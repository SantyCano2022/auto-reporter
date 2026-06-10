from auto_reporter.analysis import build_digest
from auto_reporter.collectors.synthetic import synthetic_snapshot
from tests.factories import NOW

SECRET_ENV_VARS = ["GITHUB_TOKEN", "JIRA_EMAIL", "JIRA_API_TOKEN",
                   "TELEGRAM_BOT_TOKEN", "GROQ_API_KEY"]


def test_artifacts_never_contain_secret_values(monkeypatch):
    """HR2: snapshot.json / digest.json must carry activity only, never credentials."""
    for var in SECRET_ENV_VARS:
        monkeypatch.setenv(var, f"sekret-{var.lower()}")

    snapshot = synthetic_snapshot(seed=7, now=NOW)
    digest = build_digest(snapshot, stuck_days=3, silent_days=3, now=NOW)
    blob = snapshot.model_dump_json() + digest.model_dump_json()

    for var in SECRET_ENV_VARS:
        assert f"sekret-{var.lower()}" not in blob
