from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from typer.testing import CliRunner

from segretario.cli import app
from segretario.tools.web_tool import fetch_link


def test_fetch_link_saves_public_page_to_raw_articles(tmp_path: Path):
    vault = tmp_path / "vault"
    with local_page(
        """
        <html>
          <head><title>Local Research Note</title></head>
          <body>
            <h1>Local Research Note</h1>
            <p>Alpha beta from a local HTTP page.</p>
          </body>
        </html>
        """
    ) as url:
        result = fetch_link(vault, url)

    saved = vault / "raw" / "articles" / "local-research-note.md"
    assert result.path == "raw/articles/local-research-note.md"
    assert saved.exists()
    written = saved.read_text(encoding="utf-8")
    assert "source_url:" in written
    assert "fetched_at:" in written
    assert "title: Local Research Note" in written
    assert "# Local Research Note" in written
    assert "Alpha beta from a local HTTP page." in written


def test_fetch_link_strips_utf8_bom_before_title_extraction(tmp_path: Path):
    vault = tmp_path / "vault"
    with local_page(
        "\ufeff<html><body><h1>BOM Research Note</h1><p>Clean body.</p></body></html>"
    ) as url:
        result = fetch_link(vault, url)

    assert result.path == "raw/articles/bom-research-note.md"
    written = (vault / result.path).read_text(encoding="utf-8")
    assert "\\uFEFF" not in written
    assert "ï»¿" not in written
    assert "title: BOM Research Note" in written


def test_fetch_link_rejects_non_http_urls(tmp_path: Path):
    with pytest.raises(ValueError, match="http"):
        fetch_link(tmp_path / "vault", "file:///C:/Users/laste/private.md")


def test_link_cli_routes_through_core_and_writes_audit(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    with local_page("<html><body><h1>CLI Link Note</h1><p>Fetched by CLI.</p></body></html>") as url:
        result = CliRunner().invoke(app, ["link", url])

    assert result.exit_code == 0
    assert "raw/articles/cli-link-note.md" in result.output
    assert (vault / "raw" / "articles" / "cli-link-note.md").exists()
    assert (tmp_path / "state" / "taskboard.sqlite").exists()
    assert (tmp_path / "state" / "audit" / "events.jsonl").exists()


def test_link_cli_can_ingest_fetched_source(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    with local_page(
        "<html><body><h1>Ingested Link Note</h1><p>Ready for knowledge.</p></body></html>"
    ) as url:
        result = CliRunner().invoke(app, ["link", url, "--ingest"])

    assert result.exit_code == 0
    assert "saved: raw/articles/ingested-link-note.md" in result.output
    assert "created: knowledge/ingested-link-note.md" in result.output
    assert (vault / "knowledge" / "ingested-link-note.md").exists()


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: il_segretario
vault:
  path: "{vault.as_posix()}"
llm:
  provider: ollama
  model: "local-test-model"
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


@contextmanager
def local_page(body: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/article.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)
