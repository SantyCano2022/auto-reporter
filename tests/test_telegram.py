import httpx
import respx

from auto_reporter.deliver.telegram import TelegramNotifier, split_message

API = "https://api.telegram.org/botTOKEN/sendMessage"


def test_split_short_message_is_single_chunk():
    assert split_message("hola") == ["hola"]


def test_split_prefers_paragraph_boundaries():
    text = "a" * 3000 + "\n\n" + "b" * 3000
    chunks = split_message(text, limit=4096)
    assert chunks == ["a" * 3000, "b" * 3000]


def test_split_hard_splits_oversized_paragraph():
    text = "x" * 9000
    chunks = split_message(text, limit=4096)
    assert [len(c) for c in chunks] == [4096, 4096, 808]


@respx.mock
def test_send_posts_each_chunk():
    route = respx.post(API).mock(return_value=httpx.Response(200, json={"ok": True}))
    notifier = TelegramNotifier(token="TOKEN")
    notifier.send("123", "a" * 3000 + "\n\n" + "b" * 3000)
    assert route.call_count == 2


@respx.mock
def test_send_retries_without_markdown_on_400():
    route = respx.post(API).mock(side_effect=[
        httpx.Response(400, json={"ok": False, "description": "can't parse entities"}),
        httpx.Response(200, json={"ok": True}),
    ])
    TelegramNotifier(token="TOKEN").send("123", "broken _markdown")
    assert route.call_count == 2
    import json
    assert "parse_mode" not in json.loads(route.calls[1].request.content)


@respx.mock
def test_send_error_never_leaks_the_token():
    """httpx error messages embed the request URL, which contains the bot token.

    A Telegram outage must not print the token into (public) CI logs.
    """
    respx.post(API).mock(return_value=httpx.Response(403, json={"ok": False}))
    notifier = TelegramNotifier(token="TOKEN")
    try:
        notifier.send("123", "hola")
        raised = None
    except Exception as exc:  # noqa: BLE001 — we inspect whatever propagates
        raised = exc
    assert raised is not None
    assert "TOKEN" not in str(raised)
    assert "TOKEN" not in repr(raised)
    # the chained original (whose message embeds the URL) must not be displayed
    assert raised.__cause__ is None and raised.__suppress_context__


@respx.mock
def test_send_5xx_after_retries_raises_redacted_token(monkeypatch):
    """A 5xx is retried by request_with_retry, so it reaches the redaction path
    differently than a 4xx: only after attempts are exhausted. The token must
    still be scrubbed from whatever propagates into (public) CI logs."""
    monkeypatch.setattr("auto_reporter.http.time.sleep", lambda _: None)
    route = respx.post(API).mock(return_value=httpx.Response(503, json={"ok": False}))
    notifier = TelegramNotifier(token="TOKEN")
    try:
        notifier.send("123", "hola")
        raised = None
    except Exception as exc:  # noqa: BLE001 — we inspect whatever propagates
        raised = exc
    assert raised is not None
    assert route.call_count == 3  # retried to exhaustion, not a single shot
    assert "TOKEN" not in str(raised)
    assert "TOKEN" not in repr(raised)
    assert raised.__cause__ is None and raised.__suppress_context__
