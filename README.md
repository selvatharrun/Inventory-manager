# 📦 Inventory Optimization AI Agent

> **Advisory-only, local-first AI decision-support tool for inventory planners.**  
> Reads your inventory data, computes health metrics, enriches decisions with a runtime knowledge graph, and produces plain-English recommendations — all on your own machine with no cloud required.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Architecture](#architecture)
4. [Project Structure](#project-structure)
5. [Prerequisites](#prerequisites)
6. [Installation & Setup](#installation--setup)
7. [Configuration](#configuration)
8. [Usage](#usage)
   - [CLI (`main.py`)](#cli-mainpy)
   - [Streamlit UI (`app.py`)](#streamlit-ui-apppy)
9. [Execution Modes](#execution-modes)
10. [CLI Flag Reference](#cli-flag-reference)
11. [Output Schema](#output-schema)
12. [Data Format](#data-format)
13. [Testing](#testing)
14. [Development Notes](#development-notes)
15. [Roadmap](#roadmap)
16. [License](#license)
17. [Disclaimer](#disclaimer)

---

## Overview

Inventory teams often rely on manual spreadsheet reviews to make reorder decisions, leading to:

- **Stockouts** from delayed reorder action on high-velocity SKUs.
- **Overstocking** from weak visibility on low-velocity or seasonal demand patterns.

The **Inventory Optimization AI Agent** is a local, offline-capable decision-support co-pilot that:

1. Ingests inventory data from a **CSV or JSON** file.
2. Computes per-SKU health metrics (days of stock, reorder quantity, urgency).
3. Optionally enriches decisions with a **runtime NetworkX knowledge graph** built from your data.
4. Generates prioritized recommendations via **deterministic rules** and/or an **agentic LangGraph planner**.
5. Produces **explainable, plain-English outputs** with mandatory advisory disclaimers.

> ⚠️ This tool is **advisory only**. It never places orders or modifies any external system. All recommendations require human review.

---

## Key Features

| Feature | Description |
|---|---|
| **Local-first** | Runs entirely on your machine; LLM calls go to a local Ollama endpoint |
| **Multiple execution modes** | `fast` (deterministic only) or `thinking` (graph-enriched, agentic) |
| **LangGraph orchestration** | Stateful, mode-aware graph with conditional routing |
| **MCP tool layer** | FastMCP-powered tools for data loading, metric calculation, graph querying, and rule fetching |
| **Runtime knowledge graph** | NetworkX graph built from uploaded records; captures category/supplier relationships |
| **In-memory cache** | Graph artifact reuse by dataset fingerprint to avoid repeated builds |
| **Guardrails** | Post-validation of LLM-generated recommendations against deterministic policy |
| **Streamlit UI** | Full web UI with live trace, diagnostics, and CSV export |
| **CLI entrypoint** | Scriptable `main.py` with rich flag set for automation |
| **Structured observability** | `flow_events`, `tool_call_logs`, `llm_batch_events` in every run output |

---

## Architecture

### High-Level Stack

```
┌─────────────────────────────────────────────┐
│                   UI Layer                  │
│  Streamlit (app.py)  │  CLI (main.py)        │
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│           Orchestration Layer               │
│  LangGraph graph  (agent/graph.py)          │
│  State contract   (agent/state.py)          │
│  Node logic       (agent/nodes/*)           │
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│             Tool Layer (MCP)                │
│  tools/server.py  (FastMCP server)          │
│  tools/load_data.py  │  tools/calc_metrics  │
│  tools/query_graph.py│  tools/fetch_rules   │
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│           Knowledge Layer                   │
│  knowledge/networkx_graph.py                │
│  knowledge/cache_layer.py (in-memory TTL)   │
└────────────────┬────────────────────────────┘
                 │
┌────────────────▼────────────────────────────┐
│              Model Layer                    │
│  Ollama  (localhost:11434)                  │
│  Default model: llama3.2:1b                 │
└─────────────────────────────────────────────┘
```

### LangGraph Execution Flows

#### Mode Router Entry Point

```
START ──► mode_router
              │
              ├─ mode=thinking & agent_mode=full  ──► planner_action
              └─ everything else                  ──► load_data
```

#### Deterministic Backbone

```
load_data ──► calculate_metrics
                    │
                    ├─ mode=fast      ──► apply_rules
                    └─ mode=thinking  ──► enrich_context ──► apply_rules
                                                               │
                                              generate_recs ◄─┘
                                                    │
                               ┌────────────────────┤
                               │  mode=fast          └─► explain_llm
                               │  agent_mode=deterministic
                               └─ hybrid/full & not done ──► planner_action
```

#### Agentic Planner Loop (hybrid / full)

```
planner_action
    │
    ├─ done=true & full-mode  ──► generate_recs
    ├─ done=true              ──► explain_llm
    └─ done=false             ──► execute_action ──► planner_action (loop)
```

#### Shared Tail

```
explain_llm ──► template_explanation ──► format_output ──► validate_output ──► END
```

### Mode Behavior Summary

| `--mode` | `--agent-mode` | Graph Enrichment | Planner Loop |
|---|---|---|---|
| `fast` | `deterministic` (forced) | ✗ | ✗ |
| `thinking` | `deterministic` | ✓ | ✗ |
| `thinking` | `hybrid` | ✓ | ✓ (partial) |
| `thinking` | `full` | ✓ | ✓ (planner-first) |

---

## Project Structure

```
Inventory-manager/
├── app.py                      # Streamlit UI entrypoint
├── main.py                     # CLI entrypoint
├── cli_helpers.py              # CLI output helpers (table, report, comparison)
├── requirements.txt
│
├── agent/                      # LangGraph orchestration
│   ├── graph.py                # Graph definition & conditional routing
│   ├── state.py                # AgentState TypedDict
│   ├── logging_utils.py
│   └── nodes/                  # One file per graph node
│       ├── load_data.py
│       ├── calculate_metrics.py
│       ├── enrich_context.py
│       ├── apply_rules.py
│       ├── generate_recs.py
│       ├── planner_action.py
│       ├── execute_action.py
│       ├── explain_llm.py
│       ├── template_explanation.py
│       ├── format_output.py
│       └── validate_output.py
│
├── tools/                      # FastMCP tool layer
│   ├── server.py               # MCP server registration
│   ├── load_data.py
│   ├── calc_metrics.py
│   ├── query_graph.py
│   ├── fetch_rules.py
│   └── cache.py
│
├── knowledge/                  # Knowledge graph & cache
│   ├── networkx_graph.py       # Runtime directed graph builder
│   └── cache_layer.py          # In-memory TTL cache
│
├── ui/                         # Streamlit UI components
│   ├── tabs.py
│   ├── sidebar.py
│   ├── preflight.py
│   ├── runner.py
│   ├── formatters.py
│   ├── styles.py
│   ├── config.py
│   └── session.py
│
├── config/
│   ├── thresholds.yaml         # Default config (llama3.2:1b)
│   └── thresholds_gemma3.yaml  # Alternative config (gemma3:4b)
│
├── data/
│   ├── inventory_mock.json     # Sample multi-SKU dataset
│   └── kg_seed.json            # Knowledge graph seed data
│
├── prompts/
│   └── system_prompt.txt       # LLM system prompt template
│
├── results/                    # Run output JSON + markdown reports
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fallback/
│   └── performance/
│
├── learning/                   # Guided learning notebooks
├── scripts/                    # Utility scripts
├── MAIN_PY_COMMANDS.md         # Quick CLI command cheat sheet
└── PRD_Inventory_Optimization_AI_Agent.md
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| [Ollama](https://ollama.com/) | Latest stable |
| Ollama model | `llama3.2:1b` (default) or `gemma3:4b` |

> **Note:** An active internet connection is **not** required at runtime. All LLM inference runs locally via Ollama.

---

## Installation & Setup

### 1. Clone the repository

```bash
git clone https://github.com/selvatharrun/Inventory-manager.git
cd Inventory-manager
```

### 2. Create and activate a virtual environment

**Linux / macOS:**
```bash
python -m venv venv
source venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Install and start Ollama

Download Ollama from [https://ollama.com/](https://ollama.com/), then pull the default model:

```bash
ollama pull llama3.2:1b
ollama serve          # starts the local API on http://localhost:11434
```

To use `gemma3:4b` instead:

```bash
ollama pull gemma3:4b
```

---

## Configuration

The main configuration file is `config/thresholds.yaml`:

```yaml
thresholds:
  healthy_dos_min: 14     # Days-of-stock lower bound for "healthy" status
  watch_dos_min: 7        # Days-of-stock lower bound for "watch" status
  critical_dos_max: 7     # Days-of-stock ceiling for "critical" status
  overstock_dos_min: 60   # Days-of-stock lower bound for "overstock" status

defaults:
  safety_stock: 0
  lead_time_days: 7

cache:
  ttl_graph_seconds: 86400   # 24 h
  ttl_rules_seconds: 3600    # 1 h
  ttl_metrics_seconds: 1800  # 30 min
  max_size_mb: 500

ollama:
  base_url: "http://localhost:11434"
  model: "llama3.2:1b"
  temperature: 0.1

agent:
  mode: "deterministic"   # deterministic | hybrid | full
  max_steps: 3
```

A second config file, `config/thresholds_gemma3.yaml`, targets `gemma3:4b` and is useful for single-SKU testing.

### Runtime scenario overrides

Any threshold key can be overridden at run time using `--scenario`:

```bash
python main.py --scenario lead_time=10 --scenario safety_stock=25
```

When overrides are provided, the CLI runs both the **baseline** and **override** scenarios and prints a side-by-side comparison.

---

## Usage

### CLI (`main.py`)

```bash
# Default run — uses data/inventory_mock.csv, fast mode, table output
python main.py

# Use a specific CSV or JSON file
python main.py --data data/inventory_mock.json

# Output as JSON instead of a table
python main.py --format json

# Save output to a specific file (default: results/<run_id>.json)
python main.py --output results/my_run.json

# Disable automatic markdown report generation
python main.py --no-report

# Thinking mode with hybrid planner
python main.py --mode thinking --agent-mode hybrid

# Full agentic mode with a custom model
python main.py --mode thinking --agent-mode full --model gemma3:4b

# Analyze a single SKU
python main.py --sku SKU-001 --format json

# Analyze a subset of SKUs
python main.py --skus SKU-001,SKU-003,SKU-005

# Scenario stress-test
python main.py --data data/inventory_mock.csv \
               --agent-mode full \
               --scenario lead_time=14 \
               --scenario safety_stock=40 \
               --format json

# Show all options
python main.py -h
```

### Streamlit UI (`app.py`)

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501`. The UI provides:

- **Sidebar** — upload your own CSV/JSON, choose mode and agent mode, set model/config overrides.
- **Run tab** — trigger analysis and watch the live trace.
- **Results tab** — sortable SKU recommendation table with status badges.
- **Diagnostics tab** — full `flow_events`, `tool_call_logs`, and `llm_batch_events` viewer.
- **Raw output tab** — full JSON payload for copy/download.

---

## Execution Modes

### Top-level mode (`--mode`)

| Value | Description |
|---|---|
| `fast` | Deterministic only. Skips knowledge graph enrichment and forces `agent_mode=deterministic`. Fastest path. |
| `thinking` | Enables the runtime NetworkX knowledge graph for category-aware context enrichment. Supports all agent modes. |

### Agent mode (`--agent-mode`, only effective in `thinking` mode)

| Value | Description |
|---|---|
| `deterministic` | Follows the fixed node sequence. No planner loop. |
| `hybrid` | Runs the deterministic backbone and inserts the planner loop at the `generate_recs → planner_action` transition when applicable. |
| `full` | Starts with the planner and routes through `planner_action → execute_action` loop before entering the deterministic explanation tail. Includes strict full-mode contract checks. |

### Fast template-only mode

```bash
python main.py --fast-template-only
```

In `fast` mode, skips the LLM entirely and uses template-generated explanations. Useful for quick smoke tests with no Ollama dependency.

---

## CLI Flag Reference

| Flag | Default | Description |
|---|---|---|
| `--data` | `data/inventory_mock.csv` | Path to CSV or JSON inventory file |
| `--config` | `config/thresholds.yaml` | Path to YAML configuration file |
| `--output` | `results/<run_id>.json` | Output JSON file path |
| `--format` | `table` | Console output format: `table` or `json` |
| `--mode` | `fast` | Top-level mode: `fast` or `thinking` |
| `--agent-mode` | `deterministic` | Agent mode: `deterministic`, `hybrid`, or `full` |
| `--model` | _(config value)_ | Override Ollama model name |
| `--scenario KEY=VAL` | — | Override a config threshold (repeatable) |
| `--sku` | — | Analyze a single SKU ID |
| `--skus` | — | Comma-separated list of SKU IDs to analyze |
| `--no-report` | `false` | Disable markdown report file generation |
| `--fast-template-only` | `false` | Skip LLM in fast mode; use template explanations only |

---

## Output Schema

Each run produces a structured JSON payload saved to `results/` and optionally printed to stdout.

### Top-level keys

```json
{
  "run_id": "<uuid>",
  "generated_at": "<ISO 8601 timestamp>",
  "summary": { ... },
  "recommendations": [ ... ],
  "metadata": { ... },
  "disclaimer": "..."
}
```

### `summary`

| Field | Type | Description |
|---|---|---|
| `total_skus_analyzed` | int | Number of SKUs processed |
| `critical_count` | int | SKUs with critical stock status |
| `watch_count` | int | SKUs in watch zone |
| `healthy_count` | int | SKUs in healthy range |
| `overstock_count` | int | SKUs flagged as overstock |
| `skus_skipped` | int | Rows skipped due to validation errors |
| `overall_health` | string | Aggregate health label |
| `top_priority_skus` | list | Ordered list of highest-urgency SKU IDs |

### Per-recommendation fields

| Field | Description |
|---|---|
| `sku_id` / `name` / `category` | SKU identifiers |
| `status` | `healthy` / `watch` / `critical` / `overstock` |
| `status_emoji` | Visual status indicator |
| `days_of_stock` | Estimated days until stockout |
| `reorder_qty` | Recommended reorder quantity |
| `reorder_urgency_days` | Days until reorder must be placed |
| `recommended_action` | Action label (e.g. `reorder_now`, `monitor`) |
| `plain_english_explanation` | LLM-generated or template explanation |
| `reasoning_summary` | Condensed rationale |
| `confidence` | Confidence score (0–1) |
| `risk_tags` | List of risk signals (e.g. `low_stock`, `high_velocity`) |
| `seasonal_factor` | Demand seasonality signal |
| `category_avg_dos` | Category baseline days-of-stock (thinking mode) |
| `context_source` | `runtime_graph` or `default` |
| `velocity_trend` | Recent vs. baseline sales comparison |
| `raw_cot` | _(experimental, optional)_ Raw chain-of-thought from LLM |

### `metadata`

| Field | Description |
|---|---|
| `mode` / `agent_mode` | Execution mode used |
| `llm_model` | Ollama model name |
| `graph_source` | `runtime_graph` or `default` |
| `graph_runtime_stats` | Node/edge counts, build time |
| `flow_events` | Ordered list of node execution events |
| `tool_call_logs` | MCP tool invocation log |
| `llm_batch_events` | Per-SKU LLM call events |
| `agent_fallback_reason` | Why the planner stopped early (if applicable) |
| `full_mode_contract_ok` | Whether full-mode contract checks passed |
| `errors` / `warnings` | Structured error and warning list |

---

## Data Format

The agent accepts **CSV** or **JSON** inventory files. Each row/record represents one SKU.

### Required fields

| Field | Type | Description |
|---|---|---|
| `sku_id` | string | Unique SKU identifier |
| `name` | string | Human-readable SKU name |
| `category` | string | Product category |
| `current_stock` | number | Units currently on hand |
| `avg_daily_sales` | number | Average daily sales velocity |
| `lead_time_days` | number | Supplier lead time in days |
| `safety_stock` | number | Safety stock buffer in units |

### Optional fields

| Field | Description |
|---|---|
| `avg_daily_sales_7d` | 7-day rolling average (used for velocity trend) |
| `avg_daily_sales_30d` | 30-day rolling average |
| `supplier` | Supplier name (used as graph node if provided) |

### CSV example

```csv
sku_id,name,category,current_stock,avg_daily_sales,lead_time_days,safety_stock
SKU-001,USB-C Cable 2m,electronics,420,12,7,40
SKU-002,Wireless Mouse,electronics,95,11,6,25
```

### JSON example

```json
[
  {
    "sku_id": "SKU-001",
    "name": "USB-C Cable 2m",
    "category": "electronics",
    "current_stock": 420,
    "avg_daily_sales": 12,
    "lead_time_days": 7,
    "safety_stock": 40
  }
]
```

---

## Testing

Run the full test suite:

```bash
pytest tests/ -q
```

### Test layout

| Directory | Coverage focus |
|---|---|
| `tests/unit/` | Metric calculations, status assignment, tool contract behaviour |
| `tests/integration/` | End-to-end deterministic and agentic route execution, full-mode contract checks |
| `tests/fallback/` | Graceful degradation when LLM or graph is unavailable |
| `tests/performance/` | Latency profiling by mode and dataset size |

---

## Development Notes

### Learning notebooks

The `learning/` directory contains guided Jupyter notebooks for exploring MCP tools and the LangGraph agent step-by-step:

```bash
pip install jupyter ipykernel
python -m jupyter lab
```

- `learning/01_mcp_tool_testing.ipynb` — test each tool in isolation, measure latency.
- `learning/02_langgraph_agent_testing.ipynb` — end-to-end graph runs, fallback validation.

### Debugging a run

1. Check `payload["metadata"]["errors"]` and `payload["metadata"]["warnings"]`.
2. Inspect `flow_events` for the sequence of node executions.
3. Inspect `tool_call_logs` for MCP tool invocation details.
4. Use `scripts/debug_ollama_response.py` to validate raw Ollama responses in isolation.

### Adding a new node

1. Create `agent/nodes/<your_node>.py` and implement a function `your_node(state: AgentState) -> AgentState`.
2. Register it in `agent/graph.py` with `graph_builder.add_node(...)`.
3. Wire the appropriate edges or conditional edges.

### Adding a new MCP tool

1. Implement the tool function in `tools/`.
2. Register it in `tools/server.py` using the `@mcp.tool()` decorator.
3. Map the tool's output back into state in `agent/nodes/execute_action.py` if needed for the planner path.

---

## Roadmap

| Priority | Item |
|---|---|
| High | Expand graph-derived risk features (subcategory, supplier risk signals) |
| High | Improve planner model compatibility profiles (smaller / quantised models) |
| Medium | Stronger regression matrix for action-policy correctness |
| Medium | Per-SKU on-demand raw CoT capture with redaction controls |
| Low | Benchmark framework for latency/quality tradeoff by mode and model |
| Future | ERP/WMS integration hooks (post-MVP) |
| Future | Real-time POS ingestion pipeline |

---

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file in the repository root.

---

## Disclaimer

> ⚠️ **ADVISORY ONLY:** This analysis is generated by an AI decision-support tool using synthetic mock data. All recommendations require human review and validation before any action is taken. This tool does not place orders, modify systems, or reflect real commercial inventory. Always consult your supply chain team before acting on these suggestions.