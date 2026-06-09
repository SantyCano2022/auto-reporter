from __future__ import annotations

from datetime import datetime

import httpx

from auto_reporter.http import request_with_retry
from auto_reporter.models import Commit, PullRequest

API = "https://api.github.com"


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def collect_github(
    repo: str, token: str, window_start: datetime, window_end: datetime
) -> tuple[list[Commit], list[PullRequest]]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    with httpx.Client(headers=headers, timeout=30) as client:
        commits_raw = request_with_retry(
            client, "GET", f"{API}/repos/{repo}/commits",
            params={"since": window_start.isoformat(), "until": window_end.isoformat(),
                    "per_page": 100},
        ).json()
        prs_raw = request_with_retry(
            client, "GET", f"{API}/repos/{repo}/pulls",
            params={"state": "all", "sort": "updated", "direction": "desc", "per_page": 100},
        ).json()

    commits = [
        Commit(
            sha=c["sha"],
            message=c["commit"]["message"],
            author=(c.get("author") or {}).get("login") or c["commit"]["author"]["name"],
            url=c["html_url"],
            timestamp=_iso(c["commit"]["author"]["date"]),
        )
        for c in commits_raw
    ]

    prs: list[PullRequest] = []
    for p in prs_raw:
        if _iso(p["updated_at"]) < window_start:
            continue
        prs.append(PullRequest(
            number=p["number"], title=p["title"], author=p["user"]["login"],
            state="merged" if p.get("merged_at") else p["state"],
            head_branch=p["head"]["ref"], url=p["html_url"],
            created_at=_iso(p["created_at"]),
            merged_at=_iso(p["merged_at"]) if p.get("merged_at") else None,
        ))
    return commits, prs
