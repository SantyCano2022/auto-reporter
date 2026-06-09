from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Commit(BaseModel):
    sha: str
    message: str
    author: str
    url: str
    timestamp: datetime


class PullRequest(BaseModel):
    number: int
    title: str
    author: str
    state: Literal["open", "closed", "merged"]
    head_branch: str
    url: str
    created_at: datetime
    merged_at: datetime | None = None


class TicketTransition(BaseModel):
    from_status: str
    to_status: str
    at: datetime


class Ticket(BaseModel):
    key: str
    summary: str
    status: str
    assignee: str | None = None  # Jira displayName only — never emails (HR2)
    url: str
    in_progress_since: datetime | None = None
    transitions: list[TicketTransition] = []


class Snapshot(BaseModel):
    repo: str
    project_key: str
    window_start: datetime
    window_end: datetime
    commits: list[Commit] = []
    pull_requests: list[PullRequest] = []
    tickets: list[Ticket] = []


class TicketActivity(BaseModel):
    key: str
    summary: str
    status: str
    url: str
    commit_count: int = 0
    pr_numbers: list[int] = []


class Blocker(BaseModel):
    kind: Literal["stuck", "silent", "inconsistent"]
    ticket_key: str
    summary: str
    days: int | None = None
    evidence_url: str


class Digest(BaseModel):
    repo: str
    project_key: str
    window_start: datetime
    window_end: datetime
    total_commits: int
    total_prs_opened: int
    total_prs_merged: int
    per_author: dict[str, int]
    tickets_done: list[TicketActivity]
    tickets_in_progress: list[TicketActivity]
    blockers: list[Blocker]
    data_gaps: list[str] = []  # e.g. "jira: collection failed" — report is partial


class Report(BaseModel):
    audience: str
    text: str
    generator: Literal["llm", "fallback"]
    flagged: bool = False


class GithubConfig(BaseModel):
    repo: str


class JiraConfig(BaseModel):
    base_url: str
    project_key: str


class ReportConfig(BaseModel):
    language: Literal["es", "en"] = "es"


class LlmConfig(BaseModel):
    provider: Literal["groq"] = "groq"
    model: str = "llama-3.3-70b-versatile"


class ThresholdsConfig(BaseModel):
    stuck_days: int = 3
    silent_days: int = 3


class AudienceConfig(BaseModel):
    chat_id_env: str  # indirection keeps even chat IDs out of the repo (HR2)


class Config(BaseModel):
    github: GithubConfig
    jira: JiraConfig
    report: ReportConfig = ReportConfig()
    llm: LlmConfig = LlmConfig()
    thresholds: ThresholdsConfig = ThresholdsConfig()
    audiences: dict[str, AudienceConfig]
