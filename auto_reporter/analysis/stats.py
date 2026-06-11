from __future__ import annotations

from collections import Counter

from auto_reporter.analysis.correlate import TicketLinks
from auto_reporter.models import Commit, Snapshot, Ticket, TicketActivity

DONE_STATUSES = {"done", "closed", "resolved"}
IN_PROGRESS_STATUSES = {"in progress", "in review"}


def is_done(ticket: Ticket) -> bool:
    # statusCategory is language-independent; status names are only a fallback
    # for snapshots collected before the category was captured.
    if ticket.status_category is not None:
        return ticket.status_category == "done"
    return ticket.status.lower() in DONE_STATUSES


def is_in_progress(ticket: Ticket) -> bool:
    if ticket.status_category is not None:
        return ticket.status_category == "indeterminate"
    return ticket.status.lower() in IN_PROGRESS_STATUSES


def commits_per_author(commits: list[Commit]) -> dict[str, int]:
    return dict(Counter(c.author for c in commits))


def ticket_activity(
    snapshot: Snapshot, links: dict[str, TicketLinks]
) -> tuple[list[TicketActivity], list[TicketActivity]]:
    done: list[TicketActivity] = []
    in_progress: list[TicketActivity] = []
    for ticket in snapshot.tickets:
        tlinks = links.get(ticket.key, TicketLinks())
        activity = TicketActivity(
            key=ticket.key, summary=ticket.summary, status=ticket.status, url=ticket.url,
            commit_count=len(tlinks.commit_shas), pr_numbers=sorted(tlinks.pr_numbers),
        )
        if is_done(ticket):
            done.append(activity)
        elif is_in_progress(ticket):
            in_progress.append(activity)
    return done, in_progress
