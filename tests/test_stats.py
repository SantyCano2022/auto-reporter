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
