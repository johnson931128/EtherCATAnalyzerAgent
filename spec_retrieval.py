"""Candidate search and LLM selection for the ET1100 PDF specification."""

import json
import re
from typing import Dict, List

from llm import llm
from pdf_spec import PDFSpecExtractor


_IGNORED_TERMS = {
    "about",
    "analyze",
    "and",
    "behavior",
    "current",
    "explain",
    "for",
    "from",
    "how",
    "is",
    "into",
    "of",
    "on",
    "reconstruction",
    "the",
    "to",
    "with",
}
_TERM_PATTERN = re.compile(r"0x[0-9A-Fa-f]+|[A-Za-z]+")


def _unique_terms(terms: List[str]) -> List[str]:
    seen = set()
    unique = []
    for term in terms:
        folded = term.casefold()
        if folded not in seen:
            seen.add(folded)
            unique.append(term)
    return unique


def _extract_search_terms(task: str) -> List[str]:
    tokens = _TERM_PATTERN.findall(task)
    hex_values = [token for token in tokens if token.casefold().startswith("0x")]
    phrase_words = [
        token
        for token in tokens
        if not token.casefold().startswith("0x")
        and token.casefold() not in _IGNORED_TERMS
    ]
    words = [token for token in phrase_words if len(token) >= 3]

    phrases = []
    for first, second in zip(phrase_words, phrase_words[1:]):
        phrases.append(f"{first} {second}")

    return _unique_terms(hex_values + phrases + words)


def _parse_selected_pages(content: str, valid_pages: set, max_pages: int) -> List[int]:
    selected_pages = []
    values = [line.strip() for line in content.splitlines() if line.strip()]
    if any(not re.fullmatch(r"\d+", value) for value in values):
        return []

    for value in values:
        page_num = int(value)
        if page_num not in valid_pages or page_num in selected_pages:
            continue
        selected_pages.append(page_num)
        if len(selected_pages) == max_pages:
            break
    return selected_pages


def select_spec_with_llm(task: str, max_pages: int = 5) -> Dict[str, object]:
    """Search candidate ET1100 pages and ask Qwen to select relevant pages."""
    max_pages = min(max_pages, 5)
    if not task.strip() or max_pages <= 0:
        return {"selected_pages": [], "page_texts": {}}

    search_terms = _extract_search_terms(task)
    if not search_terms:
        return {"selected_pages": [], "page_texts": {}}

    with PDFSpecExtractor() as extractor:
        search_results = extractor.search(search_terms)
        candidates = {}
        for result in search_results:
            page_num = int(result["page_num"])
            candidate = candidates.setdefault(
                page_num,
                {"page_num": page_num, "matched_terms": [], "excerpts": []},
            )
            for term in result["matches"]:
                if term not in candidate["matched_terms"]:
                    candidate["matched_terms"].append(term)
                excerpt = result["excerpts"].get(term)
                if excerpt and excerpt not in candidate["excerpts"]:
                    candidate["excerpts"].append(excerpt)

        candidate_manifest = sorted(
            candidates.values(),
            key=lambda candidate: (-len(candidate["matched_terms"]), candidate["page_num"]),
        )[:12]
        if not candidate_manifest:
            return {"selected_pages": [], "page_texts": {}}

        prompt = (
            "Select up to {max_pages} relevant ET1100 PDF pages for this task.\n"
            "Return only PDF page numbers, one per line. Do not return any other text.\n\n"
            "Task:\n{task}\n\n"
            "Candidate page manifest:\n{manifest}"
        ).format(
            max_pages=max_pages,
            task=task.strip(),
            manifest=json.dumps(candidate_manifest, ensure_ascii=False, separators=(",", ":")),
        )
        response = llm.invoke(prompt)
        valid_pages = {candidate["page_num"] for candidate in candidate_manifest}
        selected_pages = _parse_selected_pages(str(response.content), valid_pages, max_pages)

        page_texts = {}
        for page_num in selected_pages:
            page = extractor.get_page(page_num)
            if page is not None:
                page_texts[page_num] = str(page["text"])

        return {"selected_pages": selected_pages, "page_texts": page_texts}
