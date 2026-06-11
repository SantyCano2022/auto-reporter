from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from auto_reporter.analysis.stats import IN_PROGRESS_STATUSES
from auto_reporter.http import request_with_retry
from auto_reporter.models import Ticket, TicketTransition


def collect_jira(
    base_url: str, email: str, api_token: str, project_key: str, window_start: datetime
) -> list[Ticket]:
    with httpx.Client(auth=(email, api_token), timeout=30) as client:
        # Naive JQL datetimes are evaluated in the API user's profile timezone,
        # so the UTC window must be converted or it shifts by the UTC offset.
        profile = request_with_retry(client, "GET", f"{base_url}/rest/api/2/myself").json()
        local_start = window_start.astimezone(ZoneInfo(profile.get("timeZone") or "UTC"))
        jql = f'project = {project_key} AND updated >= "{local_start:%Y-%m-%d %H:%M}"'
        data = request_with_retry(
            client, "GET", f"{base_url}/rest/api/3/search/jql",
            params={"jql": jql, "fields": "summary,status,assignee",
                    "expand": "changelog", "maxResults": 100},
        ).json()

    tickets: list[Ticket] = []
    for issue in data["issues"]:
        fields = issue["fields"]
        status = fields["status"]["name"]
        # statusCategory.key is "new"/"indeterminate"/"done" regardless of the
        # site language; status names are localized ("En curso", "Listo"...).
        category = (fields["status"].get("statusCategory") or {}).get("key")
        assignee = (fields.get("assignee") or {}).get("displayName")  # HR2: no emails
        transitions = [
            TicketTransition(from_status=item["fromString"] or "",
                             to_status=item["toString"] or "",
                             at=_jira_dt(history["created"]))
            for history in issue.get("changelog", {}).get("histories", [])
            for item in history["items"]
            if item["field"] == "status"
        ]
        in_progress = (category == "indeterminate" if category is not None
                       else status.lower() in IN_PROGRESS_STATUSES)
        in_progress_since = None
        if in_progress:
            candidates = [t.at for t in transitions if t.to_status == status]
            in_progress_since = max(candidates) if candidates else None
        tickets.append(Ticket(
            key=issue["key"], summary=fields["summary"], status=status,
            status_category=category, assignee=assignee,
            url=f"{base_url}/browse/{issue['key']}",
            in_progress_since=in_progress_since, transitions=transitions,
        ))
    return tickets


def _jira_dt(value: str) -> datetime:
    # Jira format: 2026-06-01T08:00:00.000+0000 -> needs colon in offset for fromisoformat
    if value.endswith(("+0000", "-0000")) or (len(value) > 5 and value[-5] in "+-"):
        value = value[:-2] + ":" + value[-2:]
    return datetime.fromisoformat(value)
