from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional

# Render the trace-native PipelineGraph contract (pipeline/graph_contract.py, produced by
# pipeline/graph_projection.py::build_pipeline_graphs) into a single, fully self-contained
# HTML file — no CDN, no JS framework, works offline and attaches to a PR. Nodes are laid
# out on a real grid (column = depth, row = position within that depth layer, using the
# producer's own (depth, node_id) sort order) with an SVG edge overlay, so branching, fusion
# fan-ins, and parallel lanes render as real graph structure — not a flattened linear strip.
# This replaced an older heuristic renderer (`_build_diagram`/`_pipeline_topology` in
# dashboard/api.py, deleted) that inferred topology from PipelineResult.snapshots and could
# not represent fan-in at all.

_CARD_W = 210
_CARD_H = 130
_COL_GAP = 70
_ROW_GAP = 18
_MARGIN = 24


def _fmt(value: Optional[float], pct: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%" if pct else f"{value:.1f}"


def _ci(metric: Optional[Dict[str, Any]], pct: bool = False) -> str:
    if not metric or metric.get("ci_low") is None or metric.get("ci_high") is None:
        return ""
    lo, hi = metric["ci_low"], metric["ci_high"]
    return f"95% CI [{_fmt(lo, pct)}, {_fmt(hi, pct)}]"


def _metric_row(label: str, metric: Optional[Dict[str, Any]], pct: bool) -> str:
    mean = metric.get("mean") if metric else None
    ci = _ci(metric, pct)
    ci_html = f'<span class="ci">{html.escape(ci)}</span>' if ci else ""
    return (
        f'<div class="metric"><span class="label">{html.escape(label)}</span>'
        f'<span class="value">{_fmt(mean, pct)}</span>{ci_html}</div>'
    )


def _node_positions(nodes: List[Dict[str, Any]]) -> Dict[str, tuple]:
    """Grid position (col=depth, row=index within that depth) for every node, using the
    producer's own (depth, node_id) ordering -- deterministic across renders."""
    by_depth: Dict[int, List[Dict[str, Any]]] = {}
    for n in sorted(nodes, key=lambda n: (n["depth"], n["node_id"])):
        by_depth.setdefault(n["depth"], []).append(n)
    positions: Dict[str, tuple] = {}
    for depth, depth_nodes in by_depth.items():
        for row, n in enumerate(depth_nodes):
            positions[n["node_id"]] = (depth, row)
    return positions


def _card(node: Dict[str, Any], x: float, y: float) -> str:
    m = node.get("metrics") or {}
    recall = m.get("recall")
    recall_label = f"Recall@{recall['k']}" if recall and recall.get("k") is not None else "Recall"
    rows = [
        _metric_row(recall_label, recall, pct=True),
        _metric_row("NDCG@10", m.get("ndcg@10"), pct=True),
        _metric_row("Latency p50 (ms)", m.get("latency_p50"), pct=False),
    ]
    op_type = html.escape(str(node.get("op_type") or ""))
    merge_cls = " is-merge" if node.get("is_merge") else ""
    return (
        f'<div class="card{merge_cls}" style="left:{x}px;top:{y}px;width:{_CARD_W}px;height:{_CARD_H}px" '
        f'data-node-id="{html.escape(str(node.get("node_id", "")))}">'
        f'<div class="card-head"><span class="stage-id">{html.escape(str(node.get("label", "")))}</span>'
        f'<span class="op-type">{op_type}</span></div>'
        f'<div class="metrics">{"".join(rows)}</div>'
        f"</div>"
    )


def _edge_path(x1: float, y1: float, x2: float, y2: float) -> str:
    """Cubic bezier from the right edge of the source card to the left edge of the target,
    so edges read as smooth connectors rather than straight lines crossing card interiors."""
    midx = (x1 + x2) / 2
    return f"M {x1} {y1} C {midx} {y1}, {midx} {y2}, {x2} {y2}"


def _pipeline_block(pipeline: Dict[str, Any]) -> str:
    nodes = pipeline.get("nodes", [])
    edges = pipeline.get("edges", [])
    if not nodes:
        return (
            f'<section class="pipeline"><h2>{html.escape(str(pipeline.get("pipeline_id", "")))}</h2>'
            f'<p class="sub">No nodes to display.</p></section>'
        )

    positions = _node_positions(nodes)
    node_by_id = {n["node_id"]: n for n in nodes}
    max_col = max(col for col, _ in positions.values())
    rows_per_col: Dict[int, int] = {}
    for col, row in positions.values():
        rows_per_col[col] = max(rows_per_col.get(col, 0), row + 1)
    max_rows = max(rows_per_col.values()) if rows_per_col else 1

    width = _MARGIN * 2 + (max_col + 1) * _CARD_W + max_col * _COL_GAP
    height = _MARGIN * 2 + max_rows * _CARD_H + max(0, max_rows - 1) * _ROW_GAP

    def _xy(node_id: str) -> tuple:
        col, row = positions[node_id]
        x = _MARGIN + col * (_CARD_W + _COL_GAP)
        y = _MARGIN + row * (_CARD_H + _ROW_GAP)
        return x, y

    cards_html = "".join(_card(node_by_id[nid], *_xy(nid)) for nid in positions)

    edge_paths = []
    for e in edges:
        if e["source"] not in positions or e["target"] not in positions:
            continue
        sx, sy = _xy(e["source"])
        tx, ty = _xy(e["target"])
        x1, y1 = sx + _CARD_W, sy + _CARD_H / 2
        x2, y2 = tx, ty + _CARD_H / 2
        cls = "edge-fan-in" if e.get("kind") == "fan_in" else "edge-flow"
        edge_paths.append(f'<path class="{cls}" d="{_edge_path(x1, y1, x2, y2)}" />')
    edges_svg = (
        f'<svg class="edges" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" /></marker></defs>'
        f'{"".join(edge_paths)}</svg>'
    )

    return (
        f'<section class="pipeline"><h2>{html.escape(str(pipeline.get("pipeline_id", "")))}</h2>'
        f'<div class="canvas" style="width:{width}px;height:{height}px">{edges_svg}{cards_html}</div>'
        f"</section>"
    )


_STYLE = """
:root { --bg:#0f1117; --card:#1b1f2a; --line:#2c3242; --accent:#5b9bff; --text:#e6e9ef; --dim:#8a91a3; --merge:#c58af9; }
* { box-sizing: border-box; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; margin:0; padding:32px; }
h1 { font-size:20px; margin:0 0 4px; }
.sub { color:var(--dim); font-size:13px; margin-bottom:24px; }
.pipeline { margin-bottom:40px; }
.pipeline h2 { font-size:15px; color:var(--accent); margin:0 0 12px; }
.canvas { position:relative; overflow-x:auto; }
.edges { position:absolute; left:0; top:0; pointer-events:none; }
.edge-flow { fill:none; stroke:var(--line); stroke-width:2; marker-end:url(#arrow); }
.edge-fan-in { fill:none; stroke:var(--merge); stroke-width:2; stroke-dasharray:5 4; marker-end:url(#arrow); }
.card { position:absolute; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; overflow:hidden; }
.card.is-merge { border-color:var(--merge); border-width:2px; }
.card-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; gap:8px; }
.stage-id { font-weight:600; font-size:13px; }
.op-type { font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:var(--dim); border:1px solid var(--line); border-radius:4px; padding:1px 5px; white-space:nowrap; }
.metric { display:flex; flex-direction:column; margin-bottom:6px; }
.metric .label { font-size:11px; color:var(--dim); }
.metric .value { font-size:16px; font-weight:600; }
.metric .ci { font-size:10px; color:var(--dim); }
footer { color:var(--dim); font-size:11px; margin-top:24px; }
"""


def render_diagram_html(run_id: str, pipelines: List[Dict[str, Any]]) -> str:
    """Render the read-only, trace-native pipeline diagram for a run as a standalone HTML
    document. `pipelines` is the PipelineGraph.to_dict() list from build_pipeline_graphs."""
    body = "".join(_pipeline_block(p) for p in pipelines) or '<p class="sub">No pipelines to display.</p>'
    data_json = html.escape(json.dumps({"run_id": run_id, "pipelines": pipelines}))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>retobs pipeline diagram — {html.escape(run_id)}</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>Retrieval Observatory — Pipeline Diagram</h1>
<div class="sub">Run <code>{html.escape(run_id)}</code> · read-only · trace-native topology · per-stage metrics with 95% bootstrap CIs</div>
{body}
<footer>Generated by <code>retobs diagram</code>. Diagram data embedded below for tooling.</footer>
<script type="application/json" id="retobs-diagram-data">{data_json}</script>
</body>
</html>
"""
