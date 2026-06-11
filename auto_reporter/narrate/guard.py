from __future__ import annotations

import re

from auto_reporter.models import Digest

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


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
