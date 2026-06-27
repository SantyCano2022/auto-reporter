from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from auto_reporter.models import Snapshot
from tests.factories import NOW, make_commit, make_pr, make_snapshot, make_ticket


def test_snapshot_json_round_trip():
    snap = make_snapshot(commits=[make_commit()], pull_requests=[make_pr()],
                         tickets=[make_ticket()])
    restored = Snapshot.model_validate_json(snap.model_dump_json())
    assert restored == snap


def test_ticket_has_no_email_field():
    ticket = make_ticket()
    assert "email" not in ticket.model_dump()  # HR2: displayName only


def test_naive_timestamps_are_rejected():
    """A hand-edited/restored snapshot with naive datetimes used to validate and
    then crash analyze with a naive-vs-aware TypeError; reject it at the type."""
    with pytest.raises(ValidationError):
        make_commit(timestamp=datetime(2026, 6, 1, 8, 0))  # no tzinfo


def test_aware_timestamps_are_accepted():
    assert make_commit(timestamp=datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc))


def test_merged_pr_requires_merged_at():
    with pytest.raises(ValidationError):
        make_pr(state="merged", merged_at=None)


def test_unmerged_pr_forbids_merged_at():
    with pytest.raises(ValidationError):
        make_pr(state="open", merged_at=NOW)


def test_snapshot_window_must_be_ordered():
    with pytest.raises(ValidationError):
        make_snapshot(window_start=NOW, window_end=NOW.replace(year=2025))
