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
