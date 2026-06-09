from datetime import datetime, timedelta, timezone

from auto_reporter.models import Commit, PullRequest, Snapshot, Ticket, TicketTransition

NOW = datetime(2026, 6, 5, 16, 0, tzinfo=timezone.utc)
WEEK_AGO = NOW - timedelta(days=7)
DAY = timedelta(days=1)


def make_commit(sha="abc123", message="PROJ-1 fix login", author="alice",
                url="https://github.com/acme/webapp/commit/abc123", timestamp=None) -> Commit:
    return Commit(sha=sha, message=message, author=author, url=url,
                  timestamp=timestamp or NOW - DAY)


def make_pr(number=10, title="PROJ-1 login fix", author="alice", state="merged",
            head_branch="fix/proj-1-login",
            url="https://github.com/acme/webapp/pull/10",
            created_at=None, merged_at=None) -> PullRequest:
    return PullRequest(number=number, title=title, author=author, state=state,
                       head_branch=head_branch, url=url,
                       created_at=created_at or NOW - 2 * DAY, merged_at=merged_at)


def make_ticket(key="PROJ-1", summary="Fix login", status="In Progress", assignee="Alice",
                url="https://example.atlassian.net/browse/PROJ-1",
                in_progress_since=None, transitions=()) -> Ticket:
    return Ticket(key=key, summary=summary, status=status, assignee=assignee, url=url,
                  in_progress_since=in_progress_since, transitions=list(transitions))


def make_snapshot(commits=(), pull_requests=(), tickets=(), repo="acme/webapp",
                  project_key="PROJ", window_start=WEEK_AGO, window_end=NOW) -> Snapshot:
    return Snapshot(repo=repo, project_key=project_key, window_start=window_start,
                    window_end=window_end, commits=list(commits),
                    pull_requests=list(pull_requests), tickets=list(tickets))


def make_transition(from_status="To Do", to_status="In Progress", at=None) -> TicketTransition:
    return TicketTransition(from_status=from_status, to_status=to_status, at=at or NOW - 3 * DAY)
