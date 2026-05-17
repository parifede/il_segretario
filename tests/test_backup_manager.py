from __future__ import annotations

import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from segretario.backup.manager import BackupKind, BackupManager
from segretario.config.settings import BackupSettings


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "knowledge").mkdir(parents=True)
    (vault / "knowledge" / "nota1.md").write_text("contenuto 1", encoding="utf-8")
    (vault / "knowledge" / "nota2.md").write_text("contenuto 2 con accenti àèìòù", encoding="utf-8")
    (vault / "self").mkdir()
    (vault / "self" / "privato.md").write_text("dati privati", encoding="utf-8")
    (vault / "raw" / "elaborati").mkdir(parents=True)
    (vault / "raw" / "elaborati" / "vecchio.md").write_text("da escludere", encoding="utf-8")
    (vault / "meta").mkdir()
    (vault / "meta" / "log.md").write_text("# Log\n", encoding="utf-8")
    return vault


def _settings(tmp_path: Path) -> BackupSettings:
    return BackupSettings(
        target_dir=tmp_path / "backups",
        weekly_retention=2,
        monthly_retention=3,
        skip_paths=["raw/elaborati"],
        state_path=tmp_path / "state" / "backup_last_run.json",
    )


def test_create_backup_produces_zip(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)
    result = manager.create(kind=BackupKind.MANUAL)
    assert result.ok is True
    assert result.path is not None
    assert result.path.exists()
    assert result.path.suffix == ".zip"


def test_backup_excludes_raw_elaborati(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)
    result = manager.create()
    with zipfile.ZipFile(result.path, "r") as zf:
        names = zf.namelist()
    assert not any("elaborati" in n for n in names)
    assert any("nota1.md" in n for n in names)
    assert any("privato.md" in n for n in names)


def test_backup_writes_sha256_sidecar(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)
    result = manager.create()
    sidecar = result.path.with_suffix(".zip.sha256")
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8").strip() == result.sha256


def test_backup_logs_to_vault_meta_log(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)
    manager.create(kind=BackupKind.WEEKLY)
    log = (vault / "meta" / "log.md").read_text(encoding="utf-8")
    assert "backup.weekly" in log


def test_list_backups_returns_metadata(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)
    manager.create(kind=BackupKind.MANUAL)
    items = manager.list_backups()
    assert len(items) == 1
    assert items[0]["kind"] == BackupKind.MANUAL
    assert items[0]["sha256"] is not None
    assert items[0]["size_bytes"] > 0


def test_retention_keeps_only_n_weekly(tmp_path):
    vault = _make_vault(tmp_path)
    settings = _settings(tmp_path)  # weekly_retention=2
    manager = BackupManager(settings, vault)
    for _ in range(4):
        # Reset state to simulate 8 days between runs so the guard never blocks
        manager._state.set_last_run("weekly", datetime.now(timezone.utc) - timedelta(days=8))
        manager.create(kind=BackupKind.WEEKLY)
        time.sleep(1.1)
    archives = list(settings.target_dir.glob("il_segretario_vault_weekly_*.zip"))
    assert len(archives) == 2


def test_retention_does_not_touch_manual(tmp_path):
    vault = _make_vault(tmp_path)
    settings = _settings(tmp_path)
    manager = BackupManager(settings, vault)
    for _ in range(5):
        manager.create(kind=BackupKind.MANUAL)
        time.sleep(1.1)
    archives = list(settings.target_dir.glob("il_segretario_vault_manual_*.zip"))
    assert len(archives) == 5


def test_restore_dry_run_validates_sha256(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)
    result = manager.create()
    restore_result = manager.restore(result.path.name, dry_run=True)
    assert restore_result.ok is True


def test_restore_detects_corrupted_archive(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)
    result = manager.create()
    with result.path.open("ab") as f:
        f.write(b"corruption")
    restore_result = manager.restore(result.path.name, dry_run=True)
    assert restore_result.ok is False
    assert "sha256 mismatch" in restore_result.message


def test_restore_real_recreates_files(tmp_path):
    import shutil

    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)
    result = manager.create()
    shutil.rmtree(vault)
    vault.mkdir()
    restore_result = manager.restore(result.path.name, dry_run=False)
    assert restore_result.ok is True
    assert (vault / "knowledge" / "nota1.md").exists()
    assert (vault / "self" / "privato.md").exists()
    assert "àèìòù" in (vault / "knowledge" / "nota2.md").read_text(encoding="utf-8")


def test_weekly_skips_if_last_run_too_recent(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)

    result1 = manager.create(kind=BackupKind.WEEKLY)
    assert result1.ok
    assert result1.path is not None

    result2 = manager.create(kind=BackupKind.WEEKLY)
    assert result2.ok
    assert result2.path is None
    assert "skipped" in result2.message.lower()


def test_monthly_skips_if_last_run_too_recent(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)

    result1 = manager.create(kind=BackupKind.MONTHLY)
    assert result1.ok
    assert result1.path is not None

    result2 = manager.create(kind=BackupKind.MONTHLY)
    assert result2.ok
    assert result2.path is None
    assert "skipped" in result2.message.lower()


def test_manual_ignores_last_run(tmp_path):
    vault = _make_vault(tmp_path)
    manager = BackupManager(_settings(tmp_path), vault)

    for _ in range(3):
        result = manager.create(kind=BackupKind.MANUAL)
        assert result.ok
        assert result.path is not None
        time.sleep(1.1)


def test_state_file_persisted_across_runs(tmp_path):
    vault = _make_vault(tmp_path)
    settings = _settings(tmp_path)

    manager1 = BackupManager(settings, vault)
    result1 = manager1.create(kind=BackupKind.WEEKLY)
    assert result1.ok
    assert result1.path is not None

    manager2 = BackupManager(settings, vault)
    result2 = manager2.create(kind=BackupKind.WEEKLY)
    assert result2.path is None
    assert "skipped" in result2.message.lower()


def test_state_file_corrupted_logs_warning_and_proceeds(tmp_path, caplog):
    import logging

    vault = _make_vault(tmp_path)
    settings = _settings(tmp_path)
    manager = BackupManager(settings, vault)

    state_path = manager._state._path
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{ corrupted json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        result = manager.create(kind=BackupKind.WEEKLY)

    assert result.ok
    assert result.path is not None
    assert any("unreadable" in rec.message for rec in caplog.records)


def test_threshold_boundary(tmp_path):
    vault = _make_vault(tmp_path)
    settings = _settings(tmp_path)
    manager = BackupManager(settings, vault)

    eight_days_ago = datetime.now(timezone.utc) - timedelta(days=8)
    manager._state.set_last_run("weekly", eight_days_ago)

    result = manager.create(kind=BackupKind.WEEKLY)
    assert result.ok
    assert result.path is not None  # 8 days > 7 — not skipped

    six_days_ago = datetime.now(timezone.utc) - timedelta(days=6)
    manager._state.set_last_run("weekly", six_days_ago)

    result = manager.create(kind=BackupKind.WEEKLY)
    assert result.path is None  # 6 < 7 — skipped


def test_custom_threshold_from_settings(tmp_path):
    vault = _make_vault(tmp_path)
    settings = _settings(tmp_path).model_copy(update={
        "weekly_threshold_days": 1,
        "monthly_threshold_days": 2,
    })
    manager = BackupManager(settings, vault)

    half_day_ago = datetime.now(timezone.utc) - timedelta(hours=12)
    manager._state.set_last_run("weekly", half_day_ago)
    result = manager.create(kind=BackupKind.WEEKLY)
    assert result.path is None  # 0.5 days < 1 — skipped
