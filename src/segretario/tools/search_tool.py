from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from segretario.vault.paths import classify_vault_path


@dataclass(frozen=True)
class SearchResult:
    path: str
    line: int
    snippet: str


def search_vault(
    vault_path: Path | str,
    query: str,
    *,
    include_self: bool = False,
    include_raw: bool = False,
) -> list[SearchResult]:
    vault = Path(vault_path)
    needle = query.casefold()
    results: list[SearchResult] = []

    if not needle:
        return results

    for file_path in sorted(vault.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() not in {".md", ".txt"}:
            continue
        if file_path.is_symlink():
            continue

        relative = _relative_vault_path(vault, file_path)
        if _should_skip(relative, include_self=include_self, include_raw=include_raw):
            continue

        for line_number, line in enumerate(_read_lines(file_path), start=1):
            snippet = line.strip()
            if needle in snippet.casefold():
                results.append(SearchResult(path=relative, line=line_number, snippet=snippet))

    return results


def _should_skip(relative: str, *, include_self: bool, include_raw: bool) -> bool:
    policy = classify_vault_path(relative)
    parts = relative.split("/")
    if policy.skip:
        return True
    if parts[:1] == ["self"] and not include_self:
        return True
    if parts[:1] == ["raw"] and not include_raw:
        return True
    return False


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _relative_vault_path(vault: Path, path: Path) -> str:
    return path.relative_to(vault).as_posix()
