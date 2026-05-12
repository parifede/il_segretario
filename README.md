# il_segretario

Local-first CLI custodian for an Obsidian-compatible LLM Wiki vault.

## Bootstrap

```powershell
cd E:\il_segretario
uv sync
uv run segretario status
```

Copy `segretario.yaml.example` to `segretario.yaml` when you want a local config, then point the vault to the real Obsidian folder:

```yaml
vault:
  path: "E:\\YOUR_REAL_VAULT"
```

The default development vault path is `E:\il_segretario\vault_dev`. The real vault is always configurable and is not created inside the Python package.

## First Commands

```powershell
uv run segretario status
uv run segretario config show
uv run segretario vault check
uv run segretario search "topic"
uv run segretario lint wiki
uv run segretario stats
```

Basic ingest for Phase 1:

```powershell
uv run segretario ingest raw/articles/example.md --auto
```

## Safety Model

- Vault-private work uses local tools and local models.
- `self/` and `meta/privacy_map.local.json` are no-export paths.
- Gmail send/archive/delete and Calendar modify/delete require taskboard confirmation.
- Audit events are append-only JSONL records linked by a hash chain.
- Google credentials, OAuth tokens, local state, and private dev vault content are gitignored.
