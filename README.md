# EtherCAT Analyzer Agent

EtherCAT Analyzer Agent is a Windows, terminal-first engineering assistant for investigating EtherCAT Analyzer behavior. It combines deterministic retrieval from EtherCAT Analyzer C# source, the local ET1100 specification, and packet-capture JSON with Qwen-assisted routing and explanation.

The repository contains the agent/orchestration layer. It does not contain or modify the external EtherCATAnalyzer DLL project. External C# source, `docs/read` knowledge, and capture files are read from the paths configured in `core/config.py`.

## Entry point and architecture

`main.py` remains the CLI entrypoint and reads `task.md` or interactive commands, then writes results to `result.md`. `agent/graph.py` preserves the existing LangGraph routing between normal analysis, documentation generation, result checking, and the bounded engineering tool agent.

The runtime is organized by function:

- `agent/`: routing, analysis prompting, and the bounded Qwen tool-agent workflow;
- `core/`: shared configuration, state shape, LLM client, and external context loading;
- `retrieval/`: deterministic source, reference-document, ET1100 PDF, and raw-capture retrieval;
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

The allowed deterministic tools are `search_source(query)`, `search_spec(query)`, and `find_first_coe_sdo()`. The parser rejects unsupported actions, tools, and argument shapes. `MAX_TOOL_CALLS` is `3`; fresh deterministic calls consume the limit, equivalent cached calls are reused, and the agent is forced to finish after the limit. `MAX_AGENT_TURNS` remains `6` as a separate turn guard.

Tool output is evidence, not permission to invent details. Answers should distinguish implementation behavior, specification facts, capture observations, and inference.

## Retrieval roles

- `retrieval/source_retrieval.py` discovers and searches external EtherCAT Analyzer C# source files; `retrieval/source.py` integrates source selection into the graph.
- `retrieval/pdf_spec.py` extracts and searches the local ET1100 PDF; `retrieval/spec_retrieval.py` provides query planning and page selection helpers.
- `retrieval/raw_capture.py` reads TShark-derived JSON; `retrieval/capture.py` performs deterministic capture pairing and query modes.
- `retrieval/docs.py` indexes and loads Markdown from the external shared `docs/read` knowledge base.

## Local specification layout

```text
spec/
├── README.md
├── original/
│   └── ET1100/
│       └── ET1100_v2.5_2025-07-28.pdf
└── generated/
    └── ET1100/
        ├── manifest.json
        └── pages/
            ├── page_001.md
            └── ...
```

The current local ET1100 source is Beckhoff EtherCAT Slave Controller documentation, version 2.5, dated 2025-07-28. The original PDF is a local ignored asset. `spec/generated/` is reserved for raw specification-derived Markdown and manifests and is also ignored. Curated engineering knowledge belongs in the shared external EtherCATAnalyzer `docs/read` knowledge base; neither raw PDF content nor raw generated Markdown is that curated knowledge.

The first deterministic ingestion workflow is `workflows/spec_ingestion.py`. Run it from the CLI with:

```text
/ingest-spec ET1100
```

It requires exactly one PDF in `spec/original/ET1100/` and writes `manifest.json` plus `pages/page_001.md`, `pages/page_002.md`, and so on under `spec/generated/ET1100/`. The page files preserve extracted text and are raw evidence, not summaries or curated engineering notes. Generated Markdown and manifests are ignored by Git.

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
```

The existing ET1100 retrieval path resolves the single PDF in `spec/original/ET1100/`; no machine-specific absolute ET1100 PDF path is used. The external DLL project is not changed by this repository.

## Limitations and safety

- The agent depends on external source, shared knowledge, capture, and local proxy paths configured for the Windows environment.
- LLM-backed routes require the local Hermes/Qwen proxy.
- The original PDF, raw generated Markdown, and generated manifests are intentionally untracked local assets.
- There is no package installer or dependency lockfile in this repository.
- Follow [`AGENTS.md`](AGENTS.md): keep changes narrow, do not modify the external DLL project unless explicitly requested, and separate static inspection from runtime verification.
