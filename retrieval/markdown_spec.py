"""Deterministic heading-aware retrieval from generated ET1100 Markdown."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.config import SPEC_GENERATED_ROOT


SPEC_MARKDOWN_PATH = SPEC_GENERATED_ROOT / "ET1100" / "ET1100.md"
SPEC_SOURCE_RELATIVE_PATH = "spec/generated/ET1100/ET1100.md"
DEFAULT_SEARCH_LIMIT = 5
MAX_SEARCH_LIMIT = 10
MAX_CHUNK_CHARS = 12000

_HEADING_PATTERN = re.compile(r"^(#{1,4})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_TOKEN_PATTERN = re.compile(r"0x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9-]*")
_STOP_WORDS = {
    "about",
    "and",
    "for",
    "from",
    "how",
    "into",
    "is",
    "of",
    "on",
    "the",
    "to",
    "with",
}
_FRONT_MATTER_MARKERS = (
    "document history",
    "contents",
    "tables",
    "figures",
    "abbreviations",
)


def _validate_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    return query.strip()


def _validate_limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {MAX_SEARCH_LIMIT}")
    return limit


def _load_markdown(markdown_path: Path) -> str:
    if not markdown_path.is_file():
        raise FileNotFoundError(
            f"{SPEC_SOURCE_RELATIVE_PATH} is missing; "
            "run /ingest-spec ET1100 first"
        )
    return markdown_path.read_text(encoding="utf-8")


def _parse_sections(markdown: str) -> List[Dict[str, object]]:
    sections: List[Dict[str, object]] = []
    current: Optional[Dict[str, object]] = None
    heading_stack: List[Tuple[int, str, List[str]]] = []

    for line in markdown.splitlines():
        heading_match = _HEADING_PATTERN.match(line)
        if heading_match:
            if current is not None:
                sections.append(current)

            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_path = [item[1] for item in heading_stack] + [heading]
            current = {
                "heading": heading,
                "heading_path": heading_path,
                "level": level,
                "lines": [],
            }
            heading_stack.append((level, heading, heading_path))
        else:
            if current is None:
                current = {
                    "heading": "",
                    "heading_path": [],
                    "level": 0,
                    "lines": [],
                }
            current["lines"].append(line)

    if current is not None:
        sections.append(current)
    return sections


def _split_blocks(lines: List[str]) -> List[List[str]]:
    blocks: List[List[str]] = []
    current: List[str] = []
    in_fence = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            current.append(line)
            continue
        if not stripped and not in_fence:
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)

    if current:
        blocks.append(current)
    return blocks


def _is_table_block(block: List[str]) -> bool:
    if len(block) < 2 or not any("|" in line for line in block):
        return False

    for line in block:
        cells = line.strip().strip("|").split("|")
        if len(cells) >= 2 and all(
            re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in cells
        ):
            return True
    return False


def _chunk_section(section: Dict[str, object]) -> List[Dict[str, object]]:
    heading = str(section["heading"])
    heading_path = list(section["heading_path"])
    lines = list(section["lines"])
    blocks = _split_blocks(lines)
    if not blocks:
        blocks = [[]]

    chunks: List[str] = []
    current_blocks: List[str] = []
    current_length = 0

    def flush() -> None:
        nonlocal current_blocks, current_length
        if current_blocks:
            chunks.append("\n\n".join(current_blocks).strip())
            current_blocks = []
            current_length = 0

    for block in blocks:
        block_text = "\n".join(block).strip()
        if not block_text:
            continue

        is_table = _is_table_block(block)
        if current_blocks and current_length + len(block_text) + 2 > MAX_CHUNK_CHARS:
            flush()

        current_blocks.append(block_text)
        current_length += len(block_text) + 2

        # A table is an indivisible block, even when it is larger than the
        # normal chunk target.
        if is_table and current_length >= MAX_CHUNK_CHARS:
            flush()

    flush()
    if not chunks:
        chunks = [""]

    return [
        {
            "heading": heading,
            "heading_path": heading_path,
            "content": content,
            "source_relative_path": SPEC_SOURCE_RELATIVE_PATH,
        }
        for content in chunks
    ]


def load_spec_chunks() -> List[Dict[str, object]]:
    """Load ET1100.md and split it into heading-aware deterministic chunks."""
    markdown = _load_markdown(SPEC_MARKDOWN_PATH)
    chunks: List[Dict[str, object]] = []
    for section in _parse_sections(markdown):
        chunks.extend(_chunk_section(section))
    return chunks


def _query_terms(query: str) -> List[str]:
    tokens = _TOKEN_PATTERN.findall(query)
    terms = [
        token.casefold()
        for token in tokens
        if token.casefold().startswith("0x")
        or (len(token) >= 3 and token.casefold() not in _STOP_WORDS)
    ]
    return list(dict.fromkeys(terms))


def _is_front_matter(chunk: Dict[str, object]) -> bool:
    heading_path = " ".join(str(value) for value in chunk["heading_path"])
    folded_path = heading_path.casefold()
    return any(marker in folded_path for marker in _FRONT_MATTER_MARKERS)


def _score_chunk(query: str, terms: List[str], chunk: Dict[str, object]):
    heading = str(chunk["heading"])
    content = str(chunk["content"])
    folded_heading = heading.casefold()
    folded_content = content.casefold()
    folded_query = query.casefold()
    score = 0
    matched_terms = []

    if folded_query in folded_heading:
        score += 240
    if folded_query in folded_content:
        score += 120

    for term in terms:
        in_heading = term in folded_heading
        in_content = term in folded_content
        if in_heading:
            score += 90
            matched_terms.append(term)
        elif in_content:
            score += 30
            matched_terms.append(term)

    if _is_front_matter(chunk):
        score -= 220
    if score == 0:
        return None
    return score, matched_terms


def _make_excerpt(content: str, query: str, context_chars: int = 260) -> str:
    searchable = content or query
    position = searchable.casefold().find(query.casefold())
    if position < 0:
        return searchable[: context_chars * 2].strip()

    start = max(0, position - context_chars)
    end = min(len(searchable), position + len(query) + context_chars)
    excerpt = searchable[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(searchable):
        excerpt += "..."
    return excerpt


def search_spec_markdown(
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> List[Dict[str, object]]:
    """Return the most relevant ET1100.md sections or deterministic chunks."""
    normalized_query = _validate_query(query)
    normalized_limit = _validate_limit(limit)
    terms = _query_terms(normalized_query)
    scored = []
    for index, chunk in enumerate(load_spec_chunks()):
        result = _score_chunk(normalized_query, terms, chunk)
        if result is None:
            continue
        score, matched_terms = result
        scored.append((score, index, matched_terms, chunk))

    scored.sort(key=lambda item: (-item[0], item[1]))
    results = []
    for score, _, matched_terms, chunk in scored[:normalized_limit]:
        result = dict(chunk)
        result["excerpt"] = _make_excerpt(str(chunk["content"]), normalized_query)
        result["matched_terms"] = matched_terms
        result["score"] = score
        results.append(result)
    return results
