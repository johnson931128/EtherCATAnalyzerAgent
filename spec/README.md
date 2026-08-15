# Specification staging

- `original/` contains local original specification files.
- `generated/` contains raw generated Markdown derived from specifications.

Both directories may be used locally by the Agent. Original PDFs, raw generated Markdown, and generated manifests are intentionally excluded from Git; the directory placeholders and this metadata file remain tracked.

The supported ingestion command is `/ingest-spec ET1100`. It resolves the single PDF in `original/ET1100/` and uses Docling to write one readable `ET1100.md` plus `manifest.json` under `generated/ET1100/`. It disables OCR for the PDF text layer, disables layout-model compilation, and does not call an LLM. If `DOCLING_ARTIFACTS_PATH` is set, its local model directory is passed to Docling; otherwise Docling uses its default model resolution behavior.

Curated engineering knowledge belongs in the shared EtherCATAnalyzer `docs/read` knowledge base rather than in this staging area.

Current ET1100 source:

- Vendor: Beckhoff
- Document: EtherCAT Slave Controller documentation
- Version: 2.5
- Date: 2025-07-28
- Local expected path: `spec/original/ET1100/ET1100_2025.pdf`
