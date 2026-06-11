from __future__ import annotations

import os
import sys
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


def _ensure_utf8_output() -> None:
    # Windows consoles often default to cp1252, which cannot encode the report's
    # arrows/em-dashes and would crash dry-run printing with UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None)
        if (encoding and encoding.lower().replace("-", "") != "utf8"
                and hasattr(stream, "reconfigure")):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _ensure_utf8_output()
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
    # Resolve credentials BEFORE the try blocks: typer.Exit subclasses Exception,
    # so a missing secret inside them would be swallowed into a "data gap" and the
    # config error (exit 2) would never surface.
    github_token = _require(secrets.github_token, "GITHUB_TOKEN")
    jira_email = _require(secrets.jira_email, "JIRA_EMAIL")
    jira_api_token = _require(secrets.jira_api_token, "JIRA_API_TOKEN")
    gaps: list[str] = []
    commits, prs = [], []
    tickets = []
    try:
        commits, prs = collect_github(cfg.github.repo, github_token, start, now)
    except Exception as exc:  # noqa: BLE001 — degrade, surface in report, exit non-zero
        gaps.append(f"github: collection failed ({type(exc).__name__})")
    try:
        tickets = collect_jira(cfg.jira.base_url, jira_email, jira_api_token,
                               cfg.jira.project_key, start)
    except Exception as exc:  # noqa: BLE001
        gaps.append(f"jira: collection failed ({type(exc).__name__})")
    snapshot = Snapshot(repo=cfg.github.repo, project_key=cfg.jira.project_key,
                        window_start=start, window_end=now, commits=commits,
                        pull_requests=prs, tickets=tickets, data_gaps=gaps)
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
    if not demo and not dry_run:  # dry runs deliver nothing; never advance the window
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
                          now=datetime.now(timezone.utc),
                          data_gaps=snapshot.data_gaps)
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
