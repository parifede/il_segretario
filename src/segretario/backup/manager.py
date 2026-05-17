from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from segretario.config.settings import BackupSettings


class BackupKind:
    MANUAL = "manual"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class BackupResult:
    def __init__(
        self,
        *,
        ok: bool,
        path: Path | None,
        size_bytes: int,
        sha256: str | None,
        message: str,
    ) -> None:
        self.ok = ok
        self.path = path
        self.size_bytes = size_bytes
        self.sha256 = sha256
        self.message = message


class BackupManager:
    """Gestisce backup, retention e restore del vault."""

    def __init__(self, settings: BackupSettings, vault_path: Path) -> None:
        self._settings = settings
        self._vault = vault_path

    def create(self, kind: str = BackupKind.MANUAL) -> BackupResult:
        if not self._vault.exists():
            return BackupResult(
                ok=False, path=None, size_bytes=0, sha256=None,
                message=f"vault path does not exist: {self._vault}",
            )

        self._settings.target_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        archive_name = f"il_segretario_vault_{kind}_{timestamp}.zip"
        archive_path = self._settings.target_dir / archive_name
        tmp_path = archive_path.with_suffix(".zip.tmp")

        skip_resolved = [
            (self._vault / p).resolve() for p in self._settings.skip_paths
        ]

        try:
            with zipfile.ZipFile(
                tmp_path, "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=self._settings.compression_level,
            ) as zf:
                for source in self._vault.rglob("*"):
                    if not source.is_file():
                        continue
                    try:
                        resolved = source.resolve()
                    except OSError:
                        continue
                    if any(
                        skip in resolved.parents or skip == resolved
                        for skip in skip_resolved
                    ):
                        continue
                    arcname = source.relative_to(self._vault)
                    zf.write(source, arcname=str(arcname))

            tmp_path.replace(archive_path)

            sha256_hex = self._sha256_file(archive_path)
            (archive_path.with_suffix(".zip.sha256")).write_text(
                sha256_hex, encoding="utf-8"
            )

            size = archive_path.stat().st_size
            self._apply_retention(kind)
            self._log_to_vault(kind, archive_path, size, sha256_hex)

            return BackupResult(
                ok=True, path=archive_path, size_bytes=size,
                sha256=sha256_hex, message=f"backup created: {archive_name}",
            )
        except Exception as e:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return BackupResult(
                ok=False, path=None, size_bytes=0, sha256=None,
                message=f"backup failed: {type(e).__name__}: {e}",
            )

    def list_backups(self) -> list[dict]:
        if not self._settings.target_dir.exists():
            return []
        items = []
        for archive in sorted(self._settings.target_dir.glob("il_segretario_vault_*.zip")):
            sha256_file = archive.with_suffix(".zip.sha256")
            sha256_hex = sha256_file.read_text(encoding="utf-8").strip() if sha256_file.exists() else None
            kind = self._extract_kind_from_name(archive.name)
            items.append({
                "name": archive.name,
                "path": str(archive),
                "kind": kind,
                "size_bytes": archive.stat().st_size,
                "mtime": datetime.fromtimestamp(
                    archive.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                "sha256": sha256_hex,
            })
        return items

    def restore(self, backup_name: str, dry_run: bool = False) -> BackupResult:
        archive_path = self._settings.target_dir / backup_name
        if not archive_path.exists():
            return BackupResult(
                ok=False, path=None, size_bytes=0, sha256=None,
                message=f"backup not found: {backup_name}",
            )

        sha256_file = archive_path.with_suffix(".zip.sha256")
        if sha256_file.exists():
            expected = sha256_file.read_text(encoding="utf-8").strip()
            actual = self._sha256_file(archive_path)
            if expected != actual:
                return BackupResult(
                    ok=False, path=archive_path, size_bytes=0, sha256=actual,
                    message=f"sha256 mismatch: expected {expected[:16]}..., got {actual[:16]}...",
                )

        if dry_run:
            return BackupResult(
                ok=True, path=archive_path, size_bytes=archive_path.stat().st_size,
                sha256=None, message=f"dry run ok, backup valid: {backup_name}",
            )

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(self._vault)
            return BackupResult(
                ok=True, path=archive_path, size_bytes=archive_path.stat().st_size,
                sha256=None,
                message=f"restored from {backup_name} into {self._vault}",
            )
        except Exception as e:
            return BackupResult(
                ok=False, path=archive_path, size_bytes=0, sha256=None,
                message=f"restore failed: {type(e).__name__}: {e}",
            )

    def _apply_retention(self, kind: str) -> None:
        if kind == BackupKind.WEEKLY:
            keep = self._settings.weekly_retention
        elif kind == BackupKind.MONTHLY:
            keep = self._settings.monthly_retention
        else:
            return  # MANUAL: no retention

        prefix = f"il_segretario_vault_{kind}_"
        archives = sorted(
            self._settings.target_dir.glob(f"{prefix}*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in archives[keep:]:
            sidecar = old.with_suffix(".zip.sha256")
            try:
                old.unlink()
            except OSError:
                pass
            if sidecar.exists():
                try:
                    sidecar.unlink()
                except OSError:
                    pass

    def _sha256_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _extract_kind_from_name(name: str) -> str:
        # il_segretario_vault_<kind>_<timestamp>.zip
        parts = name.split("_")
        if len(parts) >= 4:
            return parts[3]
        return "unknown"

    def _log_to_vault(self, kind: str, archive_path: Path, size: int, sha256_hex: str) -> None:
        log_file = self._vault / "meta" / "log.md"
        if not log_file.parent.exists():
            return
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        size_mb = size / (1024 * 1024)
        line = (
            f"- {timestamp} backup.{kind}: "
            f"{archive_path.name} ({size_mb:.1f} MB) sha256={sha256_hex[:16]}\n"
        )
        try:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass
