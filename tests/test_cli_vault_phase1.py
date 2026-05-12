from pathlib import Path

from typer.testing import CliRunner

from segretario.cli import app


def test_vault_check_reports_missing_meta_files(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["vault", "check"])

    assert result.exit_code == 0
    assert "Vault check:" in result.output
    assert "meta/index.md: missing" in result.output
    assert "meta/log.md: missing" in result.output


def test_stats_prints_vault_counts(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "knowledge" / "Topic.md").write_text("# Topic\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["stats"])

    assert result.exit_code == 0
    assert "knowledge: 1" in result.output


def test_search_prints_matching_wiki_pages(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "knowledge" / "Topic.md").write_text("alpha beta\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["search", "alpha"])

    assert result.exit_code == 0
    assert "knowledge/Topic.md" in result.output


def test_search_cli_excludes_self_and_raw_elaborati(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    for folder in ("knowledge", "self", "raw/elaborati"):
        (vault / folder).mkdir(parents=True)
    (vault / "knowledge" / "Topic.md").write_text("alpha\n", encoding="utf-8")
    (vault / "self" / "profile.md").write_text("alpha secret\n", encoding="utf-8")
    (vault / "raw" / "elaborati" / "old.md").write_text("alpha old\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["search", "alpha"])

    assert result.exit_code == 0
    assert "knowledge/Topic.md" in result.output
    assert "self/profile.md" not in result.output
    assert "raw/elaborati/old.md" not in result.output


def test_lint_wiki_writes_report(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["lint", "wiki"])

    assert result.exit_code == 0
    assert "output/lint-" in result.output
    assert any((vault / "output").glob("lint-*.md"))


def test_ingest_creates_knowledge_page(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    source = vault / "raw" / "articles" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Source Topic\n\nAlpha beta topic.\n", encoding="utf-8")
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["ingest", "raw/articles/source.md", "--auto"])

    assert result.exit_code == 0
    assert "knowledge/source-topic.md" in result.output
    assert (vault / "knowledge" / "source-topic.md").exists()


def test_ingest_cli_rejects_parent_traversal(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    result = CliRunner().invoke(app, ["ingest", "../outside.md", "--auto"])

    assert result.exit_code != 0
    assert "parent traversal" in result.output


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: il_segretario
vault:
  path: "{vault.as_posix()}"
llm:
  base_url: "http://127.0.0.1:9"
taskboard:
  sqlite_path: "{(tmp_path / 'state' / 'taskboard.sqlite').as_posix()}"
audit:
  events_path: "{(tmp_path / 'state' / 'audit' / 'events.jsonl').as_posix()}"
  hash_chain_path: "{(tmp_path / 'state' / 'audit' / 'hash_chain.jsonl').as_posix()}"
google:
  credentials_path: "{(tmp_path / 'secrets' / 'google' / 'credentials.json').as_posix()}"
  token_path: "{(tmp_path / 'secrets' / 'google' / 'token.json').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config
