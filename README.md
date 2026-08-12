# EtherCAT Analyzer Agent

EtherCAT Analyzer Agent is a Windows, terminal-first engineering assistant for investigating EtherCAT Analyzer behavior. It combines deterministic retrieval from EtherCAT Analyzer C# source, ET1100 specification text, and packet-capture JSON with Qwen-assisted routing and explanation.

The repository contains the agent/orchestration layer only. It does not contain the EtherCATAnalyzer DLL project and does not build or modify that DLL. The agent reads selected C# files from the external project configured in `config.py` so that implementation behavior can be compared with specification facts and observed captures.

## Architecture

`main.py` provides the persistent CLI and writes task results to the repository `result.md`. `graph.py` routes work through the LangGraph workflow:

- normal analysis loads `AGENTS.md`, indexes/selects external `docs/read` Markdown, selects relevant C# source, selects a capture query mode, and asks the analysis model for an answer;
- documentation requests use the ET1100 evidence and Markdown-generation path in `build_docs.py`;
- result-check requests compare a reported Stage 3 result with deterministic capture-derived evidence;
- direct tool-agent requests use `engineering_tool_agent.py`, a bounded Qwen engineering workflow.

The main runtime Python modules intentionally remain at the repository root because their imports and the current CLI entrypoint depend on that layout.

## Bounded Qwen engineering tool agent

The tool agent is designed as a read-only evidence workflow. Qwen may request only these deterministic tools:

- `search_source(query)` searches external EtherCAT Analyzer C# files and returns compact matches;
- `search_spec(query)` searches the configured ET1100 PDF and returns ranked page excerpts;
- `find_first_coe_sdo()` returns the first matching CoE SDO packet from the configured raw capture, without arguments.

The tools retrieve evidence; they do not grant permission to invent details. Final answers are expected to distinguish source behavior, specification facts, capture observations, and inference.

### Structured tool-call protocol

Each Qwen response must be one JSON object. A tool request has this shape:

```json
{"action":"tool","tool":"search_source","arguments":{"query":"SlaveDiscoveryAnalyzer"}}
```

A final response has this shape:

```json
{"action":"final","answer":"Concise engineering answer."}
```

The parser accepts only `tool` or `final` actions. Tool calls must use an allowed tool name and a JSON object of arguments. Source/spec queries require exactly one non-empty `query` string, limited to 200 characters; the raw-capture tool requires an empty argument object.

`MAX_TOOL_CALLS` is currently `3`. It counts fresh deterministic tool executions, while an equivalent cached request is reused and does not consume another call. Once the limit is reached, the agent is instructed to return a final answer and performs the final Qwen response step without requesting another tool. The separate turn guard is `MAX_AGENT_TURNS = 6`.

## Evidence roles

- **Source retrieval** explains what the EtherCAT Analyzer implementation actually does. `source_retrieval.py` discovers C# files below the configured project root and ignores `.git`, `bin`, and `obj` directories.
- **Specification retrieval** provides ET1100 protocol and register facts from the PDF configured by `ET1100_SPEC_PATH`. `pdf_spec.py` performs deterministic page extraction/search; `spec_retrieval.py` supplies Qwen-assisted query planning or page selection for CLI commands.
- **Raw-capture retrieval** provides observations from TShark-derived JSON. `raw_capture.py` parses packet layers and extracts CoE SDO or paired datagram evidence without asking Qwen to reconstruct packet pairs.
- **Reference-document retrieval** reads Markdown below the external `DOCS_READ_PATH`. These documents provide project-specific protocol context and style references; they are separate from the original specification staging area in this repository.

## CLI

Start the agent from the repository root with:

```powershell
.\run.ps1
```

The current script expects the following layout:

1. a Python interpreter at `..\.venv\Scripts\python.exe` relative to this repository;
2. `..\HermesProxy.py` relative to this repository;
3. a healthy local proxy at `http://127.0.0.1:5000/health`.

After startup, `main.py` provides `/help`, `/read task.md`, `/source`, `/source-ai`, `/spec`, `/spec-ai`, `/spec-plan`, `/raw-coe-sdo`, and `/exit`. Plain text is sent through the bounded tool-agent route. The CLI writes normal task output to `result.md`; the input task remains `task.md`.

## Configuration and important paths

Edit `config.py` for machine-specific external data locations. The current defaults are:

- `PROJECT_ROOT`: `D:\EtherCATAnalyzer\EtherCATAnalyzer_net472`, the external EtherCAT Analyzer source/project root;
- `AGENTS_PATH`: the external project `AGENTS.md` used as analysis context;
- `DOCS_READ_PATH`: the external project `docs\read` reference Markdown directory;
- `CAPTURE_PATH`: `D:\EtherCATAnalyzer\Data\Json\ethercat-datagrams.json`;
- `RAW_TSHARK_PATH`: `D:\EtherCATAnalyzer\Data\Json\output.json`;
- `ET1100_SPEC_PATH`: `D:\DATA\SPEC\EtherCAT_ET1100_Datasheet_all_v1i8.pdf`;
- `SOURCE_FILES`: specific external C# files used by the ET1100 documentation path.

`run.ps1` is kept at the repository root because it launches `main.py` from `$PSScriptRoot`. `scripts/clean.ps1` is a maintenance helper for leftover proxy/agent processes; its process matching rules still use the existing hard-coded legacy paths.

## Repository structure

```text
.
├── README.md
├── AGENTS.md
├── run.ps1
├── main.py
├── graph.py
├── engineering_tool_agent.py
├── config.py
├── analysis.py / capture.py / context.py / docs.py
├── source.py / source_retrieval.py
├── pdf_spec.py / spec_retrieval.py / raw_capture.py
├── build_docs.py / result_check.py / state.py / llm.py
├── task.md
├── result.md
├── tests/
│   ├── test_build_docs.py
│   ├── test_llm.py
│   └── test_routing.py
├── scripts/
│   └── clean.ps1
└── spec/
    └── original/
        └── .gitkeep
```

`spec/original/` is reserved for original specification source files that are intentionally added later. It is empty in this cleanup. No specification was downloaded, and no Markdown was generated from a PDF.

## Environment and setup

This project assumes Windows PowerShell, Python, and an existing virtual environment with the imported runtime dependencies, including LangGraph, LangChain OpenAI integration, and PyMuPDF. There is currently no dependency lockfile or installer manifest in this repository. The local Qwen-compatible proxy is required for model-backed routes; deterministic source/spec/capture helper functions still depend on the external paths in `config.py`.

Keep the repository and its external EtherCAT Analyzer/DLL checkout available at the configured paths, then use `run.ps1` as the supported entrypoint. This cleanup does not install packages, change environment settings, or alter the external DLL project.

## Current limitations

- The agent depends on hard-coded Windows paths and external source, reference-document, capture, and PDF inputs.
- The ET1100 original specification is not stored in this repository yet.
- The LLM-backed routes require the local `HermesProxy.py` service and its Qwen model configuration.
- The general analysis and documentation workflows can write `result.md` or external documentation; the read-only guarantee applies to the bounded engineering tool set, not every workflow in the repository.
- The repository has no packaged installation flow or dependency manifest.
- `scripts/clean.ps1` contains legacy absolute process-path filters and may need environment-specific adjustment before use.

## Development safety

Follow [`AGENTS.md`](AGENTS.md) before making changes. Keep edits narrow, preserve the CLI and runtime behavior, do not modify the EtherCATAnalyzer DLL project unless explicitly requested, and separate static/source inspection from runtime verification. The repository cleanup in this change intentionally does not run `run.ps1`, `main.py`, `HermesProxy.py`, Qwen/LLM calls, tests, builds, or other runtime checks.
