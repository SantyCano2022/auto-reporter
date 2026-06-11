from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx

from auto_reporter.http import request_with_retry

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class GroqClient:
    api_key: str = field(repr=False)  # never print the credential (HR2)
    model: str

    def complete(self, prompt: str) -> str:
        with httpx.Client(timeout=60) as client:
            response = request_with_retry(
                client, "POST", GROQ_URL,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "temperature": 0.3,
                      "messages": [{"role": "user", "content": prompt}]},
            )
        return response.json()["choices"][0]["message"]["content"]
