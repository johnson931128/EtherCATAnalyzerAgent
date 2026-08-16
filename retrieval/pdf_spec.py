"""
ET1100 PDF specification text extraction and search.

Uses PyMuPDF (fitz) for deterministic PDF text extraction.
"""

from pathlib import Path
import re
import sys
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from core.config import SPEC_ORIGINAL_ROOT


RAW_SPEC_NAME = "ET1100"
DEFAULT_RAW_SEARCH_LIMIT = 5
MAX_RAW_SEARCH_LIMIT = 10
MAX_RAW_PAGE_COUNT = 5
MAX_RAW_QUERY_LENGTH = 200


def resolve_spec_pdf(
    spec_name: str,
    original_root: Optional[Path] = None,
) -> Path:
    """Resolve exactly one PDF from a repository specification directory."""
    if not isinstance(spec_name, str) or not spec_name.strip():
        raise ValueError("Specification name must be a non-empty directory name")

    normalized_name = spec_name.strip()
    relative_name = Path(normalized_name)
    if (
        relative_name.is_absolute()
        or len(relative_name.parts) != 1
        or relative_name.parts[0] in {".", ".."}
    ):
        raise ValueError("Specification name must be a single directory name")

    root = Path(original_root) if original_root is not None else SPEC_ORIGINAL_ROOT
    spec_directory = root / normalized_name
    if not spec_directory.is_dir():
        raise FileNotFoundError(
            f"Specification directory not found: {spec_directory}"
        )

    pdf_paths = sorted(
        (
            path
            for path in spec_directory.iterdir()
            if path.is_file() and path.suffix.casefold() == ".pdf"
        ),
        key=lambda path: path.name.casefold(),
    )
    if not pdf_paths:
        raise FileNotFoundError(
            f"No PDF found in specification directory: {spec_directory}"
        )
    if len(pdf_paths) > 1:
        names = ", ".join(path.name for path in pdf_paths)
        raise RuntimeError(
            "Ambiguous specification source: expected exactly one PDF in "
            f"{spec_directory}, found {len(pdf_paths)} ({names})"
        )

    return pdf_paths[0]


class PDFSpecExtractor:
    """Extract and search text from the ET1100 datasheet PDF."""

    def __init__(self, pdf_path: Optional[Path] = None):
        """
        Initialize the extractor with the PDF path.

        Args:
            pdf_path: Path to the PDF file. Defaults to the single PDF in
                spec/original/ET1100/.
        """
        self.pdf_path = (
            Path(pdf_path)
            if pdf_path is not None
            else resolve_spec_pdf("ET1100")
        )
        self._doc: Optional[fitz.Document] = None
        self._pages: List[Dict[str, object]] = []
        self._extraction_failures: List[Dict[str, object]] = []
        self._extracted = False

    def open(self) -> int:
        """
        Open the PDF and return the total number of pages.

        Returns:
            Total number of pages in the PDF.

        Raises:
            FileNotFoundError: If the PDF file does not exist.
            RuntimeError: If the PDF cannot be opened.
        """
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {self.pdf_path}")

        self.close()
        try:
            self._doc = fitz.open(str(self.pdf_path))
        except Exception as exc:
            raise RuntimeError(f"Could not open PDF: {self.pdf_path}") from exc

        self._pages = []
        self._extraction_failures = []
        self._extracted = False
        return len(self._doc)

    def extract_all_pages(self) -> List[Dict[str, object]]:
        """
        Extract text from all pages in the PDF.

        Returns:
            List of dicts with keys: 'page_num', 'text'
            page_num is 1-based (PDF page numbering).
        """
        if self._doc is None:
            self.open()

        self._pages = []
        self._extraction_failures = []

        for i in range(len(self._doc)):
            page_num = i + 1  # 1-based page number
            try:
                page = self._doc[i]
                text = page.get_text()
                self._pages.append({
                    'page_num': page_num,
                    'text': text
                })
            except Exception as e:
                self._extraction_failures.append({
                    'page_num': page_num,
                    'error': str(e)
                })

        self._extracted = True
        return self._pages

    @property
    def extraction_failures(self) -> List[Dict[str, object]]:
        """Return page-level extraction failures from the latest extraction."""
        return list(self._extraction_failures)

    def get_page(self, page_num: int) -> Optional[Dict[str, object]]:
        """
        Get the extracted text for a specific page.

        Args:
            page_num: 1-based page number.

        Returns:
            Dict with 'page_num' and 'text', or None if not found.
        """
        if not self._extracted:
            self.extract_all_pages()

        for page in self._pages:
            if page['page_num'] == page_num:
                return page
        return None

    def search(self, keywords: List[str]) -> List[Dict[str, object]]:
        """
        Search for pages containing any of the given keywords.

        Args:
            keywords: List of search terms (case-insensitive).

        Returns:
            List of dicts with keys:
                - 'page_num': 1-based page number
                - 'text': full page text
                - 'matches': list of keywords found on this page
                - 'excerpt': short excerpt showing the match context
        """
        if not self._extracted:
            self.extract_all_pages()

        normalized_keywords = []
        for keyword in keywords:
            if not isinstance(keyword, str) or not keyword.strip():
                raise ValueError("Search keywords must be non-empty strings")
            normalized_keywords.append((keyword, keyword.casefold()))

        results: List[Dict[str, object]] = []
        for page in self._pages:
            text = str(page['text'])
            text_folded = text.casefold()
            found_keywords: List[str] = []
            excerpts: Dict[str, str] = {}

            for keyword, keyword_folded in normalized_keywords:
                if keyword_folded in text_folded:
                    found_keywords.append(keyword)
                    excerpts[keyword] = self._make_excerpt(text, keyword)

            if found_keywords:
                results.append({
                    'page_num': page['page_num'],
                    'text': page['text'],
                    'matches': found_keywords,
                    'excerpt': excerpts[found_keywords[0]],
                    'excerpts': excerpts,
                })

        return results

    def _make_excerpt(self, text: str, keyword: str, context_chars: int = 100) -> str:
        """
        Create a short excerpt showing keyword match context.

        Args:
            text: Full page text.
            keyword: Matched keyword.
            context_chars: Number of characters before/after match.

        Returns:
            Truncated excerpt string.
        """
        position = text.casefold().find(keyword.casefold())
        if position == -1:
            return text[:200] + "..." if len(text) > 200 else text

        excerpt_start = max(0, position - context_chars)
        excerpt_end = min(len(text), position + context_chars + len(keyword))

        excerpt = text[excerpt_start:excerpt_end]

        # Add ellipsis if truncated
        if excerpt_start > 0:
            excerpt = "..." + excerpt
        if excerpt_end < len(text):
            excerpt = excerpt + "..."

        # Replace newlines with spaces for cleaner display
        excerpt = excerpt.replace('\n', ' ').replace('\r', '')
        # Collapse multiple spaces
        while '  ' in excerpt:
            excerpt = excerpt.replace('  ', ' ')

        return excerpt

    def close(self):
        """Close the PDF document."""
        if self._doc:
            self._doc.close()
            self._doc = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def extract_pdf_text(
    pdf_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """
    Convenience function to extract all text from the ET1100 PDF.

    Args:
        pdf_path: Optional path override.

    Returns:
        Tuple of (pages_list, failures_list)
        pages_list: List of {'page_num': int, 'text': str}
        failures_list: List of {'page_num': int, 'error': str}
    """
    extractor = PDFSpecExtractor(pdf_path)
    try:
        pages = extractor.extract_all_pages()
        return pages, extractor.extraction_failures
    finally:
        extractor.close()


def search_pdf(
    keywords: List[str], pdf_path: Optional[Path] = None
) -> List[Dict[str, object]]:
    """
    Convenience function to search the ET1100 PDF for keywords.

    Args:
        keywords: List of search terms.
        pdf_path: Optional path override.

    Returns:
        List of matching page results with excerpts.
    """
    with PDFSpecExtractor(pdf_path) as extractor:
        return extractor.search(keywords)


def _validate_raw_spec(spec: str) -> str:
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("spec must be the string 'ET1100'")

    normalized_spec = spec.strip()
    if normalized_spec != RAW_SPEC_NAME:
        raise ValueError(
            f"Raw PDF evidence supports only spec='{RAW_SPEC_NAME}'"
        )
    return normalized_spec


def _validate_raw_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    normalized_query = query.strip()
    if len(normalized_query) > MAX_RAW_QUERY_LENGTH:
        raise ValueError(
            f"query must not exceed {MAX_RAW_QUERY_LENGTH} characters"
        )
    return normalized_query


def _validate_raw_search_limit(limit: int) -> int:
    if type(limit) is not int:
        raise ValueError("limit must be an integer")
    if not 1 <= limit <= MAX_RAW_SEARCH_LIMIT:
        raise ValueError(
            f"limit must be between 1 and {MAX_RAW_SEARCH_LIMIT}"
        )
    return limit


def _raw_search_terms(query: str) -> List[str]:
    tokens = re.findall(r"0x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9-]*", query)
    words = [token for token in tokens if len(token) >= 3]
    phrases = [f"{first} {second}" for first, second in zip(words, words[1:])]
    terms = [query, *phrases, *words]
    return list(dict.fromkeys(term.strip() for term in terms if term.strip()))


def _raw_search_score(query: str, result: Dict[str, object]) -> int:
    text = str(result.get("text", ""))
    folded_text = text.casefold()
    score = len(result.get("matches", [])) * 25
    if query.casefold() in folded_text:
        score += 100
    if any(marker in folded_text for marker in ("register", "table", "section")):
        score += 10
    return score


def search_spec_raw(
    spec: str = RAW_SPEC_NAME,
    query: str = "",
    limit: int = DEFAULT_RAW_SEARCH_LIMIT,
) -> List[Dict[str, object]]:
    """Search the controlled raw specification PDF and return page evidence."""
    normalized_spec = _validate_raw_spec(spec)
    normalized_query = _validate_raw_query(query)
    normalized_limit = _validate_raw_search_limit(limit)
    pdf_path = resolve_spec_pdf(normalized_spec)
    candidates = search_pdf(
        _raw_search_terms(normalized_query),
        pdf_path=pdf_path,
    )
    candidates = sorted(
        candidates,
        key=lambda result: (
            -_raw_search_score(normalized_query, result),
            int(result["page_num"]),
        ),
    )
    return [
        {
            "spec": normalized_spec,
            "source_filename": pdf_path.name,
            "pdf_page": int(result["page_num"]),
            "matched_terms": list(result["matches"]),
            "excerpt": str(result["excerpt"]),
        }
        for result in candidates[:normalized_limit]
    ]


def _validate_raw_pages(pages: List[int]) -> List[int]:
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages must be a non-empty list")

    unique_pages = []
    for page in pages:
        if type(page) is not int or page <= 0:
            raise ValueError("each page must be a positive integer")
        if page not in unique_pages:
            unique_pages.append(page)

    if len(unique_pages) > MAX_RAW_PAGE_COUNT:
        raise ValueError(
            f"pages must contain at most {MAX_RAW_PAGE_COUNT} unique page numbers"
        )
    return unique_pages


def get_spec_raw_pages(
    spec: str = RAW_SPEC_NAME,
    pages: Optional[List[int]] = None,
) -> List[Dict[str, object]]:
    """Read complete extracted text from selected physical PDF pages."""
    normalized_spec = _validate_raw_spec(spec)
    normalized_pages = _validate_raw_pages(pages)
    pdf_path = resolve_spec_pdf(normalized_spec)

    extractor = PDFSpecExtractor(pdf_path)
    try:
        total_pages = extractor.open()
        out_of_range = [page for page in normalized_pages if page > total_pages]
        if out_of_range:
            values = ", ".join(str(page) for page in out_of_range)
            raise ValueError(
                f"PDF page number out of range for {pdf_path.name}: {values}; "
                f"valid range is 1-{total_pages}"
            )

        extracted_pages = extractor.extract_all_pages()
        page_by_number = {
            int(page["page_num"]): str(page["text"])
            for page in extracted_pages
        }
        missing_pages = [
            page_number
            for page_number in normalized_pages
            if page_number not in page_by_number
        ]
        if missing_pages:
            values = ", ".join(str(page) for page in missing_pages)
            raise RuntimeError(
                f"Could not extract requested PDF pages: {values}"
            )
        return [
            {
                "spec": normalized_spec,
                "source_filename": pdf_path.name,
                "pdf_page": page_number,
                "text": page_by_number[page_number],
            }
            for page_number in normalized_pages
        ]
    finally:
        extractor.close()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    # Validation/debug entry point
    print("=" * 60)
    print("ET1100 PDF Text Extraction and Search Validation")
    print("=" * 60)
    print()

    # Test keywords
    test_keywords = [
        "0x0502",
        "0x0504",
        "0x0508",
        "Vendor ID",
        "Product Code",
        "Auto Increment",
        "Working Counter"
    ]

    print(f"PDF Path: {resolve_spec_pdf('ET1100')}")
    print()

    with PDFSpecExtractor() as extractor:
        # Extract all pages
        pages = extractor.extract_all_pages()
        failures = extractor.extraction_failures
        successful = len(pages)
        failed = len(failures)
        total_pages = successful + failed
        print(f"Total PDF pages: {total_pages}")
        print()
        print(f"Pages extracted successfully: {successful}")
        print(f"Pages with extraction failures: {failed}")
        print()

        # Search for each keyword
        print("Keyword Search Results:")
        print("-" * 60)

        for keyword in test_keywords:
            results = extractor.search([keyword])
            if results:
                page_nums = [r['page_num'] for r in results]
                print(f"\n{keyword}:")
                print(f"  Matching pages: {page_nums}")
                print(f"  Count: {len(results)} page(s)")
                print("  Representative excerpts:")
                for result in results[:5]:
                    print(f"    PDF page {result['page_num']}: {result['excerpt']}")
            else:
                print(f"\n{keyword}:")
                print(f"  No matches found")

    print()
    print("=" * 60)
    print("Validation complete")
    print("=" * 60)
