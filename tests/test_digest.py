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
