from __future__ import annotations

from dataclasses import dataclass, field

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
    token: str = field(repr=False)  # never print the credential (HR2)

    def send(self, chat_id: str, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        with httpx.Client(timeout=30) as client:
            for chunk in split_message(text):
                try:
                    request_with_retry(client, "POST", url, json={
                        "chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"})
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 400:
                        raise self._redacted(exc) from None
                    # LLM markdown that Telegram can't parse -> resend as plain text
                    try:
                        request_with_retry(client, "POST", url,
                                           json={"chat_id": chat_id, "text": chunk})
                    except httpx.HTTPStatusError as exc2:
                        raise self._redacted(exc2) from None

    def _redacted(self, exc: httpx.HTTPStatusError) -> RuntimeError:
        # httpx embeds the full request URL (which contains the bot token) in its
        # error message; that must never reach (public) CI logs. `from None` above
        # also severs the chained original exception carrying the URL.
        return RuntimeError(str(exc).replace(self.token, "***"))
