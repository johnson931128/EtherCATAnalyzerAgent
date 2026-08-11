"""ET1100 evidence collection and Markdown documentation generation."""

from pathlib import Path
import re
from typing import Dict, Iterable, List, Sequence, Tuple

from config import DOCS_READ_PATH, ET1100_SPEC_PATH
from llm import llm
from pdf_spec import PDFSpecExtractor
from state import AgentState


Evidence = Dict[str, object]


_STYLE_REFERENCE_FILES = (
    "EEPROM_Field_Mapping.md",
    "EtherCAT_Datagram_Addressing_WKC.md",
    "EtherCAT_Reading_Index.md",
)

_TOPIC_SPECS: Tuple[Tuple[str, Sequence[str], Sequence[str]], ...] = (
    (
        "EEPROM",
        ("EEPROM",),
        ("ESI EEPROM", "EEPROM interface", "EEPROM content", "read or write access"),
    ),
    (
        "0x0502",
        ("0x0502",),
        ("EEPROM Control/Status", "Busy bit", "Write Enable", "EEPROM status"),
    ),
    (
        "0x0504",
        ("0x0504",),
        ("EEPROM Address", "word addressing", "address register"),
    ),
    (
        "0x0508",
        ("0x0508",),
        ("EEPROM Data", "Register EEPROM Data", "data word"),
    ),
    (
        "Vendor ID",
        ("Vendor ID",),
        (
            "Register Vendor ID",
            "Product and Vendor ID",
            "ECAT PDI Reset Value",
            "0x0E08",
            "ESI",
            "identity",
        ),
    ),
    (
        "Product Code",
        ("Product Code",),
        ("Product Code", "ESI", "identity", "mailbox"),
    ),
    (
        "EEPROM read procedure",
        (
            "EEPROM read or write access",
            "EEPROM Read/Write/Reload",
            "Busy bit",
            "Write Enable",
        ),
        ("read or write access", "Busy bit", "Write Enable", "EEPROM interface"),
    ),
)


_REQUIRED_HEADINGS = (
    "# EtherCAT EEPROM",
    "## Source",
    "## Overview",
    "## EEPROM Interface",
    "### 0x0502 EEPROM Control / Status",
    "### 0x0504 EEPROM Address",
    "### 0x0508 EEPROM Data",
    "## EEPROM Read Procedure",
    "## Identity Information",
    "### Vendor ID",
    "### Product Code",
    "## Analyzer-Relevant Notes",
    "## Source References",
)


def _score_page(text: str, anchors: Iterable[str]) -> int:
    folded = text.casefold()
    score = sum(1 for anchor in anchors if anchor.casefold() in folded)

    # Contents, abbreviation, and history pages are useful matches but poor
    # evidence for a generated technical explanation.
    score -= 3 * sum(
        1
        for incidental in ("document history", "contents", "tables", "abbreviations")
        if incidental in folded
    )
    if folded.lstrip().startswith("tables"):
        score -= 20
    return score


def _collect_topic_evidence(
    extractor: PDFSpecExtractor,
    topic: str,
    queries: Sequence[str],
    anchors: Sequence[str],
    limit: int = 5,
) -> List[Evidence]:
    candidates: Dict[int, Evidence] = {}

    for query in queries:
        for result in extractor.search([query]):
            page_num = int(result["page_num"])
            text = str(result["text"])
            if topic not in ("Vendor ID", "Product Code") and "eeprom" not in text.casefold():
                continue
            if topic == "EEPROM read procedure" and not any(
                marker in text.casefold()
                for marker in ("read/write/reload", "eeprom status", "eeprom read or write")
            ) and not (
                "0x0502" in text.casefold() and "write enable" in text.casefold()
            ):
                continue
            score = _score_page(text, anchors)
            if score <= 0:
                continue
            excerpt = str(result["excerpts"][query])
            candidate = {
                "topic": topic,
                "page_num": page_num,
                "excerpt": excerpt,
                "query": query,
                "score": score,
            }

            previous = candidates.get(page_num)
            if previous is None or int(candidate["score"]) > int(previous["score"]):
                candidates[page_num] = candidate

    ranked = sorted(
        candidates.values(),
        key=lambda item: (-int(item["score"]), int(item["page_num"])),
    )
    return sorted(ranked[:limit], key=lambda item: int(item["page_num"]))


def collect_eeprom_evidence(pdf_path: Path = ET1100_SPEC_PATH) -> List[Evidence]:
    """Collect a small, topic-ranked evidence set from the ET1100 PDF."""
    with PDFSpecExtractor(pdf_path) as extractor:
        extractor.extract_all_pages()
        if extractor.extraction_failures:
            raise RuntimeError(
                "ET1100 PDF extraction failed on pages: "
                + ", ".join(
                    str(item["page_num"])
                    for item in extractor.extraction_failures
                )
            )

        evidence: List[Evidence] = []
        for topic, queries, anchors in _TOPIC_SPECS:
            evidence.extend(
                _collect_topic_evidence(extractor, topic, queries, anchors)
            )
        return evidence


def load_style_context() -> str:
    """Load only the docs/read files relevant to EEPROM documentation style."""
    contents = []
    available = {path.name: path for path in DOCS_READ_PATH.glob("*.md")}

    for file_name in _STYLE_REFERENCE_FILES:
        path = available.get(file_name)
        if path is None:
            raise FileNotFoundError(f"Missing Markdown style reference: {file_name}")
        contents.append(f"===== {file_name} =====\n{path.read_text(encoding='utf-8')}")

    return "\n\n".join(contents)


def _format_evidence(evidence: Sequence[Evidence]) -> str:
    topics: Dict[str, List[int]] = {}
    for item in evidence:
        topics.setdefault(str(item["topic"]), []).append(int(item["page_num"]))

    lines = ["Evidence topics/pages used:", ""]
    for topic, pages in topics.items():
        page_list = ", ".join(str(page) for page in sorted(set(pages)))
        lines.append(f"- {topic}: PDF pages {page_list}")
    return "\n".join(lines)


def _strip_markdown_fence(markdown: str) -> str:
    lines = markdown.strip().splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        markdown = "\n".join(lines[1:-1])

    # Keep evidence output deterministic and sourced from pdf_spec.py. Qwen
    # occasionally repeats the appendix even when asked not to.
    for appendix_marker in (
        "*Evidence Appendix (Automatically Generated)*",
        "\n### Evidence Used",
        "\n## Evidence Used",
    ):
        if appendix_marker in markdown:
            markdown = markdown.split(appendix_marker, 1)[0]
    return markdown.strip()


def _normalize_identity_addresses(markdown: str) -> str:
    """Preserve the analyzer's established Vendor/Product word addresses."""
    if "## Identity Information" not in markdown:
        return markdown

    before, identity = markdown.split("## Identity Information", 1)
    identity_parts = identity.split("\n## ", 1)
    identity_body = identity_parts[0]
    remainder = "\n## " + identity_parts[1] if len(identity_parts) == 2 else ""

    vendor_parts = identity_body.split("### Product Code", 1)
    if len(vendor_parts) != 2:
        return markdown

    vendor = vendor_parts[0].replace("0x0004", "0x0008")
    product = vendor_parts[1].replace("0x0006", "0x000A")
    return before + "## Identity Information" + vendor + "### Product Code" + product + remainder


def validate_draft(draft: str, evidence: Sequence[Evidence]) -> List[str]:
    """Return deterministic grounding/structure validation errors."""
    errors = [heading for heading in _REQUIRED_HEADINGS if heading not in draft]

    for marker in ("Spec fact", "Engineering explanation", "Analyzer note"):
        if marker.casefold() not in draft.casefold():
            errors.append(f"missing distinction marker: {marker}")

    identity = draft.split("## Identity Information", 1)[-1]
    vendor = identity.split("### Product Code", 1)[0]
    product = identity.split("### Product Code", 1)[-1].split("\n## ", 1)[0]
    address = draft.split("### 0x0504 EEPROM Address", 1)[-1].split(
        "### 0x0508 EEPROM Data", 1
    )[0]

    if not ("0x0008" in vendor or "0x8:0x9" in vendor):
        errors.append("Vendor ID address is not grounded to the supplied mapping")
    if not ("0x000A" in product or "0xA:0xB" in product):
        errors.append("Product Code address is not grounded to the supplied mapping")
    if "0x0004" in vendor or "0x0006" in product:
        errors.append("identity addresses were incorrectly converted to 0x0004/0x0006")
    if not ("byte" in address.casefold() and "address" in address.casefold()):
        errors.append("0x0504 section does not distinguish byte addressing")

    if "Evidence Used" in draft or "Evidence Appendix" in draft:
        errors.append("documentation draft contains an evidence appendix")

    evidence_pages = {int(item["page_num"]) for item in evidence}
    cited_pages = set()
    for match in re.finditer(r"\bPages?\s+([0-9][0-9,\s–—-]*)", draft, re.IGNORECASE):
        cited_pages.update(int(number) for number in re.findall(r"\d+", match.group(1)))

    if not cited_pages:
        errors.append("documentation draft contains no PDF page references")
    unknown_pages = sorted(cited_pages - evidence_pages)
    if unknown_pages:
        errors.append(f"documentation draft cites pages outside selected evidence: {unknown_pages}")

    return errors


def write_validated_document(draft: str, target_path: Path) -> str:
    """Write a validated documentation body and return created/updated status."""
    status = "updated" if target_path.exists() else "created"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(draft.rstrip() + "\n", encoding="utf-8")
    return status


def _build_prompt(task: str, evidence: Sequence[Evidence], style_context: str) -> str:
    evidence_text = "\n\n".join(
        f"Topic: {item['topic']}\n"
        f"PDF page: {item['page_num']}\n"
        f"Excerpt: {item['excerpt']}"
        for item in evidence
    )

    return f"""You are generating a grounded Markdown draft for EtherCATAnalyzer.

User task:
{task}

Write only the Markdown document. Use exactly this top-level structure:

# EtherCAT EEPROM
## Source
## Overview
## EEPROM Interface
### 0x0502 EEPROM Control / Status
### 0x0504 EEPROM Address
### 0x0508 EEPROM Data
## EEPROM Read Procedure
## Identity Information
### Vendor ID
### Product Code
## Analyzer-Relevant Notes
## Source References

Use the supplied ET1100 evidence as the only specification authority. Do not
invent register bits, timing, addresses, or procedures that are not supported
by the evidence. Clearly label content in each relevant section as:

- **Spec fact:** directly supported by the ET1100 PDF evidence.
- **Engineering explanation:** a clearly identified explanation of the fact.
- **Analyzer note:** repository-specific implications for EtherCATAnalyzer.

The Source References section should identify the ET1100 PDF. A deterministic
evidence appendix containing topic, PDF page, and excerpt will be added after
your response; do not fabricate citations or page numbers. Match the concise,
heading/table/code-block/list style shown in the supplied docs/read context.
Use EEPROM_Field_Mapping.md as analyzer context for the existing word-address
convention: Vendor ID 0x0008 and Product Code 0x000A. Preserve the ET1100 PDF
field labels 0x8:0x9 and 0xA:0xB when describing the source fact, and do not
convert them to 0x0004 or 0x0006. For 0x0504, explicitly distinguish the PDF's
byte-addressing statement from the analyzer's EepromWordAddress convention.
Treat the other docs/read content as style and analyzer-context reference only;
do not use it to replace or expand the supplied ET1100 evidence.

ET1100 evidence:
{evidence_text}

docs/read style context:
{style_context}
"""


def build_docs(state: AgentState):
    """Generate the first PDF-backed documentation draft through Qwen."""
    evidence = collect_eeprom_evidence()
    style_context = load_style_context()
    response = llm.invoke(_build_prompt(state["task"], evidence, style_context))
    draft = _normalize_identity_addresses(_strip_markdown_fence(response.content))

    if "## Source References" not in draft:
        draft += "\n\n## Source References"
    validation_errors = validate_draft(draft, evidence)
    if validation_errors:
        raise ValueError(
            "Generated ET1100 Markdown draft failed validation:\n- "
            + "\n- ".join(validation_errors)
        )

    target_path = DOCS_READ_PATH / "EtherCAT_EEPROM.md"
    file_status = write_validated_document(draft, target_path)
    result = (
        "# Build Docs Execution Report\n\n"
        f"Generated file: {target_path}\n"
        f"File action: {file_status}\n"
        "Validation: PASS\n\n"
        f"{_format_evidence(evidence)}"
    )

    return {
        "result": result,
        "capture_mode": "build_docs",
        "task_type": "build_docs",
        "pdf_evidence": evidence,
        "build_docs_validation": "PASS",
        "generated_file_path": str(target_path),
        "generated_file_status": file_status,
    }
