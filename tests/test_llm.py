import httpx
import respx

from auto_reporter.narrate.llm import GROQ_URL, GroqClient


@respx.mock
def test_groq_client_sends_prompt_and_returns_content():
    route = respx.post(GROQ_URL).mock(return_value=httpx.Response(200, json={
        "choices": [{"message": {"content": "weekly report text"}}]
    }))
    client = GroqClient(api_key="groq-key", model="llama-3.3-70b-versatile")

    assert client.complete("narrate this") == "weekly report text"

    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer groq-key"
    assert b"narrate this" in request.content
