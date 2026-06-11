from __future__ import annotations

from datetime import datetime

from auto_reporter.analysis.correlate import TicketLinks
from auto_reporter.analysis.stats import is_done, is_in_progress
from auto_reporter.models import Blocker, Snapshot


def detect_blockers(
    snapshot: Snapshot,
    links: dict[str, TicketLinks],
    *,
    stuck_days: int,
    silent_days: int,
    now: datetime,
) -> list[Blocker]:
    blockers: list[Blocker] = []
    prs_by_number = {p.number: p for p in snapshot.pull_requests}

    for ticket in snapshot.tickets:
        tlinks = links.get(ticket.key, TicketLinks())

        if is_in_progress(ticket) and ticket.in_progress_since is not None:
            days = (now - ticket.in_progress_since).days
            if days > stuck_days:  # spec: "> N days"
                blockers.append(Blocker(kind="stuck", ticket_key=ticket.key,
                                        summary=ticket.summary, days=days,
                                        evidence_url=ticket.url))
            if not tlinks.commit_shas and days >= silent_days:  # spec: ">= M days"
                blockers.append(Blocker(kind="silent", ticket_key=ticket.key,
                                        summary=ticket.summary, days=days,
                                        evidence_url=ticket.url))

        if not is_done(ticket):
            for number in sorted(tlinks.pr_numbers):
                pr = prs_by_number.get(number)
                if pr is not None and pr.state == "merged":
                    blockers.append(Blocker(kind="inconsistent", ticket_key=ticket.key,
                                            summary=ticket.summary, days=None,
                                            evidence_url=pr.url))
                    break
    return blockers
