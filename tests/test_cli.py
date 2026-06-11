import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def test_staged_pipeline_preserves_data_gaps(tmp_path, monkeypatch):
    """collect -> analyze must not launder a partial snapshot into a complete digest."""
    def boom(*args, **kwargs):
        raise RuntimeError("jira down")

    monkeypatch.setattr(cli_mod, "collect_jira", boom)
    monkeypatch.setattr(cli_mod, "collect_github", lambda *a, **k: ([], []))
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


def test_dry_run_does_not_advance_state(tmp_path, monkeypatch):
    """A dry run delivers nothing, so it must not move last_successful_run:
    otherwise the next real run silently skips that activity window."""
    monkeypatch.chdir(tmp_path)  # state.json is cwd-relative
    monkeypatch.setattr(cli_mod, "collect_github", lambda *a, **k: ([], []))
    monkeypatch.setattr(cli_mod, "collect_jira", lambda *a, **k: [])
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
