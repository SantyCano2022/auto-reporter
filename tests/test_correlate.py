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
