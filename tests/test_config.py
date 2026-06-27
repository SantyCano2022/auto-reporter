from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from auto_reporter.config import Secrets, load_config
from auto_reporter.models import Config, ThresholdsConfig

EXAMPLE = Path("config.example.yaml")


def test_thresholds_reject_unknown_keys():
    # a YAML typo ("treshold:") used to fall back to defaults silently
    with pytest.raises(ValidationError):
        ThresholdsConfig(stuck_days=3, silent_days=3, treshold=5)


def test_thresholds_must_be_positive():
    with pytest.raises(ValidationError):
        ThresholdsConfig(stuck_days=0)


def test_config_requires_at_least_one_audience():
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    data["audiences"] = {}
    with pytest.raises(ValidationError):
        Config.model_validate(data)


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
