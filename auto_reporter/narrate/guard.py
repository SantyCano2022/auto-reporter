from __future__ import annotations

import re

from auto_reporter.models import Digest

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")
_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _normalize(num: str) -> str:
    return num.lstrip("0") or "0"


def allowed_numbers(digest: Digest) -> set[str]:
    """Every numeral that literally appears anywhere in the digest JSON.

    Known limitation: this is deliberately broad — ticket/PR ids and date
    components are allowlisted too, so an invented count that coincides with
    one of those numerals slips through. Scoping to semantic count fields is
    tracked as a follow-up issue.
    """
    return {_normalize(n) for n in _NUM_RE.findall(digest.model_dump_json())}


def find_invented_numbers(text: str, digest: Digest) -> list[str]:
    allowed = allowed_numbers(digest)
    return [n for n in _NUM_RE.findall(text) if _normalize(n) not in allowed]


def allowed_urls(digest: Digest) -> set[str]:
    """Every URL Python put in the digest — the only link targets the model may
    use, mirroring allowed_numbers(). Anything else is an invented destination
    (e.g. a commit count linked to the bare repo root)."""
    return set(_URL_RE.findall(digest.model_dump_json()))


def strip_unbacked_links(text: str, digest: Digest) -> str:
    """Unlink any [text](url) whose url is not backed by the digest, keeping the
    visible text. Bare counts (no evidence URL) become plain numbers; genuine
    ticket/PR/blocker links survive untouched."""
    allowed = allowed_urls(digest)
    return _MD_LINK_RE.sub(
        lambda m: m.group(0) if m.group(2) in allowed else m.group(1), text)
