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
