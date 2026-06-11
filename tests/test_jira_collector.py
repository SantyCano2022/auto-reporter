import httpx
import respx

from auto_reporter.collectors.jira import collect_jira
from tests.factories import WEEK_AGO

SEARCH_PAYLOAD = {
    "issues": [
        {
            "key": "DEMO-1",
            "fields": {
                "summary": "Fix login",
                "status": {"name": "In Progress"},
                "assignee": {"displayName": "Alice", "emailAddress": "alice@corp.com"},
            },
            "changelog": {
                "histories": [
                    {"created": "2026-06-01T08:00:00.000+0000",
                     "items": [{"field": "status", "fromString": "To Do",
                                "toString": "In Progress"}]},
                    {"created": "2026-05-20T08:00:00.000+0000",
                     "items": [{"field": "assignee", "fromString": "x", "toString": "y"}]},
                ]
            },
        },
        {
            "key": "DEMO-2",
            "fields": {"summary": "Old done", "status": {"name": "Done"}, "assignee": None},
            "changelog": {"histories": []},
        },
    ]
}


def _mock_jira(search_payload, timezone="Etc/UTC"):
    respx.get("https://example.atlassian.net/rest/api/2/myself").mock(
        return_value=httpx.Response(200, json={"timeZone": timezone}))
    return respx.get("https://example.atlassian.net/rest/api/3/search/jql").mock(
        return_value=httpx.Response(200, json=search_payload))


@respx.mock
def test_collect_jira_maps_tickets():
    _mock_jira(SEARCH_PAYLOAD)

    tickets = collect_jira("https://example.atlassian.net", "me@x.com", "tok",
                           "DEMO", WEEK_AGO)

    t1, t2 = tickets
    assert t1.key == "DEMO-1"
    assert t1.status == "In Progress"
    assert t1.assignee == "Alice"  # displayName only, never the email (HR2)
    assert t1.url == "https://example.atlassian.net/browse/DEMO-1"
    assert t1.in_progress_since is not None
    assert [(tr.from_status, tr.to_status) for tr in t1.transitions] == [
        ("To Do", "In Progress")]
    assert t2.assignee is None
    assert t2.in_progress_since is None


SPANISH_PAYLOAD = {
    "issues": [
        {
            "key": "SCRUM-2",
            "fields": {
                "summary": "Tarea 2",
                "status": {"name": "En curso",
                           "statusCategory": {"key": "indeterminate"}},
                "assignee": None,
            },
            "changelog": {
                "histories": [
                    {"created": "2026-06-01T08:00:00.000+0000",
                     "items": [{"field": "status", "fromString": "Tareas por hacer",
                                "toString": "En curso"}]},
                ]
            },
        },
    ]
}


@respx.mock
def test_collect_jira_uses_status_category_on_non_english_sites():
    _mock_jira(SPANISH_PAYLOAD)

    (ticket,) = collect_jira("https://example.atlassian.net", "me@x.com", "tok",
                             "SCRUM", WEEK_AGO)

    assert ticket.status == "En curso"
    assert ticket.status_category == "indeterminate"
    # in_progress_since must be derived from the category, not English names
    assert ticket.in_progress_since is not None


@respx.mock
def test_jql_window_converted_to_profile_timezone():
    # Jira evaluates naive JQL datetimes in the API user's profile timezone,
    # not UTC: sending the UTC wall-clock to a UTC-5 profile shifts the window
    # 5h late and silently drops recently-updated tickets.
    search = _mock_jira(SEARCH_PAYLOAD, timezone="America/Bogota")

    collect_jira("https://example.atlassian.net", "me@x.com", "tok",
                 "DEMO", WEEK_AGO)  # 2026-05-29 16:00 UTC

    jql = search.calls.last.request.url.params["jql"]
    assert 'updated >= "2026-05-29 11:00"' in jql  # 16:00 UTC == 11:00 Bogota


@respx.mock
def test_email_never_reaches_the_model():
    _mock_jira(SEARCH_PAYLOAD)
    tickets = collect_jira("https://example.atlassian.net", "me@x.com", "tok",
                           "DEMO", WEEK_AGO)
    assert "alice@corp.com" not in tickets[0].model_dump_json()
