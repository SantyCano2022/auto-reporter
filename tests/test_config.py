from pathlib import Path

from auto_reporter.config import Secrets, load_config

EXAMPLE = Path("config.example.yaml")


def test_load_example_config():
    cfg = load_config(EXAMPLE)
    assert cfg.github.repo == "acme/webapp"
    assert cfg.jira.project_key == "DEMO"
    assert cfg.report.language == "es"
    assert set(cfg.audiences) == {"technical", "executive", "client"}
    assert cfg.audiences["technical"].chat_id_env == "TG_CHAT_TECHNICAL"


def test_config_yaml_contains_no_secret_like_keys():
    text = EXAMPLE.read_text(encoding="utf-8").lower()
    for forbidden in ("token", "api_key", "password", "secret"):
        assert forbidden not in text  # HR2: config is secret-free


def test_secrets_come_only_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-x")
    monkeypatch.setenv("GROQ_API_KEY", "groq-x")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    secrets = Secrets.from_env()
    assert secrets.github_token == "gh-x"
    assert secrets.groq_api_key == "groq-x"
    assert secrets.telegram_bot_token is None
