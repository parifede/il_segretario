from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from typer.testing import CliRunner

from segretario.cli import app


def test_web_cli_fetches_and_ingests_url_query_as_high_confidence_result(
    tmp_path: Path,
    monkeypatch,
):
    vault = tmp_path / "vault"
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    with local_page(
        "<html><body><h1>Section 15 Web Result</h1><p>Fetched through web query.</p></body></html>"
    ) as url:
        result = CliRunner().invoke(app, ["web", url])

    assert result.exit_code == 0
    assert f"web query: {url}" in result.output
    assert "saved: raw/articles/section-15-web-result.md" in result.output
    assert "created: knowledge/section-15-web-result.md" in result.output
    raw = vault / "raw" / "articles" / "section-15-web-result.md"
    knowledge = vault / "knowledge" / "section-15-web-result.md"
    assert raw.exists()
    assert knowledge.exists()
    raw_text = raw.read_text(encoding="utf-8")
    assert "source_url:" in raw_text
    assert "fetched_at:" in raw_text
    assert "Fetched through web query." in knowledge.read_text(encoding="utf-8")
    assert (tmp_path / "state" / "audit" / "events.jsonl").exists()


def test_web_cli_private_context_fetches_projected_url_without_raw_private_leak(
    tmp_path: Path,
    monkeypatch,
):
    vault = tmp_path / "vault"
    config = _write_config(tmp_path, vault)
    monkeypatch.setenv("SEGRETARIO_CONFIG", str(config))

    with local_page(
        "<html><body><h1>Projected Public Result</h1><p>Projection-safe body.</p></body></html>"
    ) as url:
        result = CliRunner().invoke(
            app,
            [
                "web",
                "Find services near Via Roma 12 for Mario Rossi",
                "--private-context",
                "--projection",
                url,
            ],
        )

    assert result.exit_code == 0
    assert f"web query: {url}" in result.output
    assert "Via Roma" not in result.output
    assert "Mario Rossi" not in result.output
    raw = vault / "raw" / "articles" / "projected-public-result.md"
    knowledge = vault / "knowledge" / "projected-public-result.md"
    assert raw.exists()
    assert knowledge.exists()
    combined = raw.read_text(encoding="utf-8") + knowledge.read_text(encoding="utf-8")
    assert "Via Roma" not in combined
    assert "Mario Rossi" not in combined


def _write_config(tmp_path: Path, vault: Path) -> Path:
    config = tmp_path / "segretario.yaml"
    config.write_text(
        f"""
project_name: section15_test
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
        yield f"http://127.0.0.1:{server.server_address[1]}/result.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)
