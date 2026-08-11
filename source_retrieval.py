"""Deterministic discovery and search for EtherCATAnalyzer C# source files."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, List, Sequence, Tuple

from config import PROJECT_ROOT


IGNORED_DIRECTORIES = {".git", "bin", "obj"}

_NAMESPACE_PATTERN = re.compile(
    r"^\s*namespace\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)",
    re.MULTILINE,
)
_CLASS_PATTERN = re.compile(r"\bclass\s+([A-Za-z_]\w*)")
_METHOD_PATTERN = re.compile(
    r"^\s*"
    r"(?:(?:public|private|protected|internal|static|virtual|override|abstract|"
    r"sealed|async|extern|unsafe|new|partial|ref|readonly)\s+)*"
    r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:\s*<[^>{};()]+>)?"
    r"(?:\s*\[\s*\])*\??\s+"
    r"([A-Za-z_]\w*)\s*(?:<[^>{};()]+>)?\s*\(",
)
_NON_METHOD_PREFIXES = (
    "if ",
    "else ",
    "for ",
    "foreach ",
    "while ",
    "switch ",
    "catch ",
    "using ",
    "return ",
    "throw ",
    "new ",
)


@dataclass(frozen=True)
class SourceFileRecord:
    path: Path
    namespaces: Tuple[str, ...]
    classes: Tuple[str, ...]
    methods: Tuple[str, ...]
    text: str


def _unique_in_order(values: Sequence[str]) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _extract_methods(text: str) -> Tuple[str, ...]:
    methods = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.casefold().startswith(_NON_METHOD_PREFIXES):
            continue
        match = _METHOD_PATTERN.match(line)
        if match:
            methods.append(match.group(1))
    return _unique_in_order(methods)


def parse_source_file(path: Path) -> SourceFileRecord:
    """Collect lightweight symbol metadata from one C# source file."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return SourceFileRecord(
        path=path,
        namespaces=_unique_in_order(_NAMESPACE_PATTERN.findall(text)),
        classes=_unique_in_order(_CLASS_PATTERN.findall(text)),
        methods=_extract_methods(text),
        text=text,
    )


def discover_source_files(root: Path = PROJECT_ROOT) -> List[SourceFileRecord]:
    """Recursively discover C# files, excluding generated/build directories."""
    paths = []
    for path in root.rglob("*.cs"):
        relative_parts = path.relative_to(root).parts[:-1]
        if any(part.casefold() in IGNORED_DIRECTORIES for part in relative_parts):
            continue
        paths.append(path)

    return [
        parse_source_file(path)
        for path in sorted(paths, key=lambda item: str(item).casefold())
    ]


def _rank_record(record: SourceFileRecord, query: str) -> Tuple[int, List[str], str]:
    folded_query = query.casefold()
    file_name = record.path.name.casefold()
    file_stem = record.path.stem.casefold()
    score = 0
    matched_symbols: List[str] = []
    reasons: List[str] = []

    if folded_query in (file_name, file_stem):
        score += 10_000
        reasons.append("exact filename")
    elif folded_query in file_name:
        score += 5_000
        reasons.append("filename contains query")

    symbol_groups = (
        ("class", record.classes, 9_000, 4_500),
        ("method", record.methods, 8_500, 4_250),
        ("namespace", record.namespaces, 8_000, 4_000),
    )
    for label, symbols, exact_score, partial_score in symbol_groups:
        for symbol in symbols:
            folded_symbol = symbol.casefold()
            if folded_query == folded_symbol:
                score += exact_score
                matched_symbols.append(symbol)
                reasons.append(f"exact {label} {symbol}")
            elif folded_query in folded_symbol:
                score += partial_score
                matched_symbols.append(symbol)
                reasons.append(f"{label} contains query")

    folded_text = record.text.casefold()
    occurrence_count = folded_text.count(folded_query)
    if occurrence_count:
        if re.fullmatch(r"[A-Za-z_]\w*", query) and re.search(
            rf"\b{re.escape(query)}\b", record.text, re.IGNORECASE
        ):
            score += 3_000
            if not matched_symbols:
                matched_symbols.append(query)
            reasons.append("exact source identifier")
        else:
            score += 1_000
            reasons.append("source text contains query")
        score += min(occurrence_count, 20)

    reason = "; ".join(_unique_in_order(reasons)[:3])
    return score, list(_unique_in_order(matched_symbols)), reason


def search_source(
    query: str,
    max_results: int = 8,
    root: Path = PROJECT_ROOT,
) -> List[Dict[str, object]]:
    """Return deterministically ranked, compact C# source search results."""
    query = query.strip()
    if not query or max_results <= 0:
        return []

    ranked = []
    for record in discover_source_files(root):
        score, matched_symbols, reason = _rank_record(record, query)
        if score:
            ranked.append((score, str(record.path).casefold(), record, matched_symbols, reason))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "path": str(record.path),
            "matched_symbols": matched_symbols,
            "reason": reason,
        }
        for _, _, record, matched_symbols, reason in ranked[:max_results]
    ]
