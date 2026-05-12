from pathlib import Path

from segretario.app.query import query_vault


class FakeLLM:
    def __init__(self, answer: str = "Synthesized answer") -> None:
        self.answer = answer
        self.calls: list[dict[str, str | None]] = []

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        return self.answer


def test_query_refuses_when_no_relevant_pages(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    llm = FakeLLM()

    result = query_vault(vault, "alpha", llm=llm)

    assert "No relevant vault pages found" in result.answer
    assert result.sources == []
    assert llm.calls == []


def test_query_sends_only_allowed_vault_context(tmp_path: Path):
    vault = tmp_path / "vault"
    for folder in ("knowledge", "self", "raw/elaborati"):
        (vault / folder).mkdir(parents=True)
    (vault / "knowledge" / "Topic.md").write_text("# Topic\n\nalpha public\n", encoding="utf-8")
    (vault / "self" / "profile.md").write_text("alpha secret\n", encoding="utf-8")
    (vault / "raw" / "elaborati" / "old.md").write_text("alpha old\n", encoding="utf-8")
    llm = FakeLLM("Answer about alpha")

    result = query_vault(vault, "alpha", llm=llm)

    assert result.sources == ["[[Topic]]"]
    assert "[[Topic]]" in result.answer
    prompt = llm.calls[0]["prompt"]
    assert "alpha public" in prompt
    assert "alpha secret" not in prompt
    assert "alpha old" not in prompt


def test_query_uses_frontmatter_title_for_citation(tmp_path: Path):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "knowledge" / "topic.md").write_text(
        "---\ntitle: Better Title\n---\n# Topic\n\nalpha\n",
        encoding="utf-8",
    )
    llm = FakeLLM("Answer")

    result = query_vault(vault, "alpha", llm=llm)

    assert result.sources == ["[[Better Title]]"]
    assert result.answer.endswith("Sources: [[Better Title]]")
