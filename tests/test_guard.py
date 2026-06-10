from auto_reporter.analysis import build_digest
from auto_reporter.collectors.synthetic import synthetic_snapshot
from auto_reporter.narrate.guard import find_invented_numbers
from tests.factories import NOW

DIGEST = build_digest(synthetic_snapshot(seed=42, now=NOW),
                      stuck_days=3, silent_days=3, now=NOW)


def test_accepts_numbers_present_in_digest():
    text = f"This week the team produced {DIGEST.total_commits} commits."
    assert find_invented_numbers(text, DIGEST) == []


def test_rejects_invented_numbers():
    assert find_invented_numbers("We shipped 9999 commits!", DIGEST) == ["9999"]


def test_accepts_date_components_despite_leading_zeros():
    # digest dates serialize as e.g. "2026-06-05"; prose may say "5" or "05"
    text = "Reporte de la semana del 05 (junio 2026)."
    assert find_invented_numbers(text, DIGEST) == []


def test_accepts_ticket_numbers_from_keys():
    text = "DEMO-104 sigue en curso."
    assert find_invented_numbers(text, DIGEST) == []
