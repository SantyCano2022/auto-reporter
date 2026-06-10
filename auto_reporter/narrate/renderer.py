from __future__ import annotations

from jinja2 import Environment, PackageLoader

from auto_reporter.models import Digest, Report
from auto_reporter.narrate.guard import find_invented_numbers
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


def build_prompt(digest: Digest, audience: str, language: str) -> str:
    return _env.get_template("report.md.j2").render(
        audience=audience, style=STYLE_GUIDES.get(audience, _DEFAULT_STYLE),
        language=language, digest_json=digest.model_dump_json(indent=2))


def render_fallback(digest: Digest, audience: str, language: str) -> str:
    return _env.get_template("fallback.md.j2").render(
        digest=digest, audience=audience, language=language)


def narrate(digest: Digest, audience: str, language: str, llm: LLMClient | None) -> Report:
    if llm is None:
        return Report(audience=audience, text=render_fallback(digest, audience, language),
                      generator="fallback", flagged=False)

    prompt = build_prompt(digest, audience, language)
    text = llm.complete(prompt)
    if not find_invented_numbers(text, digest):
        return Report(audience=audience, text=text, generator="llm", flagged=False)

    text = llm.complete(prompt + _CORRECTIVE)
    if not find_invented_numbers(text, digest):
        return Report(audience=audience, text=text, generator="llm", flagged=False)

    return Report(audience=audience, text=render_fallback(digest, audience, language),
                  generator="fallback", flagged=True)
