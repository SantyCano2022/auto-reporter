from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def load_last_run(path: Path) -> datetime | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return datetime.fromisoformat(data["last_successful_run"])


def save_state(path: Path, run_at: datetime) -> None:
    payload = json.dumps({"last_successful_run": run_at.isoformat()}, indent=2)
    path.write_text(payload + "\n", encoding="utf-8")
