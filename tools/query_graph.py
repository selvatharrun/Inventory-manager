"""Runtime graph query logic using in-memory cache and NetworkX."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from knowledge.cache_layer import CACHE
from knowledge.networkx_graph import build_runtime_graph, query_runtime_graph


def _records_fingerprint(records: list[dict[str, Any]]) -> str:
    """Create stable hash for uploaded records."""
    normalized = json.dumps(records, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def query_graph(
    sku_id: str,
    category: str,
    query_type: str,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Query runtime context from uploaded-data NetworkX graph only."""
    _ = category
    _ = query_type

    records = config.get("runtime_records")
    if not isinstance(records, list) or not records:
        raise ValueError("graph_build_failed: runtime_records missing; graph cannot be built from uploaded data")

    graph_version = str(config.get("graph_schema_version", "runtime-v1"))
    fingerprint = _records_fingerprint(records)
    graph_key = f"runtime_graph:{graph_version}:{fingerprint}"
    cache_ttl = int(config.get("cache", {}).get("ttl_graph_seconds", 86400))

    hit, cached_graph, _ttl = CACHE.get(graph_key)
    if hit:
        graph = cached_graph
        cache_hit = True
    else:
        graph = build_runtime_graph(records)
        CACHE.set(graph_key, graph, ttl_seconds=cache_ttl)
        cache_hit = False

    context = query_runtime_graph(graph, sku_id)
    context["source"] = "cache" if cache_hit else "networkx"
    context["graph_cache_hit"] = cache_hit
    context["graph_fingerprint"] = fingerprint[:16]
    return context
