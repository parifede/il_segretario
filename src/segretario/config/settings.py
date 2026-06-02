from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


class VaultSettings(BaseModel):
    path: Path = Field(default_factory=lambda: _root() / "vault_dev")
    require_agents_md: bool = True
    require_meta_index: bool = True
    require_meta_log: bool = True
    skip_paths: list[str] = Field(default_factory=lambda: ["raw/elaborati"])


class LLMSettings(BaseModel):
    provider: str = "ollama"
    sync_model: str = "local-model-name"
    async_model: str = "qwen3.5:latest"
    async_model_timeout_seconds: int = 300
    base_url: str = "http://127.0.0.1:11434"
    temperature: float = 0.2
    timeout_seconds: int = 120
    sync_model_keep_alive: int = -1  # -1 = always resident; coordinate with async model-swap in Phase 5
    sync_model_num_predict: int | None = None  # None = Ollama default; set ~300-400 to cap latency
    sync_model_num_ctx: int = 8192  # KV cache window; 8192 keeps model fully in GPU VRAM


class CLISettings(BaseModel):
    default_output: str = "text"
    require_confirmation_for_high_risk: bool = True


class TaskboardSettings(BaseModel):
    sqlite_path: Path = Field(default_factory=lambda: _root() / "state" / "taskboard.sqlite")
    human_mirror_path: Path = Field(default_factory=lambda: _root() / "state" / "bacheca.md")
    lease_minutes: int = 15
    max_retries: int = 3
    retry_cooldown_seconds: int = 60


class AuditSettings(BaseModel):
    events_path: Path = Field(default_factory=lambda: _root() / "state" / "audit" / "events.jsonl")
    hash_chain_path: Path = Field(default_factory=lambda: _root() / "state" / "audit" / "hash_chain.jsonl")
    redact_sensitive_payloads: bool = True


class WebSettings(BaseModel):
    enabled: bool = True
    save_dir: str = "raw/articles"
    user_link_auto_fetch: bool = True
    autonomous_research_enabled: bool = True
    require_projection_for_personal_context: bool = True


class GoogleSettings(BaseModel):
    enabled: bool = True
    credentials_path: Path = Field(default_factory=lambda: _root() / "secrets" / "google" / "credentials.json")
    token_path: Path = Field(default_factory=lambda: _root() / "secrets" / "google" / "token.json")
    gmail_enabled: bool = True
    calendar_enabled: bool = True


class SchedulerSettings(BaseModel):
    enabled: bool = False
    raw_watcher_enabled: bool = False
    inbox_watcher_enabled: bool = False
    daily_digest_enabled: bool = False
    maintenance_budget_minutes: int = 10
    max_tasks_per_cycle: int = 5
    cooldown_minutes_after_failure: int = 60
    no_user_notification_unless_useful: bool = True


class OcrSettings(BaseModel):
    tesseract_cmd: str | None = None


class CharacterSettings(BaseModel):
    identity: str = (
        "Sei Zarsuit, l'assistente personale di zarsOS. "
        "Sei preciso, discreto e orientato all'azione. "
        "Conosci il contesto dell'utente attraverso il Vault locale."
    )


class ZarsuitSettings(BaseModel):
    client: str = "stub"
    stub_response_file: str | None = None
    ux_timeout_seconds: float = 3.0


class BackupSettings(BaseModel):
    enabled: bool = False
    target_dir: Path = Field(
        default_factory=lambda: Path(r"E:\ZARSUIT_LOCAL_BACKUPS")
    )
    weekly_retention: int = 4
    monthly_retention: int = 12
    skip_paths: list[str] = Field(default_factory=lambda: ["raw/elaborati"])
    compression_level: int = 6
    weekly_threshold_days: int = 7
    monthly_threshold_days: int = 30
    state_path: Path | None = None


class HTTPServerSettings(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8722
    auth_token_env: str = "IL_SEGRETARIO_HTTP_TOKEN"


class RecallSettings(BaseModel):
    enabled: bool = False  # defensive default
    user_dismissed_wizard: bool = False
    embedding_model: str = "mxbai-embed-large"
    ollama_base_url: str = "http://127.0.0.1:11434"
    db_path: Path = Field(default_factory=lambda: _root() / "state" / "recall.sqlite")
    state_path: Path = Field(default_factory=lambda: _root() / "state" / "recall_last_run.json")
    default_k: int = 5
    reindex_threshold_minutes: int = 15
    skip_paths: list[str] = Field(default_factory=lambda: [
        "raw/elaborati",
        "raw/extracted",
        "README.md",
    ])
    embedder_health_check_timeout_seconds: int = 5
    embedder_max_chunk_chars: int = 1000  # hard cap per embedder token window (mxbai: 512 tok; 1000 chars ≈ 250 tok)
    # Grounding quality knobs — defaults are no-op (behaviour unchanged until tuned)
    grounding_top_k: int | None = None  # None → use default_k; set to cap chunks used for grounding
    grounding_min_score: float = 0.0    # 0.0 → no filter; set e.g. 0.4 to drop low-relevance chunks


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_name: str = "il_segretario"
    vault: VaultSettings = Field(default_factory=VaultSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    cli: CLISettings = Field(default_factory=CLISettings)
    taskboard: TaskboardSettings = Field(default_factory=TaskboardSettings)
    audit: AuditSettings = Field(default_factory=AuditSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    google: GoogleSettings = Field(default_factory=GoogleSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    character: CharacterSettings = Field(default_factory=CharacterSettings)
    zarsuit: ZarsuitSettings = Field(default_factory=ZarsuitSettings)
    backup: BackupSettings = Field(default_factory=BackupSettings)
    recall: RecallSettings = Field(default_factory=RecallSettings)
    http_server: HTTPServerSettings = Field(default_factory=HTTPServerSettings)
    loaded_config_path: Path | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
