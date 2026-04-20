"""NetworkX runtime graph builder and query interface."""

from __future__ import annotations

from typing import Any, Dict, List

import networkx as nx


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely coerce values to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _days_of_stock(record: Dict[str, Any]) -> float:
    """Compute simple days-of-stock metric from one record."""
    stock = _safe_float(record.get("current_stock"), 0.0)
    sales = _safe_float(record.get("avg_daily_sales"), 0.0)
    if sales <= 0:
        return 9999.0
    return stock / sales


def build_runtime_graph(records: List[Dict[str, Any]]) -> nx.DiGraph:
    """Build in-memory runtime graph from uploaded inventory rows."""
    if not isinstance(records, list) or not records:
        raise ValueError("graph_build_failed: no records available for runtime graph")

    graph = nx.DiGraph()
    category_dos: Dict[str, List[float]] = {}

    for row in records:
        sku_id = str(row.get("sku_id", "")).strip()
        category = str(row.get("category", "unknown")).strip() or "unknown"
        if not sku_id:
            continue

        category_node = f"category:{category}"
        sku_node = f"sku:{sku_id}"

        dos = _days_of_stock(row)
        category_dos.setdefault(category, []).append(dos)

        graph.add_node(
            sku_node,
            node_type="sku",
            sku_id=sku_id,
            category=category,
            current_stock=_safe_float(row.get("current_stock"), 0.0),
            avg_daily_sales=_safe_float(row.get("avg_daily_sales"), 0.0),
            lead_time_days=_safe_float(row.get("lead_time_days"), 0.0),
            safety_stock=_safe_float(row.get("safety_stock"), 0.0),
            days_of_stock=dos,
            supplier_id=str(row.get("supplier_id", "")).strip(),
        )
        graph.add_node(category_node, node_type="category", category=category)
        graph.add_edge(sku_node, category_node, rel="BELONGS_TO")

        supplier_id = str(row.get("supplier_id", "")).strip()
        if supplier_id:
            supplier_node = f"supplier:{supplier_id}"
            graph.add_node(supplier_node, node_type="supplier", supplier_id=supplier_id)
            graph.add_edge(sku_node, supplier_node, rel="SUPPLIED_BY")

    for category, dos_values in category_dos.items():
        if not dos_values:
            continue
        avg_dos = sum(dos_values) / float(len(dos_values))
        category_node = f"category:{category}"
        if category_node in graph:
            graph.nodes[category_node]["category_avg_dos"] = avg_dos

    sku_nodes = [node for node, attrs in graph.nodes(data=True) if attrs.get("node_type") == "sku"]
    if not sku_nodes:
        raise ValueError("graph_build_failed: no valid SKU nodes created from uploaded records")
    return graph


def query_runtime_graph(graph: nx.DiGraph, sku_id: str) -> Dict[str, Any]:
    """Query runtime graph and return per-SKU enrichment context."""
    sku_node = f"sku:{sku_id}"
    if sku_node not in graph:
        raise KeyError(f"graph_missing_sku:{sku_id}")

    sku_attrs = graph.nodes[sku_node]
    category = str(sku_attrs.get("category", "unknown"))
    category_node = f"category:{category}"
    if category_node not in graph:
        raise KeyError(f"graph_missing_category:{category}")

    category_attrs = graph.nodes[category_node]
    dos = float(sku_attrs.get("days_of_stock", 9999.0))
    category_avg_dos = float(category_attrs.get("category_avg_dos", 30.0))

    risk_tags: List[str] = []
    if dos < 7:
        risk_tags.append("critical_cover")
    elif dos < 14:
        risk_tags.append("low_cover")
    if dos > max(60.0, category_avg_dos * 2.0):
        risk_tags.append("overstock_pressure")
    if float(sku_attrs.get("avg_daily_sales", 0.0)) <= 0:
        risk_tags.append("zero_sales")

    ratio = 1.0 if category_avg_dos <= 0 else min(2.0, max(0.5, dos / category_avg_dos))
    seasonal_factor = round(ratio, 3)

    return {
        "sku_id": sku_id,
        "seasonal_factor": seasonal_factor,
        "category_avg_dos": category_avg_dos,
        "risk_tags": risk_tags,
        "source": "networkx",
        "graph_nodes": graph.number_of_nodes(),
        "graph_edges": graph.number_of_edges(),
        "graph_cache_hit": False,
    }
