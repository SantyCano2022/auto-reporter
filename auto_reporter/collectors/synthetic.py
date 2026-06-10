from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from auto_reporter.models import Commit, PullRequest, Snapshot, Ticket, TicketTransition

_SUBJECTS = ["fix rounding in totals", "add integration test", "wire new endpoint",
             "update docs", "handle null assignee", "tune retry backoff"]
_AUTHORS = ["alice", "bruno", "carla"]


def synthetic_snapshot(
    *, repo: str = "acme/webapp", project_key: str = "DEMO",
    seed: int = 42, now: datetime | None = None,
) -> Snapshot:
    now = now or datetime.now(timezone.utc)
    rng = random.Random(seed)
    day = timedelta(days=1)
    start = now - 7 * day

    def turl(n: int) -> str:
        return f"https://example.atlassian.net/browse/{project_key}-{n}"

    def prurl(n: int) -> str:
        return f"https://github.com/{repo}/pull/{n}"

    tickets = [
        Ticket(key=f"{project_key}-101", summary="Rework checkout flow", status="Done",
               assignee="Alice", url=turl(101),
               transitions=[TicketTransition(from_status="In Progress", to_status="Done",
                                             at=now - 2 * day)]),
        Ticket(key=f"{project_key}-102", summary="Fix password reset email", status="Done",
               assignee="Bruno", url=turl(102),
               transitions=[TicketTransition(from_status="In Progress", to_status="Done",
                                             at=now - 1 * day)]),
        Ticket(key=f"{project_key}-103", summary="Add payment provider B",
               status="In Progress", assignee="Carla", url=turl(103),
               in_progress_since=now - 2 * day),  # healthy
        Ticket(key=f"{project_key}-104", summary="Migrate user service to v2 API",
               status="In Progress", assignee="Alice", url=turl(104),
               in_progress_since=now - 5 * day),  # stuck (has commits)
        Ticket(key=f"{project_key}-105", summary="Refactor session storage",
               status="In Progress", assignee="Bruno", url=turl(105),
               in_progress_since=now - 4 * day),  # stuck + silent (no commits)
        Ticket(key=f"{project_key}-106", summary="Spike: evaluate feature flags",
               status="To Do", assignee=None, url=turl(106)),
        Ticket(key=f"{project_key}-107", summary="Dark mode for settings page",
               status="In Review", assignee="Carla", url=turl(107),
               in_progress_since=now - 1 * day),  # inconsistent (merged PR below)
    ]

    ticket_numbers_with_commits = [101, 101, 102, 103, 103, 104, 107]
    commits = [
        Commit(sha=f"{seed:02x}{i:038x}",
               message=f"{project_key}-{n} {rng.choice(_SUBJECTS)}",
               author=rng.choice(_AUTHORS),
               url=f"https://github.com/{repo}/commit/{seed:02x}{i:038x}",
               timestamp=start + rng.random() * (now - start))
        for i, n in enumerate(ticket_numbers_with_commits)
    ]

    pk = project_key.lower()
    prs = [
        PullRequest(number=41, title=f"{project_key}-101 Checkout rework", author="alice",
                    state="merged", head_branch=f"feat/{pk}-101-checkout", url=prurl(41),
                    created_at=now - 4 * day, merged_at=now - 2 * day),
        PullRequest(number=42, title=f"{project_key}-102 Password reset fix", author="bruno",
                    state="merged", head_branch=f"fix/{pk}-102-reset", url=prurl(42),
                    created_at=now - 3 * day, merged_at=now - 1 * day),
        PullRequest(number=43, title=f"{project_key}-103 Payment provider B (WIP)",
                    author="carla", state="open", head_branch=f"feat/{pk}-103-payments",
                    url=prurl(43), created_at=now - 2 * day),
        PullRequest(number=44, title=f"{project_key}-107 Dark mode", author="carla",
                    state="merged", head_branch=f"feat/{pk}-107-dark-mode", url=prurl(44),
                    created_at=now - 3 * day, merged_at=now - 1 * day),
    ]

    return Snapshot(repo=repo, project_key=project_key, window_start=start,
                    window_end=now, commits=commits, pull_requests=prs, tickets=tickets)
