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
