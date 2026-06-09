import json

from auto_reporter.state import load_last_run, save_state
from tests.factories import NOW


def test_load_returns_none_when_missing(tmp_path):
    assert load_last_run(tmp_path / "state.json") is None


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, NOW)
    assert load_last_run(path) == NOW
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "last_successful_run": NOW.isoformat()
    }
