# Auto-Reporter — Design Document

**Date:** 2026-06-09
**Status:** Approved (pending implementation plan)
**Author:** Esteban Tabares, with Claude Code

## 1. Overview

Auto-Reporter is a Python automation that, every Friday, collects the weekly activity
of one GitHub repository and one Jira project, computes deterministic statistics,
and uses an LLM to narrate them as three progress reports — technical, executive,
and client — delivered to separate Telegram chats.

It is a portfolio project. Its central engineering claim: **all numbers are computed
in Python; the LLM only narrates.** The architecture makes that boundary physical.

### Goals

- One scheduled run produces three audience-specific reports from a single data snapshot.
- Cross-correlation of Jira ticket keys with GitHub commits/PRs (the differentiating feature).
- Automatic blocker detection (stuck and inconsistent tickets).
- Zero-infrastructure: runs entirely inside GitHub Actions. No server, no database.
- Fully demoable with zero API tokens (`--demo` + template fallback).

### Non-Goals (MVP)

- Email or Slack delivery (the `Notifier` interface leaves the door open).
- Multi-team / multi-tenant, authentication, web UI.
- Interactive Telegram bot (outbound messages only).
- Incremental/webhook collection (documented as future evolution).

## 2. Hard Requirements (user conditions)

These are non-negotiable and must be verified in the implementation plan:

1. **No self-triggering loop.** Double defense: (a) the workflow triggers ONLY on
   `schedule` and `workflow_dispatch` — never on `push` — so the state commit
   structurally cannot re-trigger it; (b) the automated commit message MUST include
   `[skip ci]`, which keeps the guarantee even if a `push` trigger is ever added
   later. (`paths-ignore` is not used: it only applies to push/PR triggers, which
   this workflow does not have.)
2. **Secrets policy.**
   - All tokens (GitHub, Jira, Telegram, Groq) live EXCLUSIVELY in GitHub Actions
     Secrets, injected as environment variables at runtime. Locally, a `.env` file
     (gitignored) via `python-dotenv`. Never in the repo, never in YAML config.
   - `snapshot.json` and `digest.json` persist activity data only: titles, IDs,
     public handles, timestamps, URLs. No tokens, no Jira user emails — Jira users
     are stored as `accountId` + `displayName` only.
   - The Pydantic schemas for both artifacts have no free-form fields where
     credentials could leak; a unit test asserts no configured secret value
     appears in serialized artifacts.

## 3. Architecture

Staged pipeline; each stage is a CLI subcommand connected by JSON artifacts:

```
collect  ─→ snapshot.json   raw normalized activity (GitHub + Jira)
analyze  ─→ digest.json     deterministic stats, correlation, blockers, evidence links
narrate  ─→ report_{technical,executive,client}.md   LLM renders digest per audience
deliver  ─→ Telegram        one message (or chunked) per audience chat
```

`auto-reporter run` executes all four. GitHub Actions invokes `run` on Fridays.

Why staged: the synthetic generator injects a fake `snapshot.json` and the rest of
the pipeline is identical (demo mode for free); `analyze` is a pure JSON→JSON
function (ideal TDD target); persisted digests allow re-narrating past weeks; and
the deterministic/LLM boundary is visible in the file system.

## 4. Components

```
auto_reporter/
  models.py            Pydantic v2 schemas: Snapshot, Digest, Config, Report
  config.py            YAML loading + validation; env-var secret resolution
  state.py             state.json read/write (last successful run timestamp)
  cli.py               Typer CLI: collect | analyze | narrate | deliver | run
  collectors/
    base.py            Collector protocol
    github.py          commits, PRs (opened/merged/reviewed) via REST
    jira.py            issues + status changelog via REST (JQL on updated window)
    synthetic.py       seeded realistic fake snapshot (demo mode)
  analysis/
    stats.py           counts, per-author, per-ticket aggregations
    correlate.py       ticket-key regex over branches, commit messages, PR titles
    blockers.py        stuck / inconsistency detection rules
  narrate/
    llm.py             LLMClient protocol; GroqClient (OpenAI-compatible endpoint)
    prompts/           Jinja2 templates per audience, language-parametrized (es/en)
    renderer.py        digest→prompt→narrative; template fallback when no LLM key
    guard.py           anti-hallucination number check
  deliver/
    base.py            Notifier protocol
    telegram.py        Bot API sendMessage, Markdown, 4096-char chunking
```

### Key behaviors

- **Collection window:** `[state.last_successful_run, now]`; fallback to last 7 days
  if `state.json` is missing. `--window-days 7` override for manual runs.
- **Correlation:** extract ticket keys (`[A-Z][A-Z0-9]+-\d+`, filtered to the
  configured Jira project key) from branch names, commit messages, and PR titles.
  Produces ticket↔commits/PRs links used by stats and blockers.
- **Blocker rules (thresholds in YAML):**
  - `stuck`: ticket In Progress > N days (default 3).
  - `silent`: ticket In Progress with zero linked commits in ≥ M days (default 3).
  - `inconsistent`: PR merged but linked ticket not Done.
- **Narration:** prompt = digest JSON + audience style guide + report language.
  The model is instructed to cite only digest values.
- **Anti-hallucination guard:** extract numerals from the generated narrative and
  verify each appears in the digest (with date/version-string allowlist). On
  failure: one retry with corrective prompt, then fall back to template renderer
  and flag the report. A report with invented numbers must never ship silently.
- **Template fallback:** Jinja2 deterministic renderer used when no LLM key is
  present (zero-token demo) or when the guard fails twice. Plainer output, same
  data.
- **Audience routing:** YAML maps each audience → Telegram `chat_id`. One run
  sends three reports.

## 5. Configuration

`config.yaml` (committed, secret-free):

```yaml
github: { repo: owner/name }
jira:   { base_url: https://x.atlassian.net, project_key: PROJ }
report: { language: es }            # es | en
llm:    { provider: groq, model: llama-3.3-70b-versatile }
thresholds: { stuck_days: 3, silent_days: 3 }
audiences:
  technical: { chat_id_env: TG_CHAT_TECHNICAL }
  executive: { chat_id_env: TG_CHAT_EXECUTIVE }
  client:    { chat_id_env: TG_CHAT_CLIENT }
```

Secrets via env only: `GITHUB_TOKEN`, `JIRA_EMAIL`, `JIRA_API_TOKEN`,
`TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, plus the three chat IDs (treated as
near-secrets). The `chat_id_env` indirection keeps even chat IDs out of the repo.

## 6. Scheduling & State

`.github/workflows/weekly-report.yml`:

- `on: schedule: cron '0 16 * * 5'` (Friday 16:00 UTC) + `workflow_dispatch`.
  No `push` trigger — per Hard Requirement 1, the state commit cannot re-trigger
  the workflow structurally; `[skip ci]` in the commit message is the second layer.
- Steps: checkout → setup Python → install → `auto-reporter run` → commit
  `state.json` with message `chore: update state [skip ci]` → push.
- State is committed ONLY after a fully successful run (all four stages); a failed
  run leaves the old timestamp so the next run backfills the gap.

## 7. Error Handling

- Each stage exits non-zero on fatal error → Actions run shows red (visible failure).
- Partial source failure: if one source (e.g., Jira) fails but the other succeeds,
  generate the report from available data with an explicit "data gap" warning
  section; exit code still non-zero so the operator notices.
- HTTP: retries with exponential backoff (3 attempts) on 429/5xx for GitHub, Jira,
  Telegram, and Groq.
- Telegram delivery failure after retries: non-zero exit; state not committed.

## 8. Testing Strategy (TDD throughout)

- `analysis/*`: pure functions; unit tests with fixture snapshots — the richest
  test surface (correlation edge cases, threshold boundaries, empty weeks).
- `collectors/*`: tests against recorded HTTP fixtures (`respx`); no live calls in CI.
- `narrate/guard.py`: tests with narratives containing valid/invented numbers.
- `narrate/renderer.py`: mocked LLMClient; template fallback golden-file tests.
- `deliver/telegram.py`: chunking and Markdown-escaping tests with respx.
- Secrets-leak test per Hard Requirement 2.
- E2E: `auto-reporter run --demo --no-llm` in CI must produce three reports.

## 9. Demo & Dogfooding

- **Demo mode:** `auto-reporter run --demo [--no-llm]` — synthetic snapshot
  (seeded, reproducible), full pipeline, zero tokens needed. Front and center in
  the README so a recruiter can run it in under a minute.
- **Dogfooding:** the project is developed in its own GitHub repo with its tasks
  tracked in a free-tier Jira project; the showcase artifact is Auto-Reporter's
  real weekly report about its own development, embedded in the README.

## 10. Stack

Python 3.12 · httpx · Pydantic v2 · Typer · PyYAML · Jinja2 · python-dotenv ·
pytest + respx · ruff · GitHub Actions. Groq through its OpenAI-compatible API via
a thin in-house `LLMClient` protocol (provider-swappable by design; no LiteLLM
dependency — the adapter is ~30 lines and demonstrates the boundary better).

## 11. Milestones (1–2 weeks)

1. **M1 — Deterministic core:** schemas, `analysis/*` via TDD with fixtures.
2. **M2 — Collectors:** GitHub, Jira, synthetic; recorded-fixture tests.
3. **M3 — Narration:** LLM adapter, prompts (3 audiences × es/en), guard, fallback.
4. **M4 — Delivery + CLI:** Telegram notifier, Typer wiring, `run --demo` E2E.
5. **M5 — Ship:** workflow + state commit (loop-safe), dogfood Jira setup,
   README with demo instructions and sample reports.

## 12. Future Evolution (documented, not built)

Email/Slack notifiers · interactive bot commands · incremental SQLite collector
(approach C) for >1-week windows and Jira changelog limits · trend comparison
vs. previous weeks · multi-repo aggregation.
