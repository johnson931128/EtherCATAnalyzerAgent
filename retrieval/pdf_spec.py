"""
ET1100 PDF specification text extraction and search.

Uses PyMuPDF (fitz) for deterministic PDF text extraction.
"""

from pathlib import Path
import sys
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF

from core.config import ET1100_SPEC_PATH


class PDFSpecExtractor:
    """Extract and search text from the ET1100 datasheet PDF."""

    def __init__(self, pdf_path: Optional[Path] = None):
        """
        Initialize the extractor with the PDF path.

        Args:
            pdf_path: Path to the PDF file. Defaults to ET1100_SPEC_PATH from config.
        """
        self.pdf_path = Path(pdf_path) if pdf_path is not None else ET1100_SPEC_PATH
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

    print(f"PDF Path: {ET1100_SPEC_PATH}")
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
