import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from typer.testing import CliRunner

import auto_reporter.cli as cli_mod
from auto_reporter.cli import app

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = str(REPO_ROOT / "config.example.yaml")


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


def test_run_writes_narration_meta(tmp_path):
    """generator/flagged per audience must be persisted, not just report.text,
    so a degraded (template-fallback) report is auditable after the run."""
    result = runner.invoke(app, ["run", "--demo", "--no-llm", "--dry-run",
                                 "--config", "config.example.yaml",
                                 "--artifacts-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    meta = json.loads((tmp_path / "narration_meta.json").read_text(encoding="utf-8"))
    assert set(meta) == {"technical", "executive", "client"}
    assert all(m["generator"] == "fallback" and m["flagged"] is False
               for m in meta.values())


def test_flagged_report_surfaces_github_warning_and_meta(tmp_path, monkeypatch):
    """A guard fallback in a green Actions run is invisible today; it must
    surface as a ::warning:: annotation and as flagged=True in the metadata."""
    from auto_reporter.models import Report
    monkeypatch.setattr(cli_mod, "narrate_report",
                        lambda *a, **k: Report(audience="x", text="t",
                                               generator="fallback", flagged=True))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    result = runner.invoke(app, ["run", "--demo", "--no-llm", "--dry-run",
                                 "--config", "config.example.yaml",
                                 "--artifacts-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "::warning" in result.output
    meta = json.loads((tmp_path / "narration_meta.json").read_text(encoding="utf-8"))
    assert all(m["flagged"] is True for m in meta.values())


def test_staged_narrate_writes_narration_meta(tmp_path):
    """The staged `narrate` subcommand must persist metadata too, not only run."""
    assert runner.invoke(app, ["collect", "--demo", "--config", EXAMPLE_CONFIG,
                               "--artifacts-dir", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["analyze", "--config", EXAMPLE_CONFIG,
                               "--artifacts-dir", str(tmp_path)]).exit_code == 0
    r = runner.invoke(app, ["narrate", "--no-llm", "--config", EXAMPLE_CONFIG,
                            "--artifacts-dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    meta = json.loads((tmp_path / "narration_meta.json").read_text(encoding="utf-8"))
    assert set(meta) == {"technical", "executive", "client"}


def test_run_with_partial_source_failure_delivers_but_exits_nonzero(tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("jira down")

    monkeypatch.setattr(cli_mod, "collect_jira", boom)
    monkeypatch.setattr(cli_mod, "collect_github", lambda *a, **k: ([], [], []))
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


def test_staged_pipeline_preserves_data_gaps(tmp_path, monkeypatch):
    """collect -> analyze must not launder a partial snapshot into a complete digest."""
    def boom(*args, **kwargs):
        raise RuntimeError("jira down")

    monkeypatch.setattr(cli_mod, "collect_jira", boom)
    monkeypatch.setattr(cli_mod, "collect_github", lambda *a, **k: ([], [], []))
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("JIRA_EMAIL", "x")
    monkeypatch.setenv("JIRA_API_TOKEN", "x")

    r1 = runner.invoke(app, ["collect", "--config", EXAMPLE_CONFIG,
                             "--artifacts-dir", str(tmp_path), "--window-days", "7"])
    assert r1.exit_code == 1
    snap = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    assert snap["data_gaps"] == ["jira: collection failed (RuntimeError)"]

    r2 = runner.invoke(app, ["analyze", "--config", EXAMPLE_CONFIG,
                             "--artifacts-dir", str(tmp_path)])
    assert r2.exit_code == 0, r2.output
    digest = json.loads((tmp_path / "digest.json").read_text(encoding="utf-8"))
    assert digest["data_gaps"] == ["jira: collection failed (RuntimeError)"]


def test_collect_http_error_records_status_code_in_data_gap(tmp_path, monkeypatch):
    """The gap must name the HTTP status, not just 'HTTPStatusError', so an
    operator can tell a 401 (expired token, today's incident) from a 500."""
    def boom_401(*args, **kwargs):
        req = httpx.Request("GET", "https://example.atlassian.net/rest/api/2/myself")
        raise httpx.HTTPStatusError("401 Unauthorized", request=req,
                                    response=httpx.Response(401, request=req))

    monkeypatch.setattr(cli_mod, "collect_jira", boom_401)
    monkeypatch.setattr(cli_mod, "collect_github", lambda *a, **k: ([], [], []))
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("JIRA_EMAIL", "x")
    monkeypatch.setenv("JIRA_API_TOKEN", "x")

    result = runner.invoke(app, ["collect", "--config", EXAMPLE_CONFIG,
                                 "--artifacts-dir", str(tmp_path), "--window-days", "7"])
    assert result.exit_code == 1
    snap = json.loads((tmp_path / "snapshot.json").read_text(encoding="utf-8"))
    assert snap["data_gaps"] == ["jira: collection failed (HTTP 401)"]


def test_dry_run_does_not_advance_state(tmp_path, monkeypatch):
    """A dry run delivers nothing, so it must not move last_successful_run:
    otherwise the next real run silently skips that activity window."""
    monkeypatch.chdir(tmp_path)  # state.json is cwd-relative
    monkeypatch.setattr(cli_mod, "collect_github", lambda *a, **k: ([], [], []))
    monkeypatch.setattr(cli_mod, "collect_jira", lambda *a, **k: ([], []))
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("JIRA_EMAIL", "x")
    monkeypatch.setenv("JIRA_API_TOKEN", "x")

    result = runner.invoke(app, ["run", "--no-llm", "--dry-run",
                                 "--config", EXAMPLE_CONFIG,
                                 "--artifacts-dir", str(tmp_path / "artifacts"),
                                 "--window-days", "7"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "state.json").exists()


def test_demo_dry_run_survives_cp1252_console(tmp_path):
    """README claim: the demo works in 60 seconds. Windows consoles often default
    to cp1252, which cannot encode the report's arrows/em-dashes — main() must
    reconfigure output streams instead of crashing with UnicodeEncodeError."""
    code = (
        "import sys; from auto_reporter.cli import main; "
        f"sys.argv = ['auto-reporter', 'run', '--demo', '--no-llm', '--dry-run', "
        f"'--config', 'config.example.yaml', '--artifacts-dir', {str(tmp_path)!r}]; "
        "main()"
    )
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT,
                            capture_output=True, env=env)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


def test_analyze_anchors_now_to_window_end_not_wall_clock(tmp_path, monkeypatch):
    """Re-running analyze on the same snapshot must yield the same digest:
    blocker day-counts anchor to the snapshot window, not to today."""
    r1 = runner.invoke(app, ["collect", "--demo", "--config", EXAMPLE_CONFIG,
                             "--artifacts-dir", str(tmp_path)])
    assert r1.exit_code == 0, r1.output

    class FrozenFuture(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(cli_mod, "datetime", FrozenFuture)
    r2 = runner.invoke(app, ["analyze", "--config", EXAMPLE_CONFIG,
                             "--artifacts-dir", str(tmp_path)])
    assert r2.exit_code == 0, r2.output
    digest = json.loads((tmp_path / "digest.json").read_text(encoding="utf-8"))
    stuck_days = [b["days"] for b in digest["blockers"]
                  if b["ticket_key"] == "DEMO-104" and b["kind"] == "stuck"]
    assert stuck_days == [5]  # 5 days at snapshot time, not ~3.5 years in 2030


def test_run_missing_credentials_exits_2_not_partial_report(tmp_path, monkeypatch):
    """A missing secret is a config error (exit 2), not a weekly 'data gap (Exit)'."""
    for var in ("GITHUB_TOKEN", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)

    result = runner.invoke(app, ["run", "--no-llm", "--dry-run",
                                 "--config", EXAMPLE_CONFIG,
                                 "--artifacts-dir", str(tmp_path),
                                 "--window-days", "7"])
    assert result.exit_code == 2, result.output
    assert "GITHUB_TOKEN" in result.output
    assert "(Exit)" not in result.output
