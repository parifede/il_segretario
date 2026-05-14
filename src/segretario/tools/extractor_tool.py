from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import zlib

import yaml

from segretario.vault.index_log import append_log
from segretario.vault.paths import classify_vault_path, matches_configured_skip_path
from segretario.vault.repair import _processed_raw_sources


@dataclass(frozen=True)
class ExtractPlanReport:
    path: str
    items: list[str]


class ExtractorTool:
    """Plan safe local extraction work for rich raw sources."""

    def plan(
        self,
        vault_path: Path | str,
        *,
        today: date | None = None,
        skip_paths: list[str] | tuple[str, ...] | None = None,
    ) -> ExtractPlanReport:
        return plan_extraction(vault_path, today=today, skip_paths=skip_paths)

    def extract_pdf(
        self,
        vault_path: Path | str,
        source_path: Path | str,
        *,
        skip_paths: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, str]:
        return extract_pdf(vault_path, source_path, skip_paths=skip_paths)


def plan_extraction(
    vault_path: Path | str,
    *,
    today: date | None = None,
    skip_paths: list[str] | tuple[str, ...] | None = None,
) -> ExtractPlanReport:
    vault = Path(vault_path)
    report_date = today or date.today()
    items = _extract_plan_items(vault, skip_paths=skip_paths)
    relative_report = f"output/extract-plan-{report_date.isoformat()}.md"
    report_path = vault / relative_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# Extract Plan {report_date.isoformat()}", ""]
    if items:
        lines.extend(items)
    else:
        lines.append("- no extraction planning needed")
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return ExtractPlanReport(path=relative_report, items=items)


def _extract_plan_items(
    vault: Path,
    *,
    skip_paths: list[str] | tuple[str, ...] | None,
) -> list[str]:
    raw_dir = vault / "raw"
    if not raw_dir.exists():
        return []
    processed = _processed_raw_sources(vault)
    items: list[str] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        relative = path.relative_to(vault).as_posix()
        if classify_vault_path(relative).skip or matches_configured_skip_path(relative, skip_paths):
            continue
        if relative in processed:
            continue
        proposal = _extract_plan_decision(relative)
        if proposal is None:
            continue
        kind, reason = proposal
        items.append(f"- {relative} -> {kind}: {reason}")
    return items


def _extract_plan_decision(relative: str) -> tuple[str, str] | None:
    suffix = Path(relative).suffix.casefold()
    if suffix in {".md", ".txt"}:
        return None
    if suffix == ".pdf":
        return ("extract_candidate", "pdf text extraction candidate")
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}:
        return ("extract_candidate", "image OCR or metadata extraction candidate")
    if suffix in {".xlsx", ".xls", ".ods", ".csv", ".tsv"}:
        return ("extract_candidate", "spreadsheet/table extraction candidate")
    if suffix in {".pptx", ".ppt", ".odp"}:
        return ("extract_candidate", "presentation text extraction candidate")
    if suffix in {".docx", ".doc", ".odt", ".rtf"}:
        return ("extract_candidate", "document text extraction candidate")
    if suffix in {".patch", ".diff"}:
        return ("extract_candidate", "patch text extraction candidate")
    if suffix in {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"}:
        return ("review_before_extract", "archive/bundle requires explicit expansion policy")
    if suffix:
        return ("leave_in_raw", f"unsupported {suffix.removeprefix('.')} source")
    return ("leave_in_raw", "unsupported source")


def extract_pdf(
    vault_path: Path | str,
    source_path: Path | str,
    *,
    skip_paths: list[str] | tuple[str, ...] | None = None,
) -> dict[str, str]:
    vault = Path(vault_path)
    relative_source = _normalize_pdf_source(source_path, skip_paths=skip_paths)
    source = vault / relative_source
    _require_inside(vault, source)
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_symlink():
        raise ValueError("extract source cannot be a symlink")
    if source.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("pdf source exceeds extraction size limit")

    text = _extract_text_from_pdf_bytes(source.read_bytes())
    if not text.strip():
        raise ValueError("pdf text extraction produced no text")

    slug = _slugify(source.stem)
    target_relative = f"raw/extracted/{slug}.md"
    target = vault / target_relative
    _require_inside(vault / "raw" / "extracted", target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("extract target cannot be a symlink")
    title = source.stem.replace("_", " ").replace("-", " ").strip() or "Extracted PDF"
    frontmatter = {
        "title": title,
        "source_path": relative_source,
        "extracted_from": "pdf",
        "status": "extracted",
        "privacy": "private",
        "cloud_ok": False,
        "updated": date.today().isoformat(),
    }
    target.write_text(_render_extracted_markdown(frontmatter, title, text), encoding="utf-8")
    append_log(vault, f"- {date.today().isoformat()} extract {relative_source} -> {target_relative}")
    return {"path": target_relative, "source_path": relative_source}


def _normalize_pdf_source(
    source_path: Path | str,
    *,
    skip_paths: list[str] | tuple[str, ...] | None = None,
) -> str:
    relative = Path(source_path).as_posix().strip("/")
    parts = tuple(Path(relative).parts)
    if ".." in parts:
        raise ValueError("source path cannot contain parent traversal")
    if Path(source_path).is_absolute():
        raise ValueError("source path must be vault-relative")
    if (
        parts[:1] != ("raw",)
        or classify_vault_path(relative).skip
        or matches_configured_skip_path(relative, skip_paths)
    ):
        raise ValueError("extract source must be under raw and outside skipped paths")
    if Path(relative).suffix.casefold() != ".pdf":
        raise ValueError("extract source must be a pdf")
    return relative


def _require_inside(root: Path, candidate: Path) -> None:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise ValueError("path escapes allowed vault boundary")


def _extract_text_from_pdf_bytes(data: bytes) -> str:
    chunks: list[str] = []
    for stream in _pdf_streams(data):
        chunks.append(_decode_pdf_strings(stream))
    lines = []
    seen: set[str] = set()
    for chunk in chunks:
        for line in chunk.splitlines():
            cleaned = re.sub(r"\s+", " ", line).strip()
            if cleaned and cleaned not in seen:
                lines.append(cleaned)
                seen.add(cleaned)
    text = "\n".join(lines)
    if len(text) > 1_000_000:
        raise ValueError("pdf extracted text exceeds size limit")
    return text


def _pdf_streams(data: bytes) -> list[bytes]:
    streams: list[bytes] = []
    start = 0
    while True:
        stream_index = data.find(b"stream", start)
        if stream_index < 0:
            break
        body_start = stream_index + len(b"stream")
        if data[body_start : body_start + 2] == b"\r\n":
            body_start += 2
        elif data[body_start : body_start + 1] in {b"\n", b"\r"}:
            body_start += 1
        end_index = data.find(b"endstream", body_start)
        if end_index < 0:
            break
        header_start = max(0, stream_index - 4096)
        header = data[header_start:stream_index]
        body = data[body_start:end_index].strip(b"\r\n")
        start = end_index + len(b"endstream")
        if len(body) > 5 * 1024 * 1024:
            continue
        if b"/FlateDecode" in header:
            try:
                body = zlib.decompress(body)
            except zlib.error:
                continue
        if len(body) > 5 * 1024 * 1024:
            continue
        streams.append(body)
    return streams


def _decode_pdf_strings(data: bytes) -> str:
    text: list[str] = []
    for operator in _operator_positions(data, b"Tj"):
        operand = _operand_window(data, operator)
        literal = _last_literal_operand(operand)
        if literal is not None:
            text.append(_decode_pdf_literal(literal))
            continue
        hex_text = _last_hex_operand(operand)
        if hex_text is not None:
            text.append(_decode_pdf_hex(hex_text))
    for operator in _operator_positions(data, b"TJ"):
        operand = _operand_window(data, operator)
        array = _last_array_operand(operand)
        if array is None:
            continue
        for kind, value in _array_text_operands(array):
            text.append(_decode_pdf_literal(value) if kind == "literal" else _decode_pdf_hex(value))
    return "\n".join(part for part in text if part.strip())


def _operator_positions(data: bytes, operator: bytes):
    start = 0
    while True:
        index = data.find(operator, start)
        if index < 0:
            return
        before = data[index - 1 : index] if index else b" "
        after = data[index + len(operator) : index + len(operator) + 1]
        if _is_pdf_boundary(before) and _is_pdf_boundary(after):
            yield index
        start = index + len(operator)


def _is_pdf_boundary(value: bytes) -> bool:
    return not value or value in b"\x00\t\n\f\r []<>()/"


def _operand_window(data: bytes, operator_index: int) -> bytes:
    return data[max(0, operator_index - 8192) : operator_index]


def _last_literal_operand(data: bytes) -> bytes | None:
    end = _find_last_unescaped(data, ord(")"))
    if end is None:
        return None
    start = _matching_literal_start(data, end)
    if start is None:
        return None
    return data[start + 1 : end]


def _find_last_unescaped(data: bytes, char: int) -> int | None:
    index = len(data) - 1
    while index >= 0:
        if data[index] == char and _backslash_count(data, index) % 2 == 0:
            return index
        index -= 1
    return None


def _backslash_count(data: bytes, index: int) -> int:
    count = 0
    index -= 1
    while index >= 0 and data[index] == 92:
        count += 1
        index -= 1
    return count


def _matching_literal_start(data: bytes, end: int) -> int | None:
    depth = 0
    index = end
    while index >= 0:
        char = data[index]
        if _backslash_count(data, index) % 2:
            index -= 1
            continue
        if char == ord(")"):
            depth += 1
        elif char == ord("("):
            depth -= 1
            if depth == 0:
                return index
        index -= 1
    return None


def _last_hex_operand(data: bytes) -> bytes | None:
    end = data.rfind(b">")
    if end < 0:
        return None
    start = data.rfind(b"<", 0, end)
    if start < 0 or data[start : start + 2] == b"<<":
        return None
    candidate = data[start + 1 : end]
    return candidate if re.fullmatch(rb"[0-9A-Fa-f\s]+", candidate) else None


def _last_array_operand(data: bytes) -> bytes | None:
    end = data.rfind(b"]")
    if end < 0:
        return None
    start = data.rfind(b"[", 0, end)
    if start < 0:
        return None
    return data[start + 1 : end]


def _array_text_operands(array: bytes) -> list[tuple[str, bytes]]:
    operands: list[tuple[str, bytes]] = []
    index = 0
    while index < len(array):
        char = array[index]
        if char == ord("("):
            end = _literal_end(array, index)
            if end is None:
                break
            operands.append(("literal", array[index + 1 : end]))
            index = end + 1
            continue
        if char == ord("<") and array[index : index + 2] != b"<<":
            end = array.find(b">", index + 1)
            if end < 0:
                break
            candidate = array[index + 1 : end]
            if re.fullmatch(rb"[0-9A-Fa-f\s]+", candidate):
                operands.append(("hex", candidate))
            index = end + 1
            continue
        index += 1
    return operands


def _literal_end(data: bytes, start: int) -> int | None:
    depth = 1
    index = start + 1
    while index < len(data):
        char = data[index]
        if _backslash_count(data, index) % 2:
            index += 1
            continue
        if char == ord("("):
            depth += 1
        elif char == ord(")"):
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _decode_pdf_literal(raw: bytes) -> str:
    output = bytearray()
    index = 0
    escapes = {
        ord("n"): ord("\n"),
        ord("r"): ord("\r"),
        ord("t"): ord("\t"),
        ord("b"): ord("\b"),
        ord("f"): ord("\f"),
        ord("("): ord("("),
        ord(")"): ord(")"),
        ord("\\"): ord("\\"),
    }
    while index < len(raw):
        char = raw[index]
        if char != 92:
            output.append(char)
            index += 1
            continue
        index += 1
        if index >= len(raw):
            break
        escaped = raw[index]
        if 48 <= escaped <= 55:
            digits = bytes([escaped])
            index += 1
            for _ in range(2):
                if index < len(raw) and 48 <= raw[index] <= 55:
                    digits += bytes([raw[index]])
                    index += 1
            output.append(int(digits, 8))
            continue
        output.append(escapes.get(escaped, escaped))
        index += 1
    return output.decode("utf-8", errors="replace")


def _decode_pdf_hex(raw: bytes) -> str:
    cleaned = re.sub(rb"\s+", b"", raw)
    if len(cleaned) % 2:
        cleaned += b"0"
    data = bytes.fromhex(cleaned.decode("ascii"))
    if data.startswith((b"\xfe\xff", b"\xff\xfe")):
        return data.decode("utf-16", errors="replace")
    if b"\x00" in data:
        return data.decode("utf-16-be", errors="replace")
    return data.decode("utf-8", errors="replace")


def _render_extracted_markdown(frontmatter: dict[str, object], title: str, text: str) -> str:
    metadata = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False)
    return f"---\n{metadata}---\n\n# {title}\n\n{text.strip()}\n"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "extracted-pdf"
