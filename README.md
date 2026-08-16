# EtherCAT Analyzer Agent

EtherCAT Analyzer Agent is a Windows, terminal-first engineering assistant for investigating EtherCAT Analyzer behavior. It combines deterministic retrieval from EtherCAT Analyzer C# source, the local ET1100 specification, and packet-capture JSON with Qwen-assisted routing and explanation.

The repository contains the agent/orchestration layer. It does not contain or modify the external EtherCATAnalyzer DLL project. External C# source, `docs/read` knowledge, and capture files are read from the paths configured in `core/config.py`.

## Entry point and architecture

`main.py` remains the CLI entrypoint and reads `task.md` or interactive commands, then writes results to `result.md`. `agent/graph.py` preserves the existing LangGraph routing between normal analysis, documentation generation, result checking, and the bounded engineering tool agent.

The runtime is organized by function:

- `agent/`: routing, analysis prompting, and the bounded Qwen tool-agent workflow;
- `core/`: shared configuration, state shape, LLM client, and external context loading;
- `retrieval/`: deterministic source, generated ET1100 Markdown, raw ET1100 PDF, reference-document, and raw-capture retrieval;
- `workflows/`: ET1100 documentation generation, deterministic PDF ingestion, and Stage 3 result checking;
- `tests/`: existing unit-test sources;
- `scripts/`: maintenance PowerShell scripts;
- `spec/`: local specification staging and its documentation.

## Bounded engineering tool agent

`agent/engineering_tool_agent.py` accepts only structured JSON actions from Qwen. Tool requests use:

```json
{"action":"tool","tool":"search_source","arguments":{"query":"SlaveDiscoveryAnalyzer"}}
```

Final responses use:

```json
{"action":"final","answer":"Concise engineering answer."}
```

The allowed deterministic tools are `search_source(query)`, `search_spec(query)`,
`search_spec_raw(spec, query, limit)`, `get_spec_raw_pages(spec, pages)`, and
`query_capture(capture, display_filter, fields, limit)`,
`export_frame_json(capture, frame_number)`, and `find_first_coe_sdo()`. The parser rejects unsupported actions, tools, unknown
arguments, and invalid argument types. `MAX_TOOL_CALLS` is `3`; fresh deterministic
calls consume the limit, equivalent cached calls are reused, and the agent is forced
to finish after the limit. `MAX_AGENT_TURNS` remains `6` as a separate turn guard.

Capture queries follow this bounded flow:

```text
Natural language -> Qwen -> structured capture tool -> Python validation -> TShark -> structured evidence
```

Qwen cannot provide arbitrary shell, PowerShell, Python, or TShark command strings.
`query_capture` performs bounded candidate-frame discovery using an allowlisted field
set. `export_frame_json` retrieves one frame with the canonical TShark protocol tree
(`frame`, `eth`, `ecat`, and `ecat_mailbox`).

`ET1100.md` is the primary readable specification source. The raw PDF tools are
fallback/verification evidence only: use them for Docling markers such as
`<!-- image -->` or `<!-- formula-not-decoded -->`, suspicious Markdown tables,
questionable register addresses or bit values, or an explicit request for original
PDF page evidence. Qwen may provide only the controlled `spec` value `ET1100`; it
cannot provide a PDF path or execute Python, shell commands, or arbitrary tools.

Raw tool requests use the following bounded JSON shapes:

```json
{"action":"tool","tool":"search_spec_raw","arguments":{"spec":"ET1100","query":"FMMU logical start bit","limit":5}}
{"action":"tool","tool":"get_spec_raw_pages","arguments":{"spec":"ET1100","pages":[67,68]}}
```

Search `limit` is 1-10 (default 5 for the Python operation); page reads accept at
most 5 unique positive physical page numbers and preserve the requested order.

Tool output is evidence, not permission to invent details. Answers should distinguish implementation behavior, specification facts, capture observations, and inference.

## Retrieval roles

- `retrieval/source_retrieval.py` discovers and searches external EtherCAT Analyzer C# source files; `retrieval/source.py` integrates source selection into the graph.
- `retrieval/markdown_spec.py` loads and searches the generated ET1100 Markdown
  with heading-aware deterministic chunks for primary `search_spec()` evidence.
- `retrieval/tshark_capture.py` resolves repository-local capture filenames and
  provides the bounded `query_capture` and `export_frame_json` primitives.
- `retrieval/pdf_spec.py` extracts and searches the local ET1100 PDF; its
  `search_spec_raw` and `get_spec_raw_pages` operations resolve exactly one PDF
  from `spec/original/<SPEC>/` and never read generated `ET1100.md`.
- `retrieval/spec_retrieval.py` provides query planning and page selection helpers.
- `retrieval/raw_capture.py` reads TShark-derived JSON; `retrieval/capture.py` performs deterministic capture pairing and query modes.
- `retrieval/docs.py` indexes and loads Markdown from the external shared `docs/read` knowledge base.

## Local specification layout

```text
spec/
├── README.md
├── original/
│   └── ET1100/
│       └── ET1100_2025.pdf
└── generated/
    └── ET1100/
        ├── ET1100.md
        └── manifest.json
```

The current local ET1100 source is Beckhoff EtherCAT Slave Controller documentation, version 2.5, dated 2025-07-28. The original PDF is a local ignored asset. `spec/generated/` is reserved for raw specification-derived Markdown and manifests and is also ignored. Curated engineering knowledge belongs in the shared external EtherCATAnalyzer `docs/read` knowledge base; neither raw PDF content nor raw generated Markdown is that curated knowledge.

Capture inputs are logical filenames resolved only below the repository-relative
`captures/` directory. Only `.pcap` and `.pcapng` files are accepted. Production
captures, exported packet JSON, and temporary capture files remain ignored and are
never part of the repository commit.

The specification retrieval flow is:

```text
ET1100 PDF
  -> /ingest-spec ET1100 (Docling)
  -> spec/generated/ET1100/ET1100.md
  -> search_spec(query)
  -> primary readable specification evidence
```

`retrieval/markdown_spec.py` reads `spec/generated/ET1100/ET1100.md` as UTF-8 and
performs heading-aware deterministic chunking and ranking. If `ET1100.md` is
missing, `search_spec()` reports that you must first run `/ingest-spec ET1100`;
it never starts Docling or converts the PDF automatically.

The first deterministic ingestion workflow is `workflows/spec_ingestion.py`. Run it from the CLI with:

```text
/ingest-spec ET1100
```

It requires exactly one PDF in `spec/original/ET1100/` and uses Docling to write one readable `ET1100.md` plus `manifest.json` under `spec/generated/ET1100/`. Docling preserves document headings, paragraphs, lists, tables, and reading order without LLM cleanup. Generated Markdown and manifests are ignored by Git.

For fallback evidence, `search_spec_raw()` and `get_spec_raw_pages()` read the
controlled original PDF directly through PyMuPDF. They do not replace the primary
Markdown retrieval and are not automatically invoked when `ET1100.md` is missing.

## Python dependency

This repository does not currently use a package manager or dependency lockfile. The runtime environment must provide `docling` in addition to the existing project dependencies. Docling model artifacts use its default resolution behavior unless `DOCLING_ARTIFACTS_PATH` points to a local pre-downloaded artifacts directory.

## CLI usage

Start from the repository root with:

```powershell
.\run.ps1
```

The current CLI commands are `/help`, `/read task.md`, `/source`, `/source-ai`, `/spec`, `/spec-ai`, `/spec-plan`, `/ingest-spec ET1100`, `/raw-coe-sdo`, and `/exit`. Plain text uses the bounded tool-agent route. `run.ps1` expects the existing local Python environment, `HermesProxy.py`, and a healthy proxy at `http://127.0.0.1:5000/health`.

## Configuration

`core/config.py` keeps the existing external paths for the EtherCAT Analyzer project, shared `docs/read`, and capture JSON. Specification paths are repository-relative directory constants:

```text
SPEC_ROOT            = spec/
SPEC_ORIGINAL_ROOT   = spec/original/
SPEC_GENERATED_ROOT  = spec/generated/
CAPTURE_INPUT_ROOT   = captures/
```

The primary ET1100 retrieval path reads `spec/generated/ET1100/ET1100.md`. Raw
fallback retrieval resolves exactly one PDF in `spec/original/ET1100/`; no
machine-specific absolute ET1100 PDF path is used. The external DLL project is not
changed by this repository.

`TSHARK_EXECUTABLE` may configure the TShark executable name or path; otherwise the
bounded subprocess invocation uses `tshark`. The invocation always uses an argument
list with `shell=False`. TShark display filters are length-limited, non-empty, and
cannot contain NUL or newline characters; TShark itself validates filter syntax.

`query_capture` returns raw frame-level field rows only. A frame may contain multiple
EtherCAT datagrams, so its columns must not be interpreted as one semantic datagram
record or used to pair a datagram header with another datagram's mailbox/WKC. Use
`export_frame_json` when exact datagram association or the complete protocol tree is
needed; its JSON is preserved for the existing `EtherCAT datagram:` boundary rules.

Specification ingestion disables OCR for the text-layer ET1100 PDF and disables layout-model compilation for Windows compatibility. `DOCLING_ARTIFACTS_PATH`, when set, is passed to Docling without changing repository-relative specification input or output paths.

## Limitations and safety

- The agent depends on external source, shared knowledge, capture, and local proxy paths configured for the Windows environment.
- LLM-backed routes require the local Hermes/Qwen proxy.
- The original PDF, raw generated Markdown, and generated manifests are intentionally untracked local assets.
- There is no package installer or dependency lockfile in this repository.
- Follow [`AGENTS.md`](AGENTS.md): keep changes narrow, do not modify the external DLL project unless explicitly requested, and separate static inspection from runtime verification.
