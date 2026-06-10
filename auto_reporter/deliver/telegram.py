from __future__ import annotations

from dataclasses import dataclass

import httpx

from auto_reporter.http import request_with_retry

TELEGRAM_LIMIT = 4096


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(paragraph) > limit:
            chunks.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


@dataclass(frozen=True)
class TelegramNotifier:
    token: str

    def send(self, chat_id: str, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        with httpx.Client(timeout=30) as client:
            for chunk in split_message(text):
                try:
                    request_with_retry(client, "POST", url, json={
                        "chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"})
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 400:
                        raise
                    # LLM markdown that Telegram can't parse -> resend as plain text
                    request_with_retry(client, "POST", url,
                                       json={"chat_id": chat_id, "text": chunk})
