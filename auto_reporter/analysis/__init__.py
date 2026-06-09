from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from auto_reporter.analysis.blockers import detect_blockers
from auto_reporter.analysis.correlate import correlate
from auto_reporter.analysis.stats import commits_per_author, ticket_activity
from auto_reporter.models import Digest, Snapshot


def build_digest(
    snapshot: Snapshot,
    *,
    stuck_days: int,
    silent_days: int,
    now: datetime,
    data_gaps: Sequence[str] = (),
) -> Digest:
    links = correlate(snapshot)
    done, in_progress = ticket_activity(snapshot, links)
    in_window = lambda ts: ts is not None and snapshot.window_start <= ts <= snapshot.window_end  # noqa: E731
    return Digest(
        repo=snapshot.repo,
        project_key=snapshot.project_key,
        window_start=snapshot.window_start,
        window_end=snapshot.window_end,
        total_commits=len(snapshot.commits),
        total_prs_opened=sum(1 for p in snapshot.pull_requests if in_window(p.created_at)),
        total_prs_merged=sum(1 for p in snapshot.pull_requests if in_window(p.merged_at)),
        per_author=commits_per_author(snapshot.commits),
        tickets_done=done,
        tickets_in_progress=in_progress,
        blockers=detect_blockers(snapshot, links, stuck_days=stuck_days,
                                 silent_days=silent_days, now=now),
        data_gaps=list(data_gaps),
    )
