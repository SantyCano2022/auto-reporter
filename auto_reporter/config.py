from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from auto_reporter.models import Config


def load_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Secrets:
    # repr=False on every field: reprs end up in logs and crash reports (HR2)
    github_token: str | None = field(repr=False)
    jira_email: str | None = field(repr=False)
    jira_api_token: str | None = field(repr=False)
    telegram_bot_token: str | None = field(repr=False)
    groq_api_key: str | None = field(repr=False)

    @classmethod
    def from_env(cls) -> "Secrets":
        return cls(
            github_token=os.getenv("GITHUB_TOKEN"),
            jira_email=os.getenv("JIRA_EMAIL"),
            jira_api_token=os.getenv("JIRA_API_TOKEN"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
