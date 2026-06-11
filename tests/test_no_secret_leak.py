from auto_reporter.analysis import build_digest
from auto_reporter.collectors.synthetic import synthetic_snapshot
from tests.factories import NOW

SECRET_ENV_VARS = ["GITHUB_TOKEN", "JIRA_EMAIL", "JIRA_API_TOKEN",
                   "TELEGRAM_BOT_TOKEN", "GROQ_API_KEY"]


def test_artifacts_never_contain_secret_values(monkeypatch):
    """HR2 schema-level regression: the artifact models have no fields that could
    echo configured secret values. (The data-path check that real collector input
    never leaks PII lives in test_jira_collector.test_email_never_reaches_the_model.)
    """
    for var in SECRET_ENV_VARS:
        monkeypatch.setenv(var, f"sekret-{var.lower()}")

    snapshot = synthetic_snapshot(seed=7, now=NOW)
    digest = build_digest(snapshot, stuck_days=3, silent_days=3, now=NOW)
    blob = snapshot.model_dump_json() + digest.model_dump_json()

    for var in SECRET_ENV_VARS:
        assert f"sekret-{var.lower()}" not in blob


def test_secret_holders_have_redacted_reprs():
    """HR2: repr/str of credential holders must never print the credential.

    Reprs end up in logs, pytest assertion diffs and crash reports.
    """
    from auto_reporter.config import Secrets
    from auto_reporter.deliver.telegram import TelegramNotifier
    from auto_reporter.narrate.llm import GroqClient

    secrets = Secrets(github_token="gh-sekret", jira_email="jira-mail-sekret",
                      jira_api_token="jira-sekret", telegram_bot_token="tg-sekret",
                      groq_api_key="groq-sekret")
    for sentinel in ("gh-sekret", "jira-mail-sekret", "jira-sekret",
                     "tg-sekret", "groq-sekret"):
        assert sentinel not in repr(secrets)

    assert "groq-sekret" not in repr(GroqClient(api_key="groq-sekret", model="m"))
    assert "tg-sekret" not in repr(TelegramNotifier(token="tg-sekret"))
