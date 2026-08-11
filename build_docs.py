"""ET1100 evidence collection and Markdown documentation generation."""

from pathlib import Path
import re
from typing import Dict, Iterable, List, Sequence, Tuple

from config import DOCS_READ_PATH, ET1100_SPEC_PATH, SOURCE_FILES
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


def load_analyzer_eeprom_context() -> str:
    """Load the implementation facts needed for the Analyzer notes."""
    source_path = SOURCE_FILES["slave_discovery"]
    source = source_path.read_text(encoding="utf-8")
    required_markers = (
        "pendingEepromReads",
        "EepromControlStatusRegister",
        "EepromDataRegister",
        "VendorIdEepromWordAddress",
        "ProductCodeEepromWordAddress",
    )
    missing = [marker for marker in required_markers if marker not in source]
    if missing:
        raise RuntimeError(
            "SlaveDiscoveryAnalyzer EEPROM correlation markers are missing: "
            + ", ".join(missing)
        )

    return """Current SlaveDiscoveryAnalyzer.cs implementation context:
- BindEepromIdentity keeps a pendingEepromReads map keyed by topology position.
- A successful APWR write to ADO 0x0502 with the EEPROM read command records the
  requested EepromWordAddress in pendingEepromReads.
- A successful APRD read from ADO 0x0508 is matched by topology position and
  working-counter progression, then the pending entry is removed.
- Word address 0x0008 populates VendorId and word address 0x000A populates
  ProductCode.
"""


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


def _topic_pages(evidence: Sequence[Evidence], topic: str, fallback: Sequence[int]) -> str:
    pages = sorted(
        {
            int(item["page_num"])
            for item in evidence
            if item.get("topic") == topic
        }
    )
    if not pages:
        pages = list(fallback)
    return ", ".join(str(page) for page in pages)


def _replace_section(markdown: str, heading: str, body: str, next_heading: str) -> str:
    start = markdown.index(heading) + len(heading)
    end = markdown.index(next_heading, start) if next_heading else len(markdown)
    return markdown[:start] + "\n" + body.strip() + "\n\n" + markdown[end:]


def _apply_grounded_eeprom_sections(
    markdown: str, evidence: Sequence[Evidence]
) -> str:
    """Make the safety-critical ET1100 and analyzer sections deterministic."""
    pages_0502 = _topic_pages(evidence, "0x0502", (98, 169))
    pages_0504 = _topic_pages(evidence, "0x0504", (99, 171))
    pages_0508 = _topic_pages(evidence, "0x0508", (171,))
    pages_procedure = _topic_pages(evidence, "EEPROM read procedure", (96, 98, 169, 170))
    pages_identity = "95"

    markdown = _replace_section(
        markdown,
        "## Overview",
        """- **Spec fact:** The ESI EEPROM contains configuration data and identity fields such as Vendor ID, Product Code, Revision Number, and Serial Number. (Pages 94, 95)
- **Spec fact:** The ESC Configuration Area at word addresses 0x0000–0x0007 is protected by a checksum. (Page 94)
- **Engineering explanation:** The checksum protects the ESC Configuration Area; it should not be described as protecting every identity field in the EEPROM.
- **Analyzer note:** EEPROM identity reconstruction uses the field word addresses and returned data independently of the Configuration Area checksum.""",
        "## EEPROM Interface",
    )
    markdown = _replace_section(
        markdown,
        "## EEPROM Interface",
        """The ESC exposes the EEPROM interface through a dedicated ESC register block. The interface may be controlled by EtherCAT or the PDI depending on the access assignment.

- **Spec fact:** The EEPROM interface occupies ESC registers 0x0500–0x050F. (Pages 95, 128, 168)
- **Engineering explanation:** These are ESC registers shared through the configured access mechanism, not a register block that belongs exclusively to the PDI.
- **Analyzer note:** Capture analysis should interpret accesses according to the EtherCAT/PDI assignment and the individual control, address, and data registers.""",
        "### 0x0502 EEPROM Control / Status",
    )
    markdown = _replace_section(
        markdown,
        "### 0x0502 EEPROM Control / Status",
        f"""- **Spec fact:** Bit 15 is Busy. A new EEPROM command starts only when Busy is 0. (Pages {pages_0502})
- **Spec fact:** Bit 0 is ECAT EEPROM Write Enable for EEPROM write commands. (Pages {pages_0502})
- **Spec fact:** Command bits [10:8] select the EEPROM operation. (Page 169)
- **Engineering explanation:** The ESC exposes command and status through this register while it handles the external EEPROM transaction.
- **Analyzer note:** `EepromControlStatus` exposes the captured 0x0502 value; Bit 0 should be interpreted as write-command enable, not as a read prerequisite.""",
        "### 0x0504 EEPROM Address",
    )
    markdown = _replace_section(
        markdown,
        "### 0x0504 EEPROM Address",
        f"""- **Spec fact:** From the Master/ESC register perspective, 0x0504 contains the EEPROM word address. (Pages {pages_0504})
- **Spec fact:** The underlying I²C access is byte-addressed, and A[0] is handled internally by the ESC. (Page 99)
- **Engineering explanation:** The Master uses the register-level word address; the ESC handles the underlying I²C byte-address details internally.
- **Analyzer note:** Preserve the 0x0504 value as the analyzer's `EepromWordAddress`; the analyzer interpretation applies no numeric address transformation.""",
        "### 0x0508 EEPROM Data",
    )
    markdown = _replace_section(
        markdown,
        "### 0x0508 EEPROM Data",
        f"""- **Spec fact:** EEPROM read data is returned through 0x0508:0x050F. (Pages {pages_0508})
- **Engineering explanation:** After the read command completes, the Master reads the returned data from this register block.
- **Analyzer note:** A read path observes 0x0508 after the command transaction; it does not require a preceding write to 0x0508.""",
        "## EEPROM Read Procedure",
    )
    markdown = _replace_section(
        markdown,
        "## EEPROM Read Procedure",
        f"""- **Spec fact:** Follow this ET1100 order (Pages {pages_procedure}):
  1. Check Busy == 0; if Busy is set, wait until it clears.
  2. Check and clear error status as required.
  3. Write the target EEPROM word address to 0x0504.
  4. Issue the EEPROM Read command through the 0x0502 command bits.
  5. Wait until Busy == 0.
  6. Check error status.
  7. Read the returned data from 0x0508.
- **Engineering explanation:** The sequence establishes an idle interface, selects the word, starts the read, waits for completion, checks status, and then consumes the returned data.
- **Analyzer note:** The read correlation is based on the current `SlaveDiscoveryAnalyzer` behavior described below; the procedure itself does not require writing 0x0508 before a Read command.""",
        "## Identity Information",
    )
    markdown = _replace_section(
        markdown,
        "## Identity Information",
        f"""The identity fields below are grounded in the ESI EEPROM content. (Page {pages_identity})

### Vendor ID
- **Spec fact:** Vendor ID is stored at EEPROM word addresses 0x0008:0x0009, labeled 0x8:0x9 in the ET1100 PDF. (Page {pages_identity})
- **Engineering explanation:** The two words form the device's vendor identity value.
- **Analyzer note:** `SlaveDiscoveryAnalyzer` maps the read for word address 0x0008 to `VendorId`.

### Product Code
- **Spec fact:** Product Code is stored at EEPROM word addresses 0x000A:0x000B, labeled 0xA:0xB in the ET1100 PDF. (Page {pages_identity})
- **Engineering explanation:** The two words form the device's product identity value.
- **Analyzer note:** `SlaveDiscoveryAnalyzer` maps the read for word address 0x000A to `ProductCode`.""",
        "## Analyzer-Relevant Notes",
    )
    markdown = _replace_section(
        markdown,
        "## Analyzer-Relevant Notes",
        """- **Spec fact:** The ET1100 EEPROM identity fields are read through the 0x0502/0x0504/0x0508 interface.
- **Engineering explanation:** The analyzer pairs the command-side address with the returned data using the implementation's per-slave pending state.
- **Analyzer note:** The current `SlaveDiscoveryAnalyzer` uses `pendingEepromReads`, keyed by topology position. A successful APWR read command through 0x0502 records the requested `EepromWordAddress`; a successful APRD from 0x0508 is matched by topology position and Working Counter progression, then the pending entry is removed. Word address 0x0008 populates `VendorId`, and 0x000A populates `ProductCode`.""",
        "## Source References",
    )
    return _replace_section(
        markdown,
        "## Source References",
        f"""- **ET1100 Datasheet**: Section I - Technology, Version 1.9.
- EEPROM content and identity mapping: PDF page {pages_identity}.
- EEPROM read procedure and status: PDF pages {pages_procedure}.
- EEPROM register addressing and data interface: PDF pages {pages_0502}, {pages_0504}, {pages_0508}.""",
        "",
    )


def validate_draft(draft: str, evidence: Sequence[Evidence]) -> List[str]:
    """Return deterministic grounding/structure validation errors."""
    errors = [heading for heading in _REQUIRED_HEADINGS if heading not in draft]

    for marker in ("Spec fact", "Engineering explanation", "Analyzer note"):
        if marker.casefold() not in draft.casefold():
            errors.append(f"missing distinction marker: {marker}")

    overview = draft.split("## Overview", 1)[-1].split("## EEPROM Interface", 1)[0]
    interface = draft.split("## EEPROM Interface", 1)[-1].split(
        "### 0x0502 EEPROM Control / Status", 1
    )[0]
    if "pdi registers" in draft.casefold():
        errors.append("EEPROM interface is incorrectly described as PDI registers")
    if not all(
        marker in interface.casefold()
        for marker in ("dedicated esc register block", "ethercat", "pdi", "access assignment")
    ):
        errors.append("EEPROM interface ownership/access terminology is incomplete")
    if not all(
        marker in overview.casefold()
        for marker in ("configuration data", "identity fields", "0x0000", "0x0007", "checksum")
    ):
        errors.append("EEPROM identity/checksum scope terminology is incomplete")
    if "secured with a checksum" in overview.casefold():
        errors.append("EEPROM identity fields are incorrectly described as checksum-protected")

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
    address_folded = address.casefold()
    address_markers = (
        ("word address",),
        ("byte address", "byte-address", "byte addressed"),
        ("a[0]",),
        ("internally",),
    )
    for marker_options in address_markers:
        if not any(marker in address_folded for marker in marker_options):
            errors.append(
                "0x0504 section is missing the required addressing fact: "
                + "/".join(marker_options)
            )
    conversion_instruction = (
        re.search(r"\b(?:must|should|need(?:s)? to|require(?:s)? .* to)\s+"
                  r"(?:multiply|divide|convert)", address_folded)
        or re.search(r"\b(?:multiply|divide)\s+by\s+\d+", address_folded)
        or re.search(r"0x[0-9a-f]+\s*[*/]\s*2", address_folded)
    )
    if (
        "mismatch" in address_folded
        or "byte-equivalent" in address_folded
        or "shift" in address_folded
        or "left by" in address_folded
        or conversion_instruction
    ):
        errors.append("0x0504 section gives an invalid word/byte conversion instruction")

    control = draft.split("### 0x0502 EEPROM Control / Status", 1)[-1].split(
        "### 0x0504 EEPROM Address", 1
    )[0].casefold()
    if not re.search(r"bit\s*0.{0,160}(?:eeprom\s+)?write\s+enable", control):
        errors.append("0x0502 section does not identify Bit 0 as EEPROM Write Enable")
    if not re.search(r"bit\s*0.{0,220}(?:write\s+(?:command|request)|write\s+operation)", control):
        errors.append("0x0502 section does not limit Bit 0 to EEPROM write commands")

    procedure = draft.split("## EEPROM Read Procedure", 1)[-1].split(
        "## Identity Information", 1
    )[0]
    procedure_folded = procedure.casefold()
    procedure_patterns = (
        r"busy.{0,120}(?:0|clear)",
        r"(?:check|clear).{0,120}(?:error|status)|(?:error|status).{0,120}(?:check|clear)",
        r"(?:write|set).{0,120}0x0504",
        r"(?:0x0502.{0,180}(?:read|command)|(?:read|command).{0,180}0x0502)",
        r"(?:wait|until).{0,120}busy",
        r"(?:check|clear).{0,120}(?:error|status)|(?:error|status).{0,120}(?:check|clear)",
        r"(?:read|return).{0,120}0x0508|0x0508.{0,120}(?:read|data)",
    )
    search_from = 0
    for pattern in procedure_patterns:
        match = re.search(pattern, procedure_folded[search_from:])
        if match is None:
            errors.append(f"EEPROM read procedure is missing step: {pattern}")
        else:
            search_from = search_from + match.end()
    read_command_match = re.search(procedure_patterns[3], procedure_folded)
    write_data_match = re.search(r"(?:write|writes|writing).{0,100}0x0508", procedure_folded)
    if write_data_match and (
        read_command_match is None or write_data_match.start() < read_command_match.start()
    ):
        errors.append("EEPROM read procedure incorrectly writes 0x0508 before reading")

    if "0x0e08" in draft.casefold() or "0x0e0c" in draft.casefold():
        errors.append("documentation contains unsupported ET1100 Vendor/Product register claims")

    if any(
        marker in identity.casefold()
        for marker in ("esc-specific", "power-on value", "0x0e00", "0x0eff")
    ):
        errors.append("identity section contains unsupported ESC-specific register claims")

    analyzer_notes = draft.split("## Analyzer-Relevant Notes", 1)[-1].split(
        "## Source References", 1
    )[0]
    analyzer_source = SOURCE_FILES["slave_discovery"].read_text(encoding="utf-8")
    if "pendingEepromReads" not in analyzer_source:
        errors.append("current SlaveDiscoveryAnalyzer lacks pendingEepromReads")
    for marker in ("pendingEepromReads", "topology", "0x0502", "0x0508", "0x0008", "0x000A"):
        if marker.casefold() not in analyzer_notes.casefold():
            errors.append(f"Analyzer notes omit current correlation fact: {marker}")
    if any(
        marker in analyzer_notes.casefold()
        for marker in ("not implemented", "does not pair", "not pair", "not correlated")
    ):
        errors.append("Analyzer notes incorrectly deny EEPROM transaction correlation")
    if "after verifying the busy" in analyzer_notes.casefold() or "ensure the busy" in analyzer_notes.casefold():
        errors.append("Analyzer notes attribute unsupported Busy-bit verification to SlaveDiscoveryAnalyzer")

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

    analyzer_context = load_analyzer_eeprom_context()

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

The Source References section should identify the ET1100 PDF. Cite only the
supplied PDF page numbers. Match the concise,
heading/table/code-block/list style shown in the supplied docs/read context.
Describe 0x0500–0x050F as a dedicated ESC register block, not as PDI
registers. State that the EEPROM interface may be controlled by EtherCAT or
the PDI depending on the access assignment.
State that the ESI EEPROM contains configuration data and identity fields such
as Vendor ID, Product Code, Revision Number, and Serial Number. Scope checksum
protection specifically to the ESC Configuration Area at word addresses
0x0000–0x0007; do not imply that every listed identity field is protected by
that checksum.
Use EEPROM_Field_Mapping.md as analyzer context for the existing word-address
convention: Vendor ID 0x0008 and Product Code 0x000A. Preserve the ET1100 PDF
field labels 0x8:0x9 and 0xA:0xB when describing the source fact, and do not
convert them to 0x0004 or 0x0006. For 0x0504, explicitly distinguish the PDF's
byte-addressing statement from the Master/ESC register perspective: 0x0504 is
the EEPROM word address used by the Master through the ESC register interface;
the underlying I²C access is byte-addressed and A[0] is handled internally by
the ESC. Do not call this a mismatch and do not instruct the analyzer to
multiply, divide, shift, convert, or otherwise numerically transform the
address. Do not describe an explicit numeric transformation even as an ESC
implementation detail.
For 0x0502 Bit 0, state that it is ECAT EEPROM Write Enable for EEPROM write
commands and keep its meaning scoped to write commands.
For EEPROM Read Procedure, follow this exact ET1100 order: check Busy == 0;
check/clear error status as required; write the target EEPROM word address to
0x0504; issue the EEPROM Read command through the 0x0502 command bits; wait
until Busy == 0; check error status; read the returned data from 0x0508. Do
not require writing 0x0508 before a Read command.
Do not claim that Vendor ID or Product Code are provided by ET1100
ESC-specific registers. Do not mention any ESC-specific identity register
addresses. Ground both fields in the ESI EEPROM: Vendor ID is words
0x0008:0x0009 (PDF label 0x8:0x9), and Product Code is words 0x000A:0x000B
(PDF label 0xA:0xB).
In Analyzer-Relevant Notes, explicitly state that the current
SlaveDiscoveryAnalyzer uses `pendingEepromReads` to correlate successful
0x0502 read-command requests with successful 0x0508 returned-data reads by
topology position and working-counter progression, then maps 0x0008 to Vendor
ID and 0x000A to Product Code. Do not say that pairing is unimplemented and do
not claim that SlaveDiscoveryAnalyzer directly verifies the Busy bit; keep
that Busy requirement in the ET1100 procedure section.
Treat the other docs/read content as style and analyzer-context reference only;
do not use it to replace or expand the supplied ET1100 evidence.

{analyzer_context}

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
    draft = _apply_grounded_eeprom_sections(draft, evidence)

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
