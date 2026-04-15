"""Polished Streamlit UI for Inventory Optimization AI Agent."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx
import pandas as pd
import streamlit as st
from neo4j import GraphDatabase

from main import DISCLAIMER, run_analysis
from tools.load_data import load_threshold_config


def _get_ollama_models(base_url: str) -> Tuple[bool, List[str], str]:
    """Fetch installed Ollama models from local runtime."""
    try:
        with httpx.Client(timeout=2.5) as client:
            response = client.get(f"{base_url.rstrip('/')}/api/tags")
            response.raise_for_status()
            payload = response.json()
        models = [item.get("name", "") for item in payload.get("models", []) if item.get("name")]
        return True, models, "Ollama reachable"
    except Exception as exc:
        return False, [], f"Ollama unreachable: {exc}"


def _check_neo4j_health(cfg: Dict[str, Any], enabled: bool) -> Tuple[bool, str]:
    """Check Neo4j availability with short timeout."""
    if not enabled:
        return False, "Neo4j disabled"

    neo4j_cfg = cfg.get("neo4j", {})
    driver = None
    try:
        driver = GraphDatabase.driver(
            str(neo4j_cfg.get("uri", "bolt://localhost:7687")),
            auth=(
                str(neo4j_cfg.get("user", "neo4j")),
                str(neo4j_cfg.get("password", "inventory123")),
            ),
            connection_timeout=1.0,
        )
        driver.verify_connectivity()
        return True, "Neo4j reachable"
    except Exception as exc:
        return False, f"Neo4j unavailable: {exc}"
    finally:
        if driver is not None:
            driver.close()


def _build_config(
    base_cfg: Dict[str, Any],
    data_path: str,
    ollama_base_url: str,
    ollama_model: str,
    timeout_ms: int,
    temperature: float,
    num_predict: int,
    neo4j_enabled: bool,
    scenario_overrides: Dict[str, float],
) -> Dict[str, Any]:
    """Build run config from base + UI settings."""
    cfg = json.loads(json.dumps(base_cfg))
    cfg["data_path"] = data_path
    cfg["config_path"] = "config/thresholds.yaml"
    cfg["kg_seed_path"] = "data/kg_seed.json"

    cfg.setdefault("ollama", {})["base_url"] = ollama_base_url
    cfg.setdefault("ollama", {})["model"] = ollama_model
    cfg.setdefault("ollama", {})["timeout_ms"] = timeout_ms
    cfg.setdefault("ollama", {})["temperature"] = temperature
    cfg.setdefault("ollama", {})["num_predict"] = num_predict

    cfg.setdefault("neo4j", {})["enabled"] = neo4j_enabled
    os.environ["NEO4J_ENABLED"] = "true" if neo4j_enabled else "false"

    if scenario_overrides:
        cfg["scenario_overrides"] = scenario_overrides
    return cfg


def _payload_to_df(payload: Dict[str, Any]) -> pd.DataFrame:
    """Convert recommendations to a dataframe for filtering and display."""
    rows = payload.get("recommendations", [])
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    keep_cols = [
        "sku_id",
        "name",
        "category",
        "status",
        "status_emoji",
        "days_of_stock",
        "reorder_qty",
        "reorder_urgency_days",
        "velocity_trend",
        "seasonal_factor",
        "category_avg_dos",
        "context_source",
        "confidence",
        "recommended_action",
        "plain_english_explanation",
    ]
    ordered = [col for col in keep_cols if col in frame.columns]
    return frame[ordered]


def _render_status_panel(payload: Dict[str, Any], elapsed_ms: float | None) -> None:
    """Render summary metrics and runtime diagnostics."""
    summary = payload.get("summary", {})
    warnings = payload.get("metadata", {}).get("warnings", [])

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Critical", int(summary.get("critical_count", 0)))
    col2.metric("Watch", int(summary.get("watch_count", 0)))
    col3.metric("Healthy", int(summary.get("healthy_count", 0)))
    col4.metric("Overstock", int(summary.get("overstock_count", 0)))
    col5.metric("Runtime (ms)", int(elapsed_ms) if elapsed_ms is not None else 0)

    fallback_used = any("fallback" in str(item).lower() for item in warnings)
    if fallback_used:
        st.warning("LLM fallback used for all or part of this run. Check Diagnostics tab.")
    else:
        st.success("LLM path active: no fallback warning detected in metadata.")


def _render_recommendations(payload: Dict[str, Any]) -> None:
    """Render filterable recommendation table and cards."""
    frame = _payload_to_df(payload)
    if frame.empty:
        st.info("No recommendations available for display.")
        return

    c1, c2, c3 = st.columns(3)
    status_filter = c1.multiselect("Status", sorted(frame["status"].dropna().unique().tolist()))
    category_filter = c2.multiselect("Category", sorted(frame["category"].dropna().unique().tolist()))
    context_filter = c3.multiselect(
        "Context Source",
        sorted(frame["context_source"].dropna().unique().tolist()),
    )
    search = st.text_input("Search SKU / name", value="").strip().lower()

    filtered = frame.copy()
    if status_filter:
        filtered = filtered[filtered["status"].isin(status_filter)]
    if category_filter:
        filtered = filtered[filtered["category"].isin(category_filter)]
    if context_filter:
        filtered = filtered[filtered["context_source"].isin(context_filter)]
    if search:
        filtered = filtered[
            filtered["sku_id"].str.lower().str.contains(search)
            | filtered["name"].str.lower().str.contains(search)
        ]

    filtered = filtered.sort_values(by=["status", "reorder_urgency_days"], ascending=[True, True])
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    st.download_button(
        "Download Filtered CSV",
        data=filtered.to_csv(index=False),
        file_name=f"inventory_filtered_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    st.subheader("Top Priority SKUs")
    card_data = filtered.sort_values(by="reorder_urgency_days").head(10)
    for _, rec in card_data.iterrows():
        with st.container(border=True):
            st.markdown(f"**{rec['sku_id']} - {rec['name']}**")
            st.caption(
                f"{rec['status_emoji']} {rec['status']} | Category: {rec['category']} | "
                f"Context: {rec['context_source']} | Confidence: {rec['confidence']}"
            )
            st.write(
                f"Days of stock: {float(rec['days_of_stock']):.2f} | "
                f"Reorder qty: {float(rec['reorder_qty']):.2f} | "
                f"Urgency days: {float(rec['reorder_urgency_days']):.2f}"
            )
            st.write(f"Action: {rec['recommended_action']}")
            st.write(rec["plain_english_explanation"])


def _render_diagnostics(payload: Dict[str, Any], model_name: str) -> None:
    """Render diagnostic details for troubleshooting fallback and errors."""
    metadata = payload.get("metadata", {})
    warnings = metadata.get("warnings", [])
    errors = metadata.get("errors", [])

    st.write(f"Model configured: `{model_name}`")
    st.write(f"Graph source used: `{metadata.get('graph_source', 'unknown')}`")
    st.write(f"Partial data: `{metadata.get('partial_data', False)}`")

    if warnings:
        st.warning("Warnings")
        st.code("\n".join(str(item) for item in warnings), language="text")
    else:
        st.success("No warnings reported.")

    if errors:
        st.error("Errors")
        st.code(json.dumps(errors, indent=2, ensure_ascii=False), language="json")
    else:
        st.success("No errors reported.")


def main() -> None:
    """Run Streamlit application."""
    st.set_page_config(page_title="Inventory Optimization Agent", layout="wide")
    st.title("Inventory Optimization AI Agent")
    st.caption("Local-first decision-support workflow with hybrid graph context and batched LLM explanations.")
    st.warning(DISCLAIMER)

    base_cfg = load_threshold_config("config/thresholds.yaml")

    with st.sidebar:
        st.header("Run Configuration")

        data_mode = st.radio("Data Source", ["Upload file", "Use mock dataset"], horizontal=False)
        uploaded = None
        if data_mode == "Upload file":
            uploaded = st.file_uploader("Upload inventory CSV or JSON", type=["csv", "json"])

        llm_profile = st.radio("LLM Profile", ["Quality (recommended)", "Strict latency"], index=0)
        default_timeout = 40000 if llm_profile.startswith("Quality") else 4000
        default_predict = 1800 if llm_profile.startswith("Quality") else 900

        base_url = st.text_input("Ollama Base URL", value=base_cfg.get("ollama", {}).get("base_url", "http://localhost:11434"))
        ok, models, ollama_msg = _get_ollama_models(base_url)
        if ok:
            st.success(ollama_msg)
        else:
            st.error(ollama_msg)

        model_default = base_cfg.get("ollama", {}).get("model", "llama3.2:1b")
        if models:
            model = st.selectbox("Ollama Model", options=models, index=models.index(model_default) if model_default in models else 0)
        else:
            model = st.text_input("Ollama Model", value=model_default)

        timeout_ms = int(st.slider("LLM Timeout (ms)", min_value=4000, max_value=120000, value=default_timeout, step=1000))
        temperature = float(st.slider("Temperature", min_value=0.0, max_value=1.0, value=0.1, step=0.05))
        num_predict = int(st.slider("Max Tokens (num_predict)", min_value=400, max_value=4000, value=default_predict, step=100))

        st.header("Context Settings")
        neo4j_enabled = st.checkbox("Enable Neo4j", value=bool(base_cfg.get("neo4j", {}).get("enabled", True)))
        neo_ok, neo_msg = _check_neo4j_health(base_cfg, neo4j_enabled)
        if neo_ok:
            st.success(neo_msg)
        else:
            st.info(neo_msg)

        st.header("Scenario Overrides")
        apply_scenario = st.checkbox("Enable what-if overrides", value=False)
        lead_time_override = float(st.number_input("lead_time_days", min_value=1.0, max_value=90.0, value=7.0, step=1.0))
        safety_stock_override = float(st.number_input("safety_stock", min_value=0.0, max_value=1000.0, value=0.0, step=1.0))

        run_clicked = st.button("Run Analysis", type="primary", use_container_width=True)

    if "last_payload" not in st.session_state:
        st.session_state["last_payload"] = None
    if "last_elapsed_ms" not in st.session_state:
        st.session_state["last_elapsed_ms"] = None

    if run_clicked:
        with st.spinner("Running analysis..."):
            with tempfile.TemporaryDirectory() as temp_dir:
                if data_mode == "Upload file":
                    if uploaded is None:
                        st.error("Please upload a CSV or JSON file first.")
                        return
                    data_path = Path(temp_dir) / uploaded.name
                    data_path.write_bytes(uploaded.read())
                    effective_data_path = str(data_path)
                else:
                    effective_data_path = "data/inventory_mock.csv"

                scenario_overrides: Dict[str, float] = {}
                if apply_scenario:
                    scenario_overrides = {
                        "lead_time_days": lead_time_override,
                        "safety_stock": safety_stock_override,
                    }

                config = _build_config(
                    base_cfg=base_cfg,
                    data_path=effective_data_path,
                    ollama_base_url=base_url,
                    ollama_model=model,
                    timeout_ms=timeout_ms,
                    temperature=temperature,
                    num_predict=num_predict,
                    neo4j_enabled=neo4j_enabled,
                    scenario_overrides=scenario_overrides,
                )

                start = time.perf_counter()
                payload = run_analysis(config)
                elapsed_ms = (time.perf_counter() - start) * 1000

                st.session_state["last_payload"] = payload
                st.session_state["last_elapsed_ms"] = elapsed_ms

    payload = st.session_state.get("last_payload")
    elapsed_ms = st.session_state.get("last_elapsed_ms")

    if payload is None:
        st.info("Run an analysis to view results.")
        return

    st.subheader("Run Summary")
    _render_status_panel(payload, elapsed_ms)

    tab1, tab2, tab3 = st.tabs(["Recommendations", "Diagnostics", "Raw JSON"])

    with tab1:
        _render_recommendations(payload)

    with tab2:
        _render_diagnostics(payload, model_name=model)

    with tab3:
        st.download_button(
            "Download JSON Output",
            data=json.dumps(payload, indent=2, ensure_ascii=False),
            file_name=f"inventory_run_{payload.get('run_id', 'unknown')}.json",
            mime="application/json",
        )
        st.code(json.dumps(payload, indent=2, ensure_ascii=False), language="json")


if __name__ == "__main__":
    main()
