from auto_reporter.models import Snapshot
from tests.factories import make_commit, make_pr, make_snapshot, make_ticket


def test_snapshot_json_round_trip():
    snap = make_snapshot(commits=[make_commit()], pull_requests=[make_pr()],
                         tickets=[make_ticket()])
    restored = Snapshot.model_validate_json(snap.model_dump_json())
    assert restored == snap


def test_ticket_has_no_email_field():
    ticket = make_ticket()
    assert "email" not in ticket.model_dump()  # HR2: displayName only
