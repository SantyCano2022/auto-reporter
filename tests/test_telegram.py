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
