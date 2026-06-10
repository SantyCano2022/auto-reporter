from auto_reporter.analysis import build_digest
from auto_reporter.collectors.synthetic import synthetic_snapshot
from auto_reporter.narrate.renderer import build_prompt, narrate, render_fallback
from tests.factories import NOW

DIGEST = build_digest(synthetic_snapshot(seed=42, now=NOW),
                      stuck_days=3, silent_days=3, now=NOW)


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _valid_text() -> str:
    return f"Commits: {DIGEST.total_commits}."


def test_prompt_embeds_digest_and_strict_rules():
    prompt = build_prompt(DIGEST, "executive", "es")
    assert "ONLY numbers" in prompt
    assert str(DIGEST.total_commits) in prompt
    assert "Spanish" in prompt


def test_fallback_is_deterministic_and_lists_blockers():
    text = render_fallback(DIGEST, "technical", "es")
    assert text == render_fallback(DIGEST, "technical", "es")
    assert "DEMO-105" in text  # silent blocker listed
    assert "Bloqueos" in text


def test_narrate_without_llm_uses_fallback():
    report = narrate(DIGEST, "client", "en", llm=None)
    assert report.generator == "fallback"
    assert report.flagged is False


def test_narrate_happy_path_uses_llm():
    llm = FakeLLM([_valid_text()])
    report = narrate(DIGEST, "executive", "es", llm=llm)
    assert report.generator == "llm"
    assert report.flagged is False


def test_narrate_retries_once_then_falls_back_flagged():
    llm = FakeLLM(["we did 9999 commits", "still 8888 commits"])
    report = narrate(DIGEST, "executive", "es", llm=llm)
    assert len(llm.prompts) == 2
    assert "previous draft cited numbers" in llm.prompts[1]
    assert report.generator == "fallback"
    assert report.flagged is True


def test_fallback_renders_each_blocker_on_its_own_line():
    text = render_fallback(DIGEST, "technical", "es")
    blocker_lines = [line for line in text.splitlines() if line.startswith("- **")]
    assert len(blocker_lines) == len(DIGEST.blockers)


def test_fallback_pluralizes_commit_counts():
    text = render_fallback(DIGEST, "technical", "es")
    assert "(1 commit)" in text
    assert "(1 commits)" not in text
    assert "(2 commits)" in text
