from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Commit(BaseModel):
    sha: str
    message: str
    author: str
    url: str
    timestamp: AwareDatetime


class PullRequest(BaseModel):
    number: int
    title: str
    author: str
    state: Literal["open", "closed", "merged"]
    head_branch: str
    url: str
    created_at: AwareDatetime
    merged_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _merged_at_matches_state(self) -> PullRequest:
        # digest counts merges by merged_at while blockers test state == "merged";
        # the two can only agree if the pair is consistent on every object.
        if (self.state == "merged") != (self.merged_at is not None):
            raise ValueError("merged_at must be set if and only if state is 'merged'")
        return self


class TicketTransition(BaseModel):
    from_status: str
    to_status: str
    at: AwareDatetime


class Ticket(BaseModel):
    key: str
    summary: str
    status: str
    # Jira statusCategory key ("new"/"indeterminate"/"done") — language-independent,
    # unlike status names ("En curso", "Listo"...). None in pre-existing snapshots.
    status_category: str | None = None
    assignee: str | None = None  # Jira displayName only — never emails (HR2)
    url: str
    in_progress_since: AwareDatetime | None = None
    transitions: list[TicketTransition] = []


class Snapshot(BaseModel):
    repo: str
    project_key: str
    window_start: AwareDatetime
    window_end: AwareDatetime
    commits: list[Commit] = []
    pull_requests: list[PullRequest] = []
    tickets: list[Ticket] = []
    data_gaps: list[str] = []  # sources that failed during collection — snapshot is partial

    @model_validator(mode="after")
    def _window_ordered(self) -> Snapshot:
        if self.window_start > self.window_end:
            raise ValueError("window_start must be <= window_end")
        return self


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
    window_start: AwareDatetime
    window_end: AwareDatetime
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


class _StrictConfig(BaseModel):
    # reject unknown keys so a YAML typo ("treshold:") fails loudly instead of
    # silently falling back to defaults.
    model_config = ConfigDict(extra="forbid")


class GithubConfig(_StrictConfig):
    repo: str


class JiraConfig(_StrictConfig):
    base_url: str
    project_key: str


class ReportConfig(_StrictConfig):
    language: Literal["es", "en"] = "es"


class LlmConfig(_StrictConfig):
    provider: Literal["groq"] = "groq"
    model: str = "llama-3.3-70b-versatile"


class ThresholdsConfig(_StrictConfig):
    stuck_days: int = Field(3, ge=1)
    silent_days: int = Field(3, ge=1)


class AudienceConfig(_StrictConfig):
    chat_id_env: str  # indirection keeps even chat IDs out of the repo (HR2)


class Config(_StrictConfig):
    github: GithubConfig
    jira: JiraConfig
    report: ReportConfig = ReportConfig()
    llm: LlmConfig = LlmConfig()
    thresholds: ThresholdsConfig = ThresholdsConfig()
    audiences: dict[str, AudienceConfig] = Field(min_length=1)
