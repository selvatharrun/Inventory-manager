"""LangGraph node to enrich SKUs with hybrid knowledge graph context."""

from __future__ import annotations

from agent.logging_utils import add_flow_event, add_tool_call_log, timer_ms, timer_start
from agent.state import AgentState, SKUContext
from tools.server import call_mcp_tool_sync


def enrich_context_node(state: AgentState) -> AgentState:
    """Attach contextual graph metadata to each SKU metric."""
    node = "enrich_context"
    add_flow_event(state, node=node, event="start")
    state["current_node"] = "enrich_context"

    mode = str(state["config"].get("mode", "thinking")).lower()
    if mode == "fast":
        state["sku_contexts"] = [
            SKUContext(
                sku_id=metric.sku_id,
                seasonal_factor=1.0,
                category_avg_dos=30.0,
                risk_tags=[],
                context_source="default",
            )
            for metric in state["sku_metrics"]
        ]
        state["graph_source"] = "default"
        state["graph_runtime_stats"] = {
            "enabled": False,
            "mode": "fast",
            "nodes": 0,
            "edges": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }
        state["warnings"].append("Graph enrichment skipped in fast mode.")
        add_flow_event(state, node=node, event="end", detail="skipped_fast_mode")
        return state

    if not state["raw_records"]:
        message = "graph_build_failed: no uploaded records available for thinking-mode graph enrichment"
        state["errors"].append({"node": "enrich_context", "sku_id": "", "message": message})
        add_flow_event(state, node=node, event="end", detail="missing_runtime_records")
        raise RuntimeError(message)

    contexts: list[SKUContext] = []
    source_counts: dict[str, int] = {}
    cache_hits = 0
    cache_misses = 0
    graph_nodes = 0
    graph_edges = 0
    category_by_sku = {record.sku_id: record.category for record in state["sku_records"]}

    for metric in state["sku_metrics"]:
        category = category_by_sku.get(metric.sku_id, "unknown")
        try:
            args = {
                "sku_id": metric.sku_id,
                "category": category,
                "query_type": "all",
                "config": state["config"],
            }
            started = timer_start()
            payload = call_mcp_tool_sync(
                "query_graph",
                args,
            )
            add_tool_call_log(
                state,
                node=node,
                tool_name="query_graph",
                caller="deterministic_system",
                arguments=args,
                status="ok",
                duration_ms=timer_ms(started),
                output_count=1,
            )
        except Exception as exc:
            add_tool_call_log(
                state,
                node=node,
                tool_name="query_graph",
                caller="deterministic_system",
                arguments={"sku_id": metric.sku_id, "category": category, "query_type": "all", "config": state["config"]},
                status="error",
                duration_ms=timer_ms(started),
                error=str(exc),
            )
            state["errors"].append(
                {"node": "enrich_context", "sku_id": metric.sku_id, "message": str(exc)}
            )
            add_flow_event(state, node=node, event="end", detail="graph_query_failed")
            raise RuntimeError(f"graph_query_failed:{metric.sku_id}:{exc}") from exc

        source = str(payload.get("source", "default"))
        source_counts[source] = source_counts.get(source, 0) + 1
        if bool(payload.get("graph_cache_hit", False)):
            cache_hits += 1
        else:
            cache_misses += 1
        graph_nodes = max(graph_nodes, int(payload.get("graph_nodes", 0)))
        graph_edges = max(graph_edges, int(payload.get("graph_edges", 0)))

        contexts.append(
            SKUContext(
                sku_id=metric.sku_id,
                seasonal_factor=float(payload.get("seasonal_factor", 1.0)),
                category_avg_dos=float(payload.get("category_avg_dos", 30.0)),
                risk_tags=list(payload.get("risk_tags", [])),
                context_source=source if source in {"networkx", "cache"} else "networkx",
            )
        )

    state["sku_contexts"] = contexts
    if source_counts:
        state["graph_source"] = max(source_counts.items(), key=lambda item: item[1])[0]
    state["graph_runtime_stats"] = {
        "enabled": True,
        "mode": "thinking",
        "nodes": graph_nodes,
        "edges": graph_edges,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
    }

    add_flow_event(
        state,
        node=node,
        event="end",
        extra={"contexts": len(contexts), "graph_source": state.get("graph_source", "default")},
    )

    return state
