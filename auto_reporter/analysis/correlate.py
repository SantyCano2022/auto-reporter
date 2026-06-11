from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from auto_reporter.models import Snapshot

_KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]+-\d+)\b")


@dataclass
class TicketLinks:
    commit_shas: set[str] = field(default_factory=set)
    pr_numbers: set[int] = field(default_factory=set)


def extract_ticket_keys(text: str, project_key: str) -> set[str]:
    prefix = project_key.upper() + "-"
    return {m.upper() for m in _KEY_RE.findall(text or "") if m.upper().startswith(prefix)}


def correlate(snapshot: Snapshot) -> dict[str, TicketLinks]:
    links: dict[str, TicketLinks] = defaultdict(TicketLinks)
    pk = snapshot.project_key
    for commit in snapshot.commits:
        for key in extract_ticket_keys(commit.message, pk):
            links[key].commit_shas.add(commit.sha)
    for pr in snapshot.pull_requests:
        for key in extract_ticket_keys(pr.title, pk) | extract_ticket_keys(pr.head_branch, pk):
            links[key].pr_numbers.add(pr.number)
    return dict(links)
