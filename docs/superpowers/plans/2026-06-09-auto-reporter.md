# Auto-Reporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Weekly multi-audience (technical/executive/client) progress reports from GitHub + Jira activity, deterministic stats narrated by an LLM, delivered to Telegram, scheduled by GitHub Actions with zero servers.

**Architecture:** Staged pipeline (`collect → analyze → narrate → deliver`) connected by JSON artifacts. All numbers are computed in Python (`analyze` is a pure function); the LLM only narrates and is checked by an anti-hallucination guard with a deterministic template fallback. State persists as a `state.json` committed by the workflow (loop-safe).

**Tech Stack:** Python 3.12 · Pydantic v2 · httpx · Typer · Jinja2 · PyYAML · python-dotenv · pytest + respx · GitHub Actions · Groq (OpenAI-compatible API) behind an in-house `LLMClient` protocol.

**Spec:** `docs/superpowers/specs/2026-06-09-auto-reporter-design.md`

## Hard Requirements verification map

| Requirement | Where enforced | Where tested |
|---|---|---|
| HR1: no self-triggering loop | Task 19 workflow: triggers ONLY `schedule` + `workflow_dispatch` (no `push`); state commit message contains `[skip ci]` | Code review of Task 19 YAML (structural) |
| HR2: secrets only in env / Actions Secrets | Task 7 (`Secrets.from_env`, YAML is secret-free, `chat_id_env` indirection); Task 19 (workflow `env:` from Secrets); `.env` gitignored (Task 1) | Task 13 secrets-leak test |
| HR2: no sensitive data in artifacts | Task 2 schemas (Jira assignee = displayName only, no email fields) | Task 13 |

## File structure

```
pyproject.toml                      package + deps + console script
config.example.yaml                 secret-free config template
.env.example                        names of required env vars (values empty)
.gitignore                          .env, artifacts/, caches
state.json                          (created at runtime by the workflow)
.github/workflows/weekly-report.yml Friday pipeline + loop-safe state commit
.github/workflows/ci.yml            pytest on push/PR
auto_reporter/
  __init__.py
  models.py                         all Pydantic schemas
  config.py                         YAML loading; Secrets.from_env()
  state.py                          last-run timestamp read/write
  http.py                           request_with_retry (backoff on 429/5xx)
  cli.py                            Typer: collect|analyze|narrate|deliver|run
  collectors/{__init__,github,jira,synthetic}.py
  analysis/{__init__,correlate,stats,blockers}.py
  narrate/{__init__,llm,guard,renderer}.py + narrate/prompts/*.j2
  deliver/{__init__,telegram}.py
tests/
  factories.py                      shared model factories
  test_models.py test_correlate.py test_stats.py test_blockers.py
  test_digest.py test_config.py test_state.py test_http.py
  test_github_collector.py test_jira_collector.py test_synthetic.py
  test_no_secret_leak.py test_llm.py test_guard.py test_renderer.py
  test_telegram.py test_cli.py
```

---

## Milestone 1 — Deterministic core

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `auto_reporter/__init__.py`, `auto_reporter/collectors/__init__.py`, `auto_reporter/analysis/__init__.py`, `auto_reporter/narrate/__init__.py`, `auto_reporter/deliver/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "auto-reporter"
version = "0.1.0"
description = "Weekly multi-audience progress reports from GitHub + Jira activity"
requires-python = ">=3.12"
dependencies = [
  "httpx>=0.27",
  "pydantic>=2.7",
  "typer>=0.12",
  "pyyaml>=6.0",
  "jinja2>=3.1",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "respx>=0.21", "ruff>=0.4"]

[project.scripts]
auto-reporter = "auto_reporter.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["auto_reporter*"]

[tool.setuptools.package-data]
"auto_reporter.narrate" = ["prompts/*.j2"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.egg-info/
.pytest_cache/
.venv/
.env
artifacts/
```

Note: `state.json` is deliberately NOT ignored — the workflow commits it.

- [ ] **Step 3: Create empty packages and a smoke test**

Create empty files: `auto_reporter/__init__.py`, `auto_reporter/collectors/__init__.py`, `auto_reporter/analysis/__init__.py`, `auto_reporter/narrate/__init__.py`, `auto_reporter/deliver/__init__.py`, `tests/__init__.py`.

`tests/test_smoke.py`:

```python
def test_package_imports():
    import auto_reporter  # noqa: F401
```

- [ ] **Step 4: Install and verify**

Run: `python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"` (Windows; on CI/Linux: `.venv/bin/pip`)
Then: `python -m pytest -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore auto_reporter tests
git commit -m "chore: project scaffolding (package, deps, pytest)"
```

### Task 2: Pydantic schemas

**Files:**
- Create: `auto_reporter/models.py`, `tests/factories.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/factories.py`:

```python
from datetime import datetime, timedelta, timezone

from auto_reporter.models import Commit, PullRequest, Snapshot, Ticket, TicketTransition

NOW = datetime(2026, 6, 5, 16, 0, tzinfo=timezone.utc)
WEEK_AGO = NOW - timedelta(days=7)
DAY = timedelta(days=1)


def make_commit(sha="abc123", message="PROJ-1 fix login", author="alice",
                url="https://github.com/acme/webapp/commit/abc123", timestamp=None) -> Commit:
    return Commit(sha=sha, message=message, author=author, url=url,
                  timestamp=timestamp or NOW - DAY)


def make_pr(number=10, title="PROJ-1 login fix", author="alice", state="merged",
            head_branch="fix/proj-1-login",
            url="https://github.com/acme/webapp/pull/10",
            created_at=None, merged_at=None) -> PullRequest:
    return PullRequest(number=number, title=title, author=author, state=state,
                       head_branch=head_branch, url=url,
                       created_at=created_at or NOW - 2 * DAY, merged_at=merged_at)


def make_ticket(key="PROJ-1", summary="Fix login", status="In Progress", assignee="Alice",
                url="https://example.atlassian.net/browse/PROJ-1",
                in_progress_since=None, transitions=()) -> Ticket:
    return Ticket(key=key, summary=summary, status=status, assignee=assignee, url=url,
                  in_progress_since=in_progress_since, transitions=list(transitions))


def make_snapshot(commits=(), pull_requests=(), tickets=(), repo="acme/webapp",
                  project_key="PROJ", window_start=WEEK_AGO, window_end=NOW) -> Snapshot:
    return Snapshot(repo=repo, project_key=project_key, window_start=window_start,
                    window_end=window_end, commits=list(commits),
                    pull_requests=list(pull_requests), tickets=list(tickets))


def make_transition(from_status="To Do", to_status="In Progress", at=None) -> TicketTransition:
    return TicketTransition(from_status=from_status, to_status=to_status, at=at or NOW - 3 * DAY)
```

`tests/test_models.py`:

```python
from auto_reporter.models import Snapshot
from tests.factories import make_commit, make_pr, make_snapshot, make_ticket


def test_snapshot_json_round_trip():
    snap = make_snapshot(commits=[make_commit()], pull_requests=[make_pr()],
                         tickets=[make_ticket()])
    restored = Snapshot.model_validate_json(snap.model_dump_json())
    assert restored == snap


def test_ticket_has_no_email_field():
    ticket = make_ticket()
    assert "email" not in ticket.model_dump()  # HR2: displayName only
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auto_reporter.models'`

- [ ] **Step 3: Write `auto_reporter/models.py`**

```python
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
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/models.py tests/factories.py tests/test_models.py
git commit -m "feat: pydantic schemas for snapshot, digest, report and config"
```

### Task 3: Ticket-key correlation

**Files:**
- Create: `auto_reporter/analysis/correlate.py`
- Test: `tests/test_correlate.py`

- [ ] **Step 1: Write the failing test**

`tests/test_correlate.py`:

```python
from auto_reporter.analysis.correlate import correlate, extract_ticket_keys
from tests.factories import make_commit, make_pr, make_snapshot


def test_extracts_uppercase_keys_from_text():
    assert extract_ticket_keys("PROJ-12 fix bug, also PROJ-7", "PROJ") == {"PROJ-12", "PROJ-7"}


def test_normalizes_lowercase_branch_style_keys():
    assert extract_ticket_keys("feat/proj-12-login", "PROJ") == {"PROJ-12"}


def test_ignores_other_project_keys():
    assert extract_ticket_keys("OTHER-3 and PROJ-1", "PROJ") == {"PROJ-1"}


def test_handles_empty_text():
    assert extract_ticket_keys("", "PROJ") == set()


def test_correlate_links_commits_and_prs_to_tickets():
    snap = make_snapshot(
        commits=[make_commit(sha="c1", message="PROJ-1 fix"),
                 make_commit(sha="c2", message="PROJ-1 more"),
                 make_commit(sha="c3", message="no key here")],
        pull_requests=[make_pr(number=10, title="PROJ-1 login fix", head_branch="fix/proj-1-x"),
                       make_pr(number=11, title="chore", head_branch="feat/proj-2-y")],
    )
    links = correlate(snap)
    assert links["PROJ-1"].commit_shas == {"c1", "c2"}
    assert links["PROJ-1"].pr_numbers == {10}
    assert links["PROJ-2"].pr_numbers == {11}
    assert "PROJ-3" not in links
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_correlate.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/analysis/correlate.py`**

```python
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from auto_reporter.models import Snapshot

_KEY_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]+-\d+)\b")


@dataclass
class TicketLinks:
    commit_shas: set[str] = field(default_factory=set)
    pr_numbers: set[int] = field(default_factory=set)


def extract_ticket_keys(text: str, project_key: str) -> set[str]:
    prefix = project_key.upper() + "-"
    return {m.upper() for m in _KEY_RE.findall(text or "") if m.upper().startswith(prefix)}


def correlate(snapshot: Snapshot) -> dict[str, TicketLinks]:
    links: dict[str, TicketLinks] = defaultdict(TicketLinks)
    pk = snapshot.project_key
    for commit in snapshot.commits:
        for key in extract_ticket_keys(commit.message, pk):
            links[key].commit_shas.add(commit.sha)
    for pr in snapshot.pull_requests:
        for key in extract_ticket_keys(pr.title, pk) | extract_ticket_keys(pr.head_branch, pk):
            links[key].pr_numbers.add(pr.number)
    return dict(links)
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_correlate.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/analysis/correlate.py tests/test_correlate.py
git commit -m "feat: GitHub<->Jira ticket-key correlation"
```

### Task 4: Activity stats

**Files:**
- Create: `auto_reporter/analysis/stats.py`
- Test: `tests/test_stats.py`

- [ ] **Step 1: Write the failing test**

`tests/test_stats.py`:

```python
from auto_reporter.analysis.correlate import TicketLinks
from auto_reporter.analysis.stats import commits_per_author, ticket_activity
from tests.factories import make_commit, make_snapshot, make_ticket


def test_commits_per_author():
    commits = [make_commit(sha=s, author=a)
               for s, a in [("c1", "alice"), ("c2", "alice"), ("c3", "bruno")]]
    assert commits_per_author(commits) == {"alice": 2, "bruno": 1}


def test_ticket_activity_partitions_done_and_in_progress():
    snap = make_snapshot(tickets=[
        make_ticket(key="PROJ-1", status="Done"),
        make_ticket(key="PROJ-2", status="In Progress"),
        make_ticket(key="PROJ-3", status="To Do"),
    ])
    links = {"PROJ-1": TicketLinks(commit_shas={"c1", "c2"}, pr_numbers={10})}
    done, in_progress = ticket_activity(snap, links)
    assert [t.key for t in done] == ["PROJ-1"]
    assert done[0].commit_count == 2
    assert done[0].pr_numbers == [10]
    assert [t.key for t in in_progress] == ["PROJ-2"]
    assert in_progress[0].commit_count == 0
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_stats.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/analysis/stats.py`**

```python
from __future__ import annotations

from collections import Counter

from auto_reporter.analysis.correlate import TicketLinks
from auto_reporter.models import Commit, Snapshot, Ticket, TicketActivity

DONE_STATUSES = {"done", "closed", "resolved"}
IN_PROGRESS_STATUSES = {"in progress", "in review"}


def is_done(ticket: Ticket) -> bool:
    return ticket.status.lower() in DONE_STATUSES


def is_in_progress(ticket: Ticket) -> bool:
    return ticket.status.lower() in IN_PROGRESS_STATUSES


def commits_per_author(commits: list[Commit]) -> dict[str, int]:
    return dict(Counter(c.author for c in commits))


def ticket_activity(
    snapshot: Snapshot, links: dict[str, TicketLinks]
) -> tuple[list[TicketActivity], list[TicketActivity]]:
    done: list[TicketActivity] = []
    in_progress: list[TicketActivity] = []
    for ticket in snapshot.tickets:
        tlinks = links.get(ticket.key, TicketLinks())
        activity = TicketActivity(
            key=ticket.key, summary=ticket.summary, status=ticket.status, url=ticket.url,
            commit_count=len(tlinks.commit_shas), pr_numbers=sorted(tlinks.pr_numbers),
        )
        if is_done(ticket):
            done.append(activity)
        elif is_in_progress(ticket):
            in_progress.append(activity)
    return done, in_progress
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_stats.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/analysis/stats.py tests/test_stats.py
git commit -m "feat: deterministic activity stats"
```

### Task 5: Blocker detection

**Files:**
- Create: `auto_reporter/analysis/blockers.py`
- Test: `tests/test_blockers.py`

- [ ] **Step 1: Write the failing test**

`tests/test_blockers.py`:

```python
from auto_reporter.analysis.blockers import detect_blockers
from auto_reporter.analysis.correlate import TicketLinks
from tests.factories import DAY, NOW, make_pr, make_snapshot, make_ticket


def _kinds(blockers):
    return sorted((b.kind, b.ticket_key) for b in blockers)


def test_stuck_requires_strictly_more_than_threshold_days():
    at_threshold = make_ticket(key="PROJ-1", in_progress_since=NOW - 3 * DAY)
    over = make_ticket(key="PROJ-2", in_progress_since=NOW - 4 * DAY)
    links = {"PROJ-1": TicketLinks(commit_shas={"c1"}), "PROJ-2": TicketLinks(commit_shas={"c2"})}
    snap = make_snapshot(tickets=[at_threshold, over])
    blockers = detect_blockers(snap, links, stuck_days=3, silent_days=3, now=NOW)
    assert _kinds(blockers) == [("stuck", "PROJ-2")]


def test_silent_requires_zero_commits_and_at_least_threshold_days():
    silent = make_ticket(key="PROJ-1", in_progress_since=NOW - 3 * DAY)
    active = make_ticket(key="PROJ-2", in_progress_since=NOW - 3 * DAY)
    links = {"PROJ-2": TicketLinks(commit_shas={"c1"})}
    snap = make_snapshot(tickets=[silent, active])
    blockers = detect_blockers(snap, links, stuck_days=99, silent_days=3, now=NOW)
    assert _kinds(blockers) == [("silent", "PROJ-1")]


def test_inconsistent_when_pr_merged_but_ticket_not_done():
    ticket = make_ticket(key="PROJ-1", status="In Review", in_progress_since=NOW - DAY)
    pr = make_pr(number=10, state="merged", merged_at=NOW - DAY)
    links = {"PROJ-1": TicketLinks(pr_numbers={10})}
    snap = make_snapshot(tickets=[ticket], pull_requests=[pr])
    blockers = detect_blockers(snap, links, stuck_days=99, silent_days=99, now=NOW)
    assert _kinds(blockers) == [("inconsistent", "PROJ-1")]
    assert blockers[0].evidence_url == pr.url


def test_done_ticket_with_merged_pr_is_not_inconsistent():
    ticket = make_ticket(key="PROJ-1", status="Done")
    pr = make_pr(number=10, state="merged", merged_at=NOW - DAY)
    links = {"PROJ-1": TicketLinks(pr_numbers={10})}
    snap = make_snapshot(tickets=[ticket], pull_requests=[pr])
    assert detect_blockers(snap, links, stuck_days=99, silent_days=99, now=NOW) == []
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_blockers.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/analysis/blockers.py`**

```python
from __future__ import annotations

from datetime import datetime

from auto_reporter.analysis.correlate import TicketLinks
from auto_reporter.analysis.stats import is_done, is_in_progress
from auto_reporter.models import Blocker, Snapshot


def detect_blockers(
    snapshot: Snapshot,
    links: dict[str, TicketLinks],
    *,
    stuck_days: int,
    silent_days: int,
    now: datetime,
) -> list[Blocker]:
    blockers: list[Blocker] = []
    prs_by_number = {p.number: p for p in snapshot.pull_requests}

    for ticket in snapshot.tickets:
        tlinks = links.get(ticket.key, TicketLinks())

        if is_in_progress(ticket) and ticket.in_progress_since is not None:
            days = (now - ticket.in_progress_since).days
            if days > stuck_days:  # spec: "> N days"
                blockers.append(Blocker(kind="stuck", ticket_key=ticket.key,
                                        summary=ticket.summary, days=days,
                                        evidence_url=ticket.url))
            if not tlinks.commit_shas and days >= silent_days:  # spec: ">= M days"
                blockers.append(Blocker(kind="silent", ticket_key=ticket.key,
                                        summary=ticket.summary, days=days,
                                        evidence_url=ticket.url))

        if not is_done(ticket):
            for number in sorted(tlinks.pr_numbers):
                pr = prs_by_number.get(number)
                if pr is not None and pr.state == "merged":
                    blockers.append(Blocker(kind="inconsistent", ticket_key=ticket.key,
                                            summary=ticket.summary, days=None,
                                            evidence_url=pr.url))
                    break
    return blockers
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_blockers.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/analysis/blockers.py tests/test_blockers.py
git commit -m "feat: stuck/silent/inconsistent blocker detection"
```

### Task 6: `build_digest` (analyze stage entrypoint)

**Files:**
- Modify: `auto_reporter/analysis/__init__.py`
- Test: `tests/test_digest.py`

- [ ] **Step 1: Write the failing test**

`tests/test_digest.py`:

```python
from auto_reporter.analysis import build_digest
from tests.factories import DAY, NOW, make_commit, make_pr, make_snapshot, make_ticket


def test_build_digest_aggregates_everything():
    snap = make_snapshot(
        commits=[make_commit(sha="c1", message="PROJ-1 fix", author="alice"),
                 make_commit(sha="c2", message="PROJ-2 wip", author="bruno")],
        pull_requests=[
            make_pr(number=10, title="PROJ-1 fix", state="merged",
                    created_at=NOW - 3 * DAY, merged_at=NOW - DAY),
            make_pr(number=11, title="PROJ-2 wip", state="open", created_at=NOW - 2 * DAY),
        ],
        tickets=[make_ticket(key="PROJ-1", status="Done"),
                 make_ticket(key="PROJ-2", status="In Progress",
                             in_progress_since=NOW - 5 * DAY)],
    )
    digest = build_digest(snap, stuck_days=3, silent_days=3, now=NOW)

    assert digest.total_commits == 2
    assert digest.total_prs_opened == 2
    assert digest.total_prs_merged == 1
    assert digest.per_author == {"alice": 1, "bruno": 1}
    assert [t.key for t in digest.tickets_done] == ["PROJ-1"]
    assert [t.key for t in digest.tickets_in_progress] == ["PROJ-2"]
    assert [(b.kind, b.ticket_key) for b in digest.blockers] == [("stuck", "PROJ-2")]
    assert digest.data_gaps == []


def test_build_digest_records_data_gaps():
    digest = build_digest(make_snapshot(), stuck_days=3, silent_days=3, now=NOW,
                          data_gaps=["jira: collection failed"])
    assert digest.data_gaps == ["jira: collection failed"]
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_digest.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_digest'`

- [ ] **Step 3: Write `auto_reporter/analysis/__init__.py`**

```python
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from auto_reporter.analysis.blockers import detect_blockers
from auto_reporter.analysis.correlate import correlate
from auto_reporter.analysis.stats import commits_per_author, ticket_activity
from auto_reporter.models import Digest, Snapshot


def build_digest(
    snapshot: Snapshot,
    *,
    stuck_days: int,
    silent_days: int,
    now: datetime,
    data_gaps: Sequence[str] = (),
) -> Digest:
    links = correlate(snapshot)
    done, in_progress = ticket_activity(snapshot, links)
    in_window = lambda ts: ts is not None and snapshot.window_start <= ts <= snapshot.window_end  # noqa: E731
    return Digest(
        repo=snapshot.repo,
        project_key=snapshot.project_key,
        window_start=snapshot.window_start,
        window_end=snapshot.window_end,
        total_commits=len(snapshot.commits),
        total_prs_opened=sum(1 for p in snapshot.pull_requests if in_window(p.created_at)),
        total_prs_merged=sum(1 for p in snapshot.pull_requests if in_window(p.merged_at)),
        per_author=commits_per_author(snapshot.commits),
        tickets_done=done,
        tickets_in_progress=in_progress,
        blockers=detect_blockers(snapshot, links, stuck_days=stuck_days,
                                 silent_days=silent_days, now=now),
        data_gaps=list(data_gaps),
    )
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_digest.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/analysis/__init__.py tests/test_digest.py
git commit -m "feat: build_digest pure analyze entrypoint"
```

---

## Milestone 2 — Config, state, collectors

### Task 7: Config loading + secrets from env

**Files:**
- Create: `auto_reporter/config.py`, `config.example.yaml`, `.env.example`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`config.example.yaml`:

```yaml
github:
  repo: acme/webapp
jira:
  base_url: https://example.atlassian.net
  project_key: DEMO
report:
  language: es
llm:
  provider: groq
  model: llama-3.3-70b-versatile
thresholds:
  stuck_days: 3
  silent_days: 3
audiences:
  technical: { chat_id_env: TG_CHAT_TECHNICAL }
  executive: { chat_id_env: TG_CHAT_EXECUTIVE }
  client: { chat_id_env: TG_CHAT_CLIENT }
```

`.env.example`:

```
# Copy to .env (gitignored). In CI these come from GitHub Actions Secrets (HR2).
GITHUB_TOKEN=
JIRA_EMAIL=
JIRA_API_TOKEN=
TELEGRAM_BOT_TOKEN=
GROQ_API_KEY=
TG_CHAT_TECHNICAL=
TG_CHAT_EXECUTIVE=
TG_CHAT_CLIENT=
```

`auto_reporter/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from auto_reporter.models import Config


def load_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Secrets:
    github_token: str | None
    jira_email: str | None
    jira_api_token: str | None
    telegram_bot_token: str | None
    groq_api_key: str | None

    @classmethod
    def from_env(cls) -> "Secrets":
        return cls(
            github_token=os.getenv("GITHUB_TOKEN"),
            jira_email=os.getenv("JIRA_EMAIL"),
            jira_api_token=os.getenv("JIRA_API_TOKEN"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/config.py config.example.yaml .env.example tests/test_config.py
git commit -m "feat: yaml config and env-only secrets (HR2)"
```

### Task 8: Run state

**Files:**
- Create: `auto_reporter/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:

```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/state.py`**

```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def load_last_run(path: Path) -> datetime | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return datetime.fromisoformat(data["last_successful_run"])


def save_state(path: Path, run_at: datetime) -> None:
    payload = json.dumps({"last_successful_run": run_at.isoformat()}, indent=2)
    path.write_text(payload + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_state.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/state.py tests/test_state.py
git commit -m "feat: last-run state persistence"
```

### Task 9: HTTP retry helper

**Files:**
- Create: `auto_reporter/http.py`
- Test: `tests/test_http.py`

- [ ] **Step 1: Write the failing test**

`tests/test_http.py`:

```python
import httpx
import pytest
import respx

from auto_reporter import http as http_mod
from auto_reporter.http import request_with_retry


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(http_mod.time, "sleep", lambda _: None)


@respx.mock
def test_retries_on_5xx_then_succeeds():
    route = respx.get("https://api.test/x").mock(side_effect=[
        httpx.Response(500), httpx.Response(502), httpx.Response(200, json={"ok": True}),
    ])
    with httpx.Client() as client:
        resp = request_with_retry(client, "GET", "https://api.test/x")
    assert resp.json() == {"ok": True}
    assert route.call_count == 3


@respx.mock
def test_raises_after_exhausting_attempts():
    respx.get("https://api.test/x").mock(return_value=httpx.Response(429))
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        request_with_retry(client, "GET", "https://api.test/x")


@respx.mock
def test_no_retry_on_4xx_other_than_429():
    route = respx.get("https://api.test/x").mock(return_value=httpx.Response(404))
    with httpx.Client() as client, pytest.raises(httpx.HTTPStatusError):
        request_with_retry(client, "GET", "https://api.test/x")
    assert route.call_count == 1
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_http.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/http.py`**

```python
from __future__ import annotations

import time

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    backoff_seconds: float = 1.0,
    **kwargs,
) -> httpx.Response:
    response: httpx.Response | None = None
    for attempt in range(attempts):
        response = client.request(method, url, **kwargs)
        if response.status_code not in RETRY_STATUS:
            response.raise_for_status()
            return response
        if attempt < attempts - 1:
            time.sleep(backoff_seconds * 2**attempt)
    assert response is not None
    response.raise_for_status()
    return response
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_http.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/http.py tests/test_http.py
git commit -m "feat: http retry with exponential backoff"
```

### Task 10: GitHub collector

**Files:**
- Create: `auto_reporter/collectors/github.py`
- Test: `tests/test_github_collector.py`

- [ ] **Step 1: Write the failing test**

`tests/test_github_collector.py`:

```python
import httpx
import respx

from auto_reporter.collectors.github import collect_github
from tests.factories import NOW, WEEK_AGO

COMMITS_PAYLOAD = [
    {
        "sha": "c1",
        "html_url": "https://github.com/acme/webapp/commit/c1",
        "commit": {"message": "PROJ-1 fix login",
                   "author": {"name": "Alice Dev", "date": "2026-06-03T10:00:00Z"}},
        "author": {"login": "alice"},
    },
    {
        "sha": "c2",
        "html_url": "https://github.com/acme/webapp/commit/c2",
        "commit": {"message": "no key",
                   "author": {"name": "Ghost", "date": "2026-06-04T10:00:00Z"}},
        "author": None,  # deleted account -> fall back to commit author name
    },
]

PRS_PAYLOAD = [
    {
        "number": 10, "title": "PROJ-1 fix", "state": "closed",
        "user": {"login": "alice"}, "head": {"ref": "fix/proj-1-login"},
        "html_url": "https://github.com/acme/webapp/pull/10",
        "created_at": "2026-06-02T09:00:00Z", "updated_at": "2026-06-04T09:00:00Z",
        "merged_at": "2026-06-04T09:00:00Z",
    },
    {
        "number": 9, "title": "old PR", "state": "open",
        "user": {"login": "bruno"}, "head": {"ref": "feat/old"},
        "html_url": "https://github.com/acme/webapp/pull/9",
        "created_at": "2026-05-01T09:00:00Z", "updated_at": "2026-05-02T09:00:00Z",
        "merged_at": None,  # updated before window -> excluded
    },
]


@respx.mock
def test_collect_github_maps_commits_and_prs():
    respx.get("https://api.github.com/repos/acme/webapp/commits").mock(
        return_value=httpx.Response(200, json=COMMITS_PAYLOAD))
    respx.get("https://api.github.com/repos/acme/webapp/pulls").mock(
        return_value=httpx.Response(200, json=PRS_PAYLOAD))

    commits, prs = collect_github("acme/webapp", "tok", WEEK_AGO, NOW)

    assert [c.sha for c in commits] == ["c1", "c2"]
    assert commits[0].author == "alice"
    assert commits[1].author == "Ghost"
    assert [p.number for p in prs] == [10]
    assert prs[0].state == "merged"
    assert prs[0].head_branch == "fix/proj-1-login"
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_github_collector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/collectors/github.py`**

```python
from __future__ import annotations

from datetime import datetime

import httpx

from auto_reporter.http import request_with_retry
from auto_reporter.models import Commit, PullRequest

API = "https://api.github.com"


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def collect_github(
    repo: str, token: str, window_start: datetime, window_end: datetime
) -> tuple[list[Commit], list[PullRequest]]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    with httpx.Client(headers=headers, timeout=30) as client:
        commits_raw = request_with_retry(
            client, "GET", f"{API}/repos/{repo}/commits",
            params={"since": window_start.isoformat(), "until": window_end.isoformat(),
                    "per_page": 100},
        ).json()
        prs_raw = request_with_retry(
            client, "GET", f"{API}/repos/{repo}/pulls",
            params={"state": "all", "sort": "updated", "direction": "desc", "per_page": 100},
        ).json()

    commits = [
        Commit(
            sha=c["sha"],
            message=c["commit"]["message"],
            author=(c.get("author") or {}).get("login") or c["commit"]["author"]["name"],
            url=c["html_url"],
            timestamp=_iso(c["commit"]["author"]["date"]),
        )
        for c in commits_raw
    ]

    prs: list[PullRequest] = []
    for p in prs_raw:
        if _iso(p["updated_at"]) < window_start:
            continue
        prs.append(PullRequest(
            number=p["number"], title=p["title"], author=p["user"]["login"],
            state="merged" if p.get("merged_at") else p["state"],
            head_branch=p["head"]["ref"], url=p["html_url"],
            created_at=_iso(p["created_at"]),
            merged_at=_iso(p["merged_at"]) if p.get("merged_at") else None,
        ))
    return commits, prs
```

Limitation (documented, accepted for MVP): single page of 100 commits/PRs per window.

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_github_collector.py -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/collectors/github.py tests/test_github_collector.py
git commit -m "feat: github commits and PRs collector"
```

### Task 11: Jira collector

**Files:**
- Create: `auto_reporter/collectors/jira.py`
- Test: `tests/test_jira_collector.py`

- [ ] **Step 1: Write the failing test**

`tests/test_jira_collector.py`:

```python
import httpx
import respx

from auto_reporter.collectors.jira import collect_jira
from tests.factories import WEEK_AGO

SEARCH_PAYLOAD = {
    "issues": [
        {
            "key": "DEMO-1",
            "fields": {
                "summary": "Fix login",
                "status": {"name": "In Progress"},
                "assignee": {"displayName": "Alice", "emailAddress": "alice@corp.com"},
            },
            "changelog": {
                "histories": [
                    {"created": "2026-06-01T08:00:00.000+0000",
                     "items": [{"field": "status", "fromString": "To Do",
                                "toString": "In Progress"}]},
                    {"created": "2026-05-20T08:00:00.000+0000",
                     "items": [{"field": "assignee", "fromString": "x", "toString": "y"}]},
                ]
            },
        },
        {
            "key": "DEMO-2",
            "fields": {"summary": "Old done", "status": {"name": "Done"}, "assignee": None},
            "changelog": {"histories": []},
        },
    ]
}


@respx.mock
def test_collect_jira_maps_tickets():
    respx.get("https://example.atlassian.net/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json=SEARCH_PAYLOAD))

    tickets = collect_jira("https://example.atlassian.net", "me@x.com", "tok",
                           "DEMO", WEEK_AGO)

    t1, t2 = tickets
    assert t1.key == "DEMO-1"
    assert t1.status == "In Progress"
    assert t1.assignee == "Alice"  # displayName only, never the email (HR2)
    assert t1.url == "https://example.atlassian.net/browse/DEMO-1"
    assert t1.in_progress_since is not None
    assert [(tr.from_status, tr.to_status) for tr in t1.transitions] == [
        ("To Do", "In Progress")]
    assert t2.assignee is None
    assert t2.in_progress_since is None


@respx.mock
def test_email_never_reaches_the_model():
    respx.get("https://example.atlassian.net/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json=SEARCH_PAYLOAD))
    tickets = collect_jira("https://example.atlassian.net", "me@x.com", "tok",
                           "DEMO", WEEK_AGO)
    assert "alice@corp.com" not in tickets[0].model_dump_json()
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_jira_collector.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/collectors/jira.py`**

```python
from __future__ import annotations

from datetime import datetime

import httpx

from auto_reporter.analysis.stats import IN_PROGRESS_STATUSES
from auto_reporter.http import request_with_retry
from auto_reporter.models import Ticket, TicketTransition


def collect_jira(
    base_url: str, email: str, api_token: str, project_key: str, window_start: datetime
) -> list[Ticket]:
    jql = f'project = {project_key} AND updated >= "{window_start:%Y-%m-%d %H:%M}"'
    with httpx.Client(auth=(email, api_token), timeout=30) as client:
        data = request_with_retry(
            client, "GET", f"{base_url}/rest/api/3/search/jql",
            params={"jql": jql, "fields": "summary,status,assignee",
                    "expand": "changelog", "maxResults": 100},
        ).json()

    tickets: list[Ticket] = []
    for issue in data["issues"]:
        fields = issue["fields"]
        status = fields["status"]["name"]
        assignee = (fields.get("assignee") or {}).get("displayName")  # HR2: no emails
        transitions = [
            TicketTransition(from_status=item["fromString"] or "",
                             to_status=item["toString"] or "",
                             at=_jira_dt(history["created"]))
            for history in issue.get("changelog", {}).get("histories", [])
            for item in history["items"]
            if item["field"] == "status"
        ]
        in_progress_since = None
        if status.lower() in IN_PROGRESS_STATUSES:
            candidates = [t.at for t in transitions if t.to_status == status]
            in_progress_since = max(candidates) if candidates else None
        tickets.append(Ticket(
            key=issue["key"], summary=fields["summary"], status=status,
            assignee=assignee, url=f"{base_url}/browse/{issue['key']}",
            in_progress_since=in_progress_since, transitions=transitions,
        ))
    return tickets


def _jira_dt(value: str) -> datetime:
    # Jira format: 2026-06-01T08:00:00.000+0000 -> needs colon in offset for fromisoformat
    if value.endswith(("+0000", "-0000")) or (len(value) > 5 and value[-5] in "+-"):
        value = value[:-2] + ":" + value[-2:]
    return datetime.fromisoformat(value)
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_jira_collector.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/collectors/jira.py tests/test_jira_collector.py
git commit -m "feat: jira tickets collector (displayName only, HR2)"
```

### Task 12: Synthetic snapshot (demo mode)

**Files:**
- Create: `auto_reporter/collectors/synthetic.py`
- Test: `tests/test_synthetic.py`

- [ ] **Step 1: Write the failing test**

`tests/test_synthetic.py`:

```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_synthetic.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/collectors/synthetic.py`**

```python
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from auto_reporter.models import Commit, PullRequest, Snapshot, Ticket, TicketTransition

_SUBJECTS = ["fix rounding in totals", "add integration test", "wire new endpoint",
             "update docs", "handle null assignee", "tune retry backoff"]
_AUTHORS = ["alice", "bruno", "carla"]


def synthetic_snapshot(
    *, repo: str = "acme/webapp", project_key: str = "DEMO",
    seed: int = 42, now: datetime | None = None,
) -> Snapshot:
    now = now or datetime.now(timezone.utc)
    rng = random.Random(seed)
    day = timedelta(days=1)
    start = now - 7 * day

    def turl(n: int) -> str:
        return f"https://example.atlassian.net/browse/{project_key}-{n}"

    def prurl(n: int) -> str:
        return f"https://github.com/{repo}/pull/{n}"

    tickets = [
        Ticket(key=f"{project_key}-101", summary="Rework checkout flow", status="Done",
               assignee="Alice", url=turl(101),
               transitions=[TicketTransition(from_status="In Progress", to_status="Done",
                                             at=now - 2 * day)]),
        Ticket(key=f"{project_key}-102", summary="Fix password reset email", status="Done",
               assignee="Bruno", url=turl(102),
               transitions=[TicketTransition(from_status="In Progress", to_status="Done",
                                             at=now - 1 * day)]),
        Ticket(key=f"{project_key}-103", summary="Add payment provider B",
               status="In Progress", assignee="Carla", url=turl(103),
               in_progress_since=now - 2 * day),  # healthy
        Ticket(key=f"{project_key}-104", summary="Migrate user service to v2 API",
               status="In Progress", assignee="Alice", url=turl(104),
               in_progress_since=now - 5 * day),  # stuck (has commits)
        Ticket(key=f"{project_key}-105", summary="Refactor session storage",
               status="In Progress", assignee="Bruno", url=turl(105),
               in_progress_since=now - 4 * day),  # stuck + silent (no commits)
        Ticket(key=f"{project_key}-106", summary="Spike: evaluate feature flags",
               status="To Do", assignee=None, url=turl(106)),
        Ticket(key=f"{project_key}-107", summary="Dark mode for settings page",
               status="In Review", assignee="Carla", url=turl(107),
               in_progress_since=now - 1 * day),  # inconsistent (merged PR below)
    ]

    ticket_numbers_with_commits = [101, 101, 102, 103, 103, 104, 107]
    commits = [
        Commit(sha=f"{seed:02x}{i:038x}",
               message=f"{project_key}-{n} {rng.choice(_SUBJECTS)}",
               author=rng.choice(_AUTHORS),
               url=f"https://github.com/{repo}/commit/{seed:02x}{i:038x}",
               timestamp=start + rng.random() * (now - start))
        for i, n in enumerate(ticket_numbers_with_commits)
    ]

    pk = project_key.lower()
    prs = [
        PullRequest(number=41, title=f"{project_key}-101 Checkout rework", author="alice",
                    state="merged", head_branch=f"feat/{pk}-101-checkout", url=prurl(41),
                    created_at=now - 4 * day, merged_at=now - 2 * day),
        PullRequest(number=42, title=f"{project_key}-102 Password reset fix", author="bruno",
                    state="merged", head_branch=f"fix/{pk}-102-reset", url=prurl(42),
                    created_at=now - 3 * day, merged_at=now - 1 * day),
        PullRequest(number=43, title=f"{project_key}-103 Payment provider B (WIP)",
                    author="carla", state="open", head_branch=f"feat/{pk}-103-payments",
                    url=prurl(43), created_at=now - 2 * day),
        PullRequest(number=44, title=f"{project_key}-107 Dark mode", author="carla",
                    state="merged", head_branch=f"feat/{pk}-107-dark-mode", url=prurl(44),
                    created_at=now - 3 * day, merged_at=now - 1 * day),
    ]

    return Snapshot(repo=repo, project_key=project_key, window_start=start,
                    window_end=now, commits=commits, pull_requests=prs, tickets=tickets)
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_synthetic.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/collectors/synthetic.py tests/test_synthetic.py
git commit -m "feat: seeded synthetic snapshot for demo mode"
```

### Task 13: Secrets-leak test (HR2)

**Files:**
- Test: `tests/test_no_secret_leak.py`

- [ ] **Step 1: Write the test (must pass immediately — it verifies an invariant)**

`tests/test_no_secret_leak.py`:

```python
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
```

- [ ] **Step 2: Run, verify pass**

Run: `python -m pytest tests/test_no_secret_leak.py -v`
Expected: `1 passed`

- [ ] **Step 3: Commit**

```bash
git add tests/test_no_secret_leak.py
git commit -m "test: artifacts never contain secret values (HR2)"
```

---

## Milestone 3 — Narration

### Task 14: LLM adapter

**Files:**
- Create: `auto_reporter/narrate/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test**

`tests/test_llm.py`:

```python
import httpx
import respx

from auto_reporter.narrate.llm import GROQ_URL, GroqClient


@respx.mock
def test_groq_client_sends_prompt_and_returns_content():
    route = respx.post(GROQ_URL).mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": "weekly report text"}}]
    }))
    client = GroqClient(api_key="groq-key", model="llama-3.3-70b-versatile")

    assert client.complete("narrate this") == "weekly report text"

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer groq-key"
    assert b"narrate this" in request.content
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/narrate/llm.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from auto_reporter.http import request_with_retry

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class GroqClient:
    api_key: str
    model: str

    def complete(self, prompt: str) -> str:
        with httpx.Client(timeout=60) as client:
            response = request_with_retry(
                client, "POST", GROQ_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "temperature": 0.3,
                      "messages": [{"role": "user", "content": prompt}]},
            )
        return response.json()["choices"][0]["message"]["content"]
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_llm.py -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/narrate/llm.py tests/test_llm.py
git commit -m "feat: LLMClient protocol with Groq adapter"
```

### Task 15: Anti-hallucination guard

**Files:**
- Create: `auto_reporter/narrate/guard.py`
- Test: `tests/test_guard.py`

- [ ] **Step 1: Write the failing test**

`tests/test_guard.py`:

```python
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
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_guard.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/narrate/guard.py`**

```python
from __future__ import annotations

import re

from auto_reporter.models import Digest

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _normalize(num: str) -> str:
    return num.lstrip("0") or "0"


def allowed_numbers(digest: Digest) -> set[str]:
    """Every numeral that literally appears anywhere in the digest JSON."""
    return {_normalize(n) for n in _NUM_RE.findall(digest.model_dump_json())}


def find_invented_numbers(text: str, digest: Digest) -> list[str]:
    allowed = allowed_numbers(digest)
    return [n for n in _NUM_RE.findall(text) if _normalize(n) not in allowed]
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_guard.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/narrate/guard.py tests/test_guard.py
git commit -m "feat: anti-hallucination number guard"
```

### Task 16: Prompts, fallback template and narrate orchestration

**Files:**
- Create: `auto_reporter/narrate/prompts/report.md.j2`, `auto_reporter/narrate/prompts/fallback.md.j2`, `auto_reporter/narrate/renderer.py`
- Test: `tests/test_renderer.py`

- [ ] **Step 1: Write the failing test**

`tests/test_renderer.py`:

```python
from auto_reporter.analysis import build_digest
from auto_reporter.collectors.synthetic import synthetic_snapshot
from auto_reporter.narrate.renderer import build_prompt, narrate, render_fallback
from tests.factories import NOW

DIGEST = build_digest(synthetic_snapshot(seed=42, now=NOW),
                      stuck_days=3, silent_days=3, now=NOW)


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _valid_text() -> str:
    return f"Commits: {DIGEST.total_commits}."


def test_prompt_embeds_digest_and_strict_rules():
    prompt = build_prompt(DIGEST, "executive", "es")
    assert "ONLY numbers" in prompt
    assert str(DIGEST.total_commits) in prompt
    assert "Spanish" in prompt


def test_fallback_is_deterministic_and_lists_blockers():
    text = render_fallback(DIGEST, "technical", "es")
    assert text == render_fallback(DIGEST, "technical", "es")
    assert "DEMO-105" in text  # silent blocker listed
    assert "Bloqueos" in text


def test_narrate_without_llm_uses_fallback():
    report = narrate(DIGEST, "client", "en", llm=None)
    assert report.generator == "fallback"
    assert report.flagged is False


def test_narrate_happy_path_uses_llm():
    llm = FakeLLM([_valid_text()])
    report = narrate(DIGEST, "executive", "es", llm=llm)
    assert report.generator == "llm"
    assert report.flagged is False


def test_narrate_retries_once_then_falls_back_flagged():
    llm = FakeLLM(["we did 9999 commits", "still 8888 commits"])
    report = narrate(DIGEST, "executive", "es", llm=llm)
    assert len(llm.prompts) == 2
    assert "previous draft cited numbers" in llm.prompts[1]
    assert report.generator == "fallback"
    assert report.flagged is True
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_renderer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the templates and renderer**

`auto_reporter/narrate/prompts/report.md.j2`:

```jinja
You are writing the weekly progress report for the "{{ audience }}" audience.
Write it in {{ "Spanish" if language == "es" else "English" }}, in Markdown.

STRICT RULES:
- Use ONLY numbers that literally appear in the DATA JSON below. Never compute,
  estimate, round, or aggregate numbers yourself. If a number you want is not in
  DATA, omit it.
- Do not invent work that is not in DATA.
- Where natural, include the evidence URLs from DATA as inline Markdown links.
- If DATA has a non-empty "data_gaps" list, state prominently that the report
  is partial and name the missing source.

STYLE: {{ style }}

DATA:
{{ digest_json }}
```

`auto_reporter/narrate/prompts/fallback.md.j2`:

```jinja
{% set es = language == "es" %}
# {{ "Reporte semanal" if es else "Weekly report" }} — {{ audience }}

{{ "Periodo" if es else "Period" }}: {{ digest.window_start.date() }} → {{ digest.window_end.date() }}
{% if digest.data_gaps %}

## ⚠ {{ "Datos incompletos" if es else "Partial data" }}
{% for gap in digest.data_gaps %}
- {{ gap }}
{% endfor %}
{% endif %}

## {{ "Actividad" if es else "Activity" }}
- Commits: {{ digest.total_commits }}
- PRs {{ "abiertos" if es else "opened" }}: {{ digest.total_prs_opened }} · {{ "mergeados" if es else "merged" }}: {{ digest.total_prs_merged }}

## {{ "Completado" if es else "Completed" }}
{% for t in digest.tickets_done %}
- [{{ t.key }}]({{ t.url }}) — {{ t.summary }} ({{ t.commit_count }} commits)
{% else %}
- {{ "Nada completado esta semana" if es else "Nothing completed this week" }}
{% endfor %}

## {{ "En curso" if es else "In progress" }}
{% for t in digest.tickets_in_progress %}
- [{{ t.key }}]({{ t.url }}) — {{ t.summary }} ({{ t.status }})
{% endfor %}

## {{ "Bloqueos" if es else "Blockers" }}
{% for b in digest.blockers %}
- **{{ b.kind }}**: [{{ b.ticket_key }}]({{ b.evidence_url }}) — {{ b.summary }}{% if b.days is not none %} ({{ b.days }} {{ "días" if es else "days" }}){% endif %}
{% else %}
- {{ "Sin bloqueos detectados" if es else "No blockers detected" }}
{% endfor %}
```

`auto_reporter/narrate/renderer.py`:

```python
from __future__ import annotations

from jinja2 import Environment, PackageLoader

from auto_reporter.models import Digest, Report
from auto_reporter.narrate.guard import find_invented_numbers
from auto_reporter.narrate.llm import LLMClient

_env = Environment(loader=PackageLoader("auto_reporter.narrate", "prompts"),
                   autoescape=False, trim_blocks=True, lstrip_blocks=True)

STYLE_GUIDES = {
    "technical": ("Detailed and precise; reference ticket keys, PR numbers and commit "
                  "activity; audience is the engineering team."),
    "executive": ("Brief and outcome-focused; progress, risks and blockers first; "
                  "no implementation jargon."),
    "client": ("Warm and plain-language; explain what improved in the product; "
               "no ticket keys, no internal jargon."),
}
_DEFAULT_STYLE = "Neutral professional summary."

_CORRECTIVE = ("\n\nIMPORTANT: your previous draft cited numbers that are NOT in DATA. "
               "Rewrite the report using only numbers that appear in DATA.")


def build_prompt(digest: Digest, audience: str, language: str) -> str:
    return _env.get_template("report.md.j2").render(
        audience=audience, style=STYLE_GUIDES.get(audience, _DEFAULT_STYLE),
        language=language, digest_json=digest.model_dump_json(indent=2))


def render_fallback(digest: Digest, audience: str, language: str) -> str:
    return _env.get_template("fallback.md.j2").render(
        digest=digest, audience=audience, language=language)


def narrate(digest: Digest, audience: str, language: str, llm: LLMClient | None) -> Report:
    if llm is None:
        return Report(audience=audience, text=render_fallback(digest, audience, language),
                      generator="fallback", flagged=False)

    prompt = build_prompt(digest, audience, language)
    text = llm.complete(prompt)
    if not find_invented_numbers(text, digest):
        return Report(audience=audience, text=text, generator="llm", flagged=False)

    text = llm.complete(prompt + _CORRECTIVE)
    if not find_invented_numbers(text, digest):
        return Report(audience=audience, text=text, generator="llm", flagged=False)

    return Report(audience=audience, text=render_fallback(digest, audience, language),
                  generator="fallback", flagged=True)
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_renderer.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/narrate/prompts auto_reporter/narrate/renderer.py tests/test_renderer.py
git commit -m "feat: audience prompts, guard-checked narration, template fallback"
```

---

## Milestone 4 — Delivery + CLI

### Task 17: Telegram notifier

**Files:**
- Create: `auto_reporter/deliver/telegram.py`
- Test: `tests/test_telegram.py`

- [ ] **Step 1: Write the failing test**

`tests/test_telegram.py`:

```python
import httpx
import respx

from auto_reporter.deliver.telegram import TelegramNotifier, split_message

API = "https://api.telegram.org/botTOKEN/sendMessage"


def test_split_short_message_is_single_chunk():
    assert split_message("hola") == ["hola"]


def test_split_prefers_paragraph_boundaries():
    text = "a" * 3000 + "\n\n" + "b" * 3000
    chunks = split_message(text, limit=4096)
    assert chunks == ["a" * 3000, "b" * 3000]


def test_split_hard_splits_oversized_paragraph():
    text = "x" * 9000
    chunks = split_message(text, limit=4096)
    assert [len(c) for c in chunks] == [4096, 4096, 808]


@respx.mock
def test_send_posts_each_chunk():
    route = respx.post(API).mock(return_value=httpx.Response(200, json={"ok": True}))
    notifier = TelegramNotifier(token="TOKEN")
    notifier.send("123", "a" * 3000 + "\n\n" + "b" * 3000)
    assert route.call_count == 2


@respx.mock
def test_send_retries_without_markdown_on_400():
    route = respx.post(API).mock(side_effect=[
        httpx.Response(400, json={"ok": False, "description": "can't parse entities"}),
        httpx.Response(200, json={"ok": True}),
    ])
    TelegramNotifier(token="TOKEN").send("123", "broken _markdown")
    assert route.call_count == 2
    import json
    assert "parse_mode" not in json.loads(route.calls[1].request.content)
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `auto_reporter/deliver/telegram.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

import httpx

from auto_reporter.http import request_with_retry

TELEGRAM_LIMIT = 4096


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


@dataclass(frozen=True)
class TelegramNotifier:
    token: str

    def send(self, chat_id: str, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        with httpx.Client(timeout=30) as client:
            for chunk in split_message(text):
                try:
                    request_with_retry(client, "POST", url, json={
                        "chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"})
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 400:
                        raise
                    # LLM markdown that Telegram can't parse -> resend as plain text
                    request_with_retry(client, "POST", url,
                                       json={"chat_id": chat_id, "text": chunk})
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_telegram.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/deliver/telegram.py tests/test_telegram.py
git commit -m "feat: telegram notifier with chunking and markdown fallback"
```

### Task 18: Typer CLI + E2E demo test

**Files:**
- Create: `auto_reporter/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
from typer.testing import CliRunner

import auto_reporter.cli as cli_mod
from auto_reporter.cli import app

runner = CliRunner()


def test_run_demo_no_llm_dry_run_produces_three_reports(tmp_path):
    result = runner.invoke(app, ["run", "--demo", "--no-llm", "--dry-run",
                                 "--config", "config.example.yaml",
                                 "--artifacts-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "snapshot.json").exists()
    assert (tmp_path / "digest.json").exists()
    for audience in ("technical", "executive", "client"):
        report = tmp_path / f"report_{audience}.md"
        assert report.exists()
        assert "DEMO-" in report.read_text(encoding="utf-8")


def test_run_with_partial_source_failure_delivers_but_exits_nonzero(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("jira down")

    monkeypatch.setattr(cli_mod, "collect_jira", boom)
    monkeypatch.setattr(cli_mod, "collect_github", lambda *a, **k: ([], []))
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("JIRA_EMAIL", "x")
    monkeypatch.setenv("JIRA_API_TOKEN", "x")

    result = runner.invoke(app, ["run", "--no-llm", "--dry-run",
                                 "--config", "config.example.yaml",
                                 "--artifacts-dir", str(tmp_path),
                                 "--window-days", "7"])
    assert result.exit_code == 1
    report = (tmp_path / "report_technical.md").read_text(encoding="utf-8")
    assert "jira" in report.lower()  # data gap surfaced in the report
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError` (no `auto_reporter.cli`)

- [ ] **Step 3: Write `auto_reporter/cli.py`**

```python
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer
from dotenv import load_dotenv

from auto_reporter.analysis import build_digest
from auto_reporter.collectors.github import collect_github
from auto_reporter.collectors.jira import collect_jira
from auto_reporter.collectors.synthetic import synthetic_snapshot
from auto_reporter.config import Secrets, load_config
from auto_reporter.deliver.telegram import TelegramNotifier
from auto_reporter.models import Config, Digest, Snapshot
from auto_reporter.narrate.llm import GroqClient, LLMClient
from auto_reporter.narrate.renderer import narrate as narrate_report
from auto_reporter.state import load_last_run, save_state

app = typer.Typer(no_args_is_help=True, add_completion=False,
                  help="Weekly GitHub+Jira progress reports.")

STATE_PATH = Path("state.json")

ConfigOpt = typer.Option(Path("config.yaml"), "--config", help="Path to config.yaml")
ArtifactsOpt = typer.Option(Path("artifacts"), "--artifacts-dir")


def main() -> None:
    load_dotenv()
    app()


def _require(value: str | None, name: str) -> str:
    if not value:
        typer.echo(f"Missing required env var: {name}", err=True)
        raise typer.Exit(code=2)
    return value


def _window_start(window_days: int | None, now: datetime) -> datetime:
    if window_days is not None:
        return now - timedelta(days=window_days)
    return load_last_run(STATE_PATH) or now - timedelta(days=7)


def _collect(cfg: Config, secrets: Secrets, start: datetime, now: datetime,
             demo: bool) -> tuple[Snapshot, list[str]]:
    if demo:
        return synthetic_snapshot(now=now), []
    gaps: list[str] = []
    commits, prs = [], []
    tickets = []
    try:
        commits, prs = collect_github(
            cfg.github.repo, _require(secrets.github_token, "GITHUB_TOKEN"), start, now)
    except Exception as exc:  # noqa: BLE001 — degrade, surface in report, exit non-zero
        gaps.append(f"github: collection failed ({type(exc).__name__})")
    try:
        tickets = collect_jira(
            cfg.jira.base_url, _require(secrets.jira_email, "JIRA_EMAIL"),
            _require(secrets.jira_api_token, "JIRA_API_TOKEN"),
            cfg.jira.project_key, start)
    except Exception as exc:  # noqa: BLE001
        gaps.append(f"jira: collection failed ({type(exc).__name__})")
    snapshot = Snapshot(repo=cfg.github.repo, project_key=cfg.jira.project_key,
                        window_start=start, window_end=now, commits=commits,
                        pull_requests=prs, tickets=tickets)
    return snapshot, gaps


def _make_llm(no_llm: bool, secrets: Secrets, cfg: Config) -> LLMClient | None:
    if no_llm:
        return None
    if secrets.groq_api_key:
        return GroqClient(api_key=secrets.groq_api_key, model=cfg.llm.model)
    typer.echo("GROQ_API_KEY not set — falling back to template narration.", err=True)
    return None


def _narrate_and_deliver(cfg: Config, digest: Digest, artifacts_dir: Path,
                         llm: LLMClient | None, notifier: TelegramNotifier | None) -> None:
    for audience, audience_cfg in cfg.audiences.items():
        report = narrate_report(digest, audience, cfg.report.language, llm)
        (artifacts_dir / f"report_{audience}.md").write_text(report.text, encoding="utf-8")
        if report.flagged:
            typer.echo(f"[guard] {audience}: invented numbers twice; used fallback.",
                       err=True)
        if notifier is None:
            typer.echo(f"\n===== {audience} =====\n{report.text}")
        else:
            chat_id = _require(os.getenv(audience_cfg.chat_id_env),
                               audience_cfg.chat_id_env)
            notifier.send(chat_id, report.text)


@app.command()
def run(config: Path = ConfigOpt, artifacts_dir: Path = ArtifactsOpt,
        demo: bool = typer.Option(False, help="Synthetic data; no tokens needed."),
        no_llm: bool = typer.Option(False, help="Deterministic template narration."),
        dry_run: bool = typer.Option(False, help="Print reports instead of sending."),
        window_days: int | None = typer.Option(None)) -> None:
    """Full pipeline: collect -> analyze -> narrate -> deliver."""
    cfg = load_config(config)
    secrets = Secrets.from_env()
    now = datetime.now(timezone.utc)
    start = _window_start(window_days, now)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    snapshot, gaps = _collect(cfg, secrets, start, now, demo)
    (artifacts_dir / "snapshot.json").write_text(snapshot.model_dump_json(indent=2),
                                                 encoding="utf-8")
    digest = build_digest(snapshot, stuck_days=cfg.thresholds.stuck_days,
                          silent_days=cfg.thresholds.silent_days, now=now, data_gaps=gaps)
    (artifacts_dir / "digest.json").write_text(digest.model_dump_json(indent=2),
                                               encoding="utf-8")

    llm = _make_llm(no_llm, secrets, cfg)
    notifier = None if dry_run else TelegramNotifier(
        token=_require(secrets.telegram_bot_token, "TELEGRAM_BOT_TOKEN"))
    _narrate_and_deliver(cfg, digest, artifacts_dir, llm, notifier)

    if gaps:
        typer.echo(f"Data gaps: {gaps} — report is partial.", err=True)
        raise typer.Exit(code=1)
    if not demo:
        save_state(STATE_PATH, now)


@app.command()
def collect(config: Path = ConfigOpt, artifacts_dir: Path = ArtifactsOpt,
            demo: bool = typer.Option(False),
            window_days: int | None = typer.Option(None)) -> None:
    """Stage 1: fetch activity into artifacts/snapshot.json."""
    cfg = load_config(config)
    now = datetime.now(timezone.utc)
    snapshot, gaps = _collect(cfg, Secrets.from_env(),
                              _window_start(window_days, now), now, demo)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "snapshot.json").write_text(snapshot.model_dump_json(indent=2),
                                                 encoding="utf-8")
    if gaps:
        typer.echo(f"Data gaps: {gaps}", err=True)
        raise typer.Exit(code=1)


@app.command()
def analyze(config: Path = ConfigOpt, artifacts_dir: Path = ArtifactsOpt) -> None:
    """Stage 2: snapshot.json -> digest.json (pure, deterministic)."""
    cfg = load_config(config)
    snapshot = Snapshot.model_validate_json(
        (artifacts_dir / "snapshot.json").read_text(encoding="utf-8"))
    digest = build_digest(snapshot, stuck_days=cfg.thresholds.stuck_days,
                          silent_days=cfg.thresholds.silent_days,
                          now=datetime.now(timezone.utc))
    (artifacts_dir / "digest.json").write_text(digest.model_dump_json(indent=2),
                                               encoding="utf-8")


@app.command(name="narrate")
def narrate_cmd(config: Path = ConfigOpt, artifacts_dir: Path = ArtifactsOpt,
                no_llm: bool = typer.Option(False)) -> None:
    """Stage 3: digest.json -> report_<audience>.md files."""
    cfg = load_config(config)
    digest = Digest.model_validate_json(
        (artifacts_dir / "digest.json").read_text(encoding="utf-8"))
    llm = _make_llm(no_llm, Secrets.from_env(), cfg)
    for audience in cfg.audiences:
        report = narrate_report(digest, audience, cfg.report.language, llm)
        (artifacts_dir / f"report_{audience}.md").write_text(report.text, encoding="utf-8")


@app.command()
def deliver(config: Path = ConfigOpt, artifacts_dir: Path = ArtifactsOpt,
            dry_run: bool = typer.Option(False)) -> None:
    """Stage 4: send report_<audience>.md files to their Telegram chats."""
    cfg = load_config(config)
    secrets = Secrets.from_env()
    notifier = None if dry_run else TelegramNotifier(
        token=_require(secrets.telegram_bot_token, "TELEGRAM_BOT_TOKEN"))
    for audience, audience_cfg in cfg.audiences.items():
        text = (artifacts_dir / f"report_{audience}.md").read_text(encoding="utf-8")
        if notifier is None:
            typer.echo(f"\n===== {audience} =====\n{text}")
        else:
            notifier.send(_require(os.getenv(audience_cfg.chat_id_env),
                                   audience_cfg.chat_id_env), text)
```

- [ ] **Step 4: Run the full suite, verify pass**

Run: `python -m pytest -v`
Expected: all tests pass (including both new CLI tests)

- [ ] **Step 5: Commit**

```bash
git add auto_reporter/cli.py tests/test_cli.py
git commit -m "feat: typer CLI with staged pipeline, demo mode and degraded-run handling"
```

---

## Milestone 5 — Ship

### Task 19: GitHub Actions workflows (HR1)

**Files:**
- Create: `.github/workflows/weekly-report.yml`, `.github/workflows/ci.yml`

- [ ] **Step 1: Write `.github/workflows/weekly-report.yml`**

```yaml
name: weekly-report

# Hard Requirement 1: NO `push` trigger — the state commit below can never
# re-trigger this workflow structurally. `[skip ci]` in the commit message is
# the second defense layer in case a push trigger is ever added.
on:
  schedule:
    - cron: "0 16 * * 5" # Friday 16:00 UTC
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install .
      - name: Generate and deliver weekly report
        env:
          # HR2: every credential comes from Actions Secrets; none live in the repo.
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
          JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          TG_CHAT_TECHNICAL: ${{ secrets.TG_CHAT_TECHNICAL }}
          TG_CHAT_EXECUTIVE: ${{ secrets.TG_CHAT_EXECUTIVE }}
          TG_CHAT_CLIENT: ${{ secrets.TG_CHAT_CLIENT }}
        run: auto-reporter run
      - name: Commit state (only reached on success)
        run: |
          git config user.name "auto-reporter-bot"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add state.json
          git diff --cached --quiet || git commit -m "chore: update state [skip ci]"
          git push
```

Note: the built-in `secrets.GITHUB_TOKEN` can read the same repo and push the state
commit. To report on a *different* repo, create a PAT secret and swap it in.

- [ ] **Step 2: Write `.github/workflows/ci.yml`**

```yaml
name: ci
on:
  push:
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: python -m pytest -v
      - name: E2E zero-token demo
        run: |
          pip install .
          auto-reporter run --demo --no-llm --dry-run --config config.example.yaml
```

- [ ] **Step 3: Validate YAML locally**

Run: `python -c "import yaml,glob; [yaml.safe_load(open(f,encoding='utf-8')) for f in glob.glob('.github/workflows/*.yml')]; print('YAML OK')"`
Expected: `YAML OK`

- [ ] **Step 4: Manual HR1 review checklist**

Confirm by reading the file: (a) `on:` contains only `schedule` and `workflow_dispatch`;
(b) the commit message contains `[skip ci]`; (c) state commit step runs after the
report step succeeded.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows
git commit -m "ci: weekly pipeline with loop-safe state commit (HR1) and test workflow"
```

### Task 20: README + final polish

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# Auto-Reporter

Weekly engineering progress reports, written for three audiences at once.

Every Friday, Auto-Reporter collects the week's activity from a GitHub repository
and a Jira project, computes the statistics deterministically in Python, and has
an LLM narrate them as three different reports — technical, executive, and
client — each delivered to its own Telegram chat. No servers: the whole pipeline
runs inside a scheduled GitHub Actions job.

## The engineering claim

**The LLM never counts.** All numbers are computed in Python; the model receives
a structured digest and only writes prose. A guard verifies every numeral in the
output exists in the digest — if the model invents numbers twice, the report
falls back to a deterministic template and is flagged. The pipeline makes this
boundary physical:

    collect  ->  snapshot.json   raw normalized activity (GitHub + Jira)
    analyze  ->  digest.json     stats, cross-correlation, blockers, evidence links
    narrate  ->  report_*.md     LLM narration per audience (guard-checked)
    deliver  ->  Telegram        one chat per audience

## Try it in 60 seconds (no tokens needed)

    pip install -e .
    auto-reporter run --demo --no-llm --dry-run --config config.example.yaml

`--demo` uses a seeded synthetic week of activity; `--no-llm` uses the
deterministic template renderer; `--dry-run` prints instead of sending.
Add a `GROQ_API_KEY` to `.env` and drop `--no-llm` to see real LLM narration.

## What makes the reports smart

- **GitHub <-> Jira correlation:** ticket keys (`PROJ-123`) are extracted from
  branch names, commit messages and PR titles, linking code activity to tickets.
- **Blocker detection:** `stuck` (In Progress > N days), `silent` (In Progress
  with zero linked commits >= M days), `inconsistent` (PR merged but ticket not
  Done). Thresholds in `config.yaml`.
- **Evidence links:** every claim links to the PR or ticket behind it.

## Real setup

1. Copy `config.example.yaml` to `config.yaml` (repo, Jira project, thresholds,
   report language `es`/`en`).
2. Create a Telegram bot (@BotFather) and three chats/groups; get their chat IDs.
3. Add GitHub Actions Secrets: `JIRA_EMAIL`, `JIRA_API_TOKEN`,
   `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, `TG_CHAT_TECHNICAL`,
   `TG_CHAT_EXECUTIVE`, `TG_CHAT_CLIENT`. (The built-in `GITHUB_TOKEN` covers
   reading this repo; use a PAT to report on another repo.)
4. The `weekly-report` workflow runs Fridays 16:00 UTC, or trigger it manually
   from the Actions tab.

Secrets live only in Actions Secrets / a gitignored `.env`. The JSON artifacts
persist activity data only (no tokens, no emails) — enforced by tests.

State between runs is a `state.json` committed by the workflow itself. The
workflow has no `push` trigger and the commit says `[skip ci]`, so it can never
trigger itself.

## Dogfooding

This repo reports on its own development: its tasks are tracked in a free-tier
Jira project, and the sample report below was generated by Auto-Reporter about
Auto-Reporter.

## Future work

Email/Slack notifiers · interactive bot commands · incremental SQLite collector
for long windows · week-over-week trends · multi-repo aggregation.
```

- [ ] **Step 2: Full suite + lint**

Run: `python -m pytest -v && python -m ruff check .`
Expected: all tests pass, no lint errors

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README with demo quickstart and setup guide"
```

- [ ] **Step 4 (manual, outside the repo):** create the GitHub repo, push, configure
the Actions Secrets listed in the README, create the free-tier Jira project for
dogfooding, and run the workflow once via `workflow_dispatch` to validate end-to-end.
