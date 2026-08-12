"""Deterministic discovery and search for EtherCATAnalyzer C# source files."""

from dataclasses import dataclass
import json
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


def build_source_manifest(root: Path = PROJECT_ROOT) -> List[Dict[str, object]]:
    """Build a compact, stable manifest without including source text."""
    return [
        {
            "id": index,
            "relative_path": str(record.path.relative_to(root)).replace("\\", "/"),
            "classes": list(record.classes),
            "methods": list(record.methods),
        }
        for index, record in enumerate(discover_source_files(root), start=1)
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


_SEARCH_STOP_WORDS = {
    "about",
    "analyze",
    "analyse",
    "current",
    "explain",
    "flow",
    "from",
    "into",
    "with",
}


def _candidate_records(task: str, root: Path, max_candidates: int) -> List[SourceFileRecord]:
    """Use deterministic search to collect and rank candidates for an LLM prompt."""
    records = discover_source_files(root)
    records_by_path = {str(record.path): record for record in records}
    queries = [task.strip()]
    seen_queries = {task.strip().casefold()}
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", task):
        folded_token = token.casefold()
        if len(token) >= 3 and folded_token not in _SEARCH_STOP_WORDS:
            if folded_token not in seen_queries:
                queries.append(token)
                seen_queries.add(folded_token)

    candidate_scores: Dict[str, int] = {}
    for query in queries:
        for result in search_source(query, max_results=max_candidates, root=root):
            path = str(result["path"])
            record = records_by_path.get(path)
            if record is None:
                continue
            score, _, _ = _rank_record(record, query)
            candidate_scores[path] = candidate_scores.get(path, 0) + score

    ranked_paths = sorted(
        candidate_scores,
        key=lambda path: (-candidate_scores[path], path.casefold()),
    )
    return [records_by_path[path] for path in ranked_paths[:max_candidates]]


def _parse_selected_ids(content: str, valid_ids: set, max_files: int) -> List[int]:
    """Accept only a whitespace-separated list of valid numeric manifest IDs."""
    values = [line.strip() for line in content.splitlines() if line.strip()]
    if not values or any(not re.fullmatch(r"\d+", value) for value in values):
        return []

    selected_ids = []
    for value in values:
        identifier = int(value)
        if identifier not in valid_ids or identifier in selected_ids:
            continue
        selected_ids.append(identifier)
        if len(selected_ids) == max_files:
            break
    return selected_ids


def select_source_with_llm(task: str, max_files: int = 3, root: Path = PROJECT_ROOT) -> Dict[str, object]:
    """Ask Qwen to select complete C# files from a deterministic candidate manifest."""
    max_files = min(max_files, 3)
    if not task.strip() or max_files <= 0:
        return {"selected_paths": [], "source_texts": {}}

    records = discover_source_files(root)
    manifest = [
        {
            "id": index,
            "relative_path": str(record.path.relative_to(root)).replace("\\", "/"),
            "classes": list(record.classes),
            "methods": list(record.methods),
        }
        for index, record in enumerate(records, start=1)
    ]
    records_by_id = {entry["id"]: record for entry, record in zip(manifest, records)}
    candidates = _candidate_records(task, root, max(max_files * 3, 8))
    candidate_paths = {
        str(record.path.relative_to(root)).replace("\\", "/")
        for record in candidates
    }
    candidate_manifest = [
        entry
        for entry in manifest
        if entry["relative_path"] in candidate_paths
    ]
    if not candidate_manifest:
        return {"selected_paths": [], "source_texts": {}}

    from llm import llm

    prompt = (
        "Select up to {max_files} C# files relevant to this task.\n"
        "Return only numeric file ids, one id per line. Do not return any other text.\n\n"
        "Task:\n{task}\n\n"
        "Candidate source manifest:\n{manifest}"
    ).format(
        max_files=max_files,
        task=task.strip(),
        manifest=json.dumps(candidate_manifest, ensure_ascii=False, separators=(",", ":")),
    )
    response = llm.invoke(prompt)
    valid_ids = {int(entry["id"]) for entry in candidate_manifest}
    selected_ids = _parse_selected_ids(str(response.content), valid_ids, max_files)

    selected_paths = []
    source_texts = {}
    for identifier in selected_ids:
        record = records_by_id[identifier]
        path = str(record.path)
        selected_paths.append(path)
        source_texts[path] = record.text

    return {"selected_paths": selected_paths, "source_texts": source_texts}
