from auto_reporter.analysis import build_digest
from auto_reporter.collectors.synthetic import synthetic_snapshot
from tests.factories import NOW


def test_same_seed_same_snapshot():
    a = synthetic_snapshot(seed=7, now=NOW)
    b = synthetic_snapshot(seed=7, now=NOW)
    assert a.model_dump_json() == b.model_dump_json()


def test_demo_digest_exhibits_every_blocker_kind():
    snap = synthetic_snapshot(seed=42, now=NOW)
    digest = build_digest(snap, stuck_days=3, silent_days=3, now=NOW)
    kinds = {b.kind for b in digest.blockers}
    assert kinds == {"stuck", "silent", "inconsistent"}
    assert digest.total_commits > 0
    assert digest.tickets_done and digest.tickets_in_progress
