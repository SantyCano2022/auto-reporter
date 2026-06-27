from __future__ import annotations

import json

import httpx
from jinja2 import Environment, PackageLoader

from auto_reporter.models import Digest, Report
from auto_reporter.narrate.guard import find_invented_numbers, strip_unbacked_links
from auto_reporter.narrate.llm import LLMClient

_env = Environment(loader=PackageLoader("auto_reporter.narrate", "prompts"),
                   autoescape=False, trim_blocks=True, lstrip_blocks=True)

STYLE_GUIDES = {
    "technical": ("Detailed and precise; reference ticket keys, PR numbers and commit "
                  "activity; audience is the engineering team."),
    "executive": ("Brief and outcome-focused; progress, risks and blockers first; "
                  "no implementation jargon."),
    "client": ("Warm and plain-language; explain what improved in the product; "
               "no ticket keys, no internal jargon."),
}
_DEFAULT_STYLE = "Neutral professional summary."

_CORRECTIVE = ("\n\nIMPORTANT: your previous draft cited numbers that are NOT in DATA. "
               "Rewrite the report using only numbers that appear in DATA.")


def _bot_safe(name: str) -> str:
    # "github-actions[bot]" breaks Markdown link text ([x[bot]](url)); the
    # parenthesised form reads the same and is link-safe.
    return f"{name[:-len('[bot]')]} (bot)" if name.endswith("[bot]") else name


def _llm_digest_json(digest: Digest) -> str:
    """The digest as the LLM should see it: date-only window bounds (raw ISO
    timestamps leaked into prose) and Markdown-safe author names. The guard
    still scores against the full-precision digest, and these are subsets of
    its numerals, so nothing new is flagged."""
    data = json.loads(digest.model_dump_json())
    data["window_start"] = f"{digest.window_start:%Y-%m-%d}"
    data["window_end"] = f"{digest.window_end:%Y-%m-%d}"
    data["per_author"] = {_bot_safe(k): v for k, v in data["per_author"].items()}
    return json.dumps(data, indent=2, ensure_ascii=False)


def build_prompt(digest: Digest, audience: str, language: str) -> str:
    return _env.get_template("report.md.j2").render(
        audience=audience, style=STYLE_GUIDES.get(audience, _DEFAULT_STYLE),
        language=language, digest_json=_llm_digest_json(digest))


def render_fallback(digest: Digest, audience: str, language: str) -> str:
    return _env.get_template("fallback.md.j2").render(
        digest=digest, audience=audience, language=language)


def _complete_or_none(llm: LLMClient, prompt: str) -> str | None:
    """LLM outages and schema drift degrade to the template; they never kill the run."""
    try:
        return llm.complete(prompt)
    except (httpx.HTTPError, KeyError, IndexError):
        return None


def narrate(digest: Digest, audience: str, language: str, llm: LLMClient | None) -> Report:
    if llm is None:
        return Report(audience=audience, text=render_fallback(digest, audience, language),
                      generator="fallback", flagged=False)

    prompt = build_prompt(digest, audience, language)
    text = _complete_or_none(llm, prompt)
    if text is not None and not find_invented_numbers(text, digest):
        return Report(audience=audience, text=strip_unbacked_links(text, digest),
                      generator="llm", flagged=False)

    if text is not None:  # invented numbers -> one corrective retry (skip if LLM is down)
        text = _complete_or_none(llm, prompt + _CORRECTIVE)
        if text is not None and not find_invented_numbers(text, digest):
            return Report(audience=audience, text=strip_unbacked_links(text, digest),
                          generator="llm", flagged=False)

    return Report(audience=audience, text=render_fallback(digest, audience, language),
                  generator="fallback", flagged=True)
