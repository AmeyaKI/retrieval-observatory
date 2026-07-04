from __future__ import annotations

import html
import json
from typing import Any, Dict, List, Optional

# Render diagram-ready pipeline JSON (from dashboard.api._build_diagram) into a single, fully
# self-contained HTML file — no CDN, no JS framework, works offline and attaches to a PR. Each
# pipeline is a left-to-right strip of stage cards; each card overlays per-stage Recall / NDCG@10
# / latency with their bootstrap confidence intervals. This is the read-only "traced pipeline
# diagram with per-stage metrics overlay" as a shareable artifact.


def _fmt(value: Optional[float], pct: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%" if pct else f"{value:.1f}"


def _ci(overlay: Optional[Dict[str, Any]], pct: bool = False) -> str:
    if not overlay or overlay.get("ci_low") is None or overlay.get("ci_high") is None:
        return ""
    lo, hi = overlay["ci_low"], overlay["ci_high"]
    return f"95% CI [{_fmt(lo, pct)}, {_fmt(hi, pct)}]"


def _metric_row(label: str, overlay: Optional[Dict[str, Any]], pct: bool) -> str:
    mean = overlay.get("mean") if overlay else None
    ci = _ci(overlay, pct)
    ci_html = f'<span class="ci">{html.escape(ci)}</span>' if ci else ""
    return (
        f'<div class="metric"><span class="label">{html.escape(label)}</span>'
        f'<span class="value">{_fmt(mean, pct)}</span>{ci_html}</div>'
    )


def _card(node: Dict[str, Any]) -> str:
    m = node.get("metrics") or {}
    recall = m.get("recall")
    recall_label = f"Recall@{recall['k']}" if recall and recall.get("k") is not None else "Recall"
    rows = [
        _metric_row(recall_label, recall, pct=True),
        _metric_row("NDCG@10", m.get("ndcg@10"), pct=True),
        _metric_row("Latency p50 (ms)", m.get("latency_p50"), pct=False),
    ]
    arms_html = ""
    if node.get("arms"):
        arm_cards = "".join(
            f'<div class="arm"><div class="arm-title">{html.escape(a["arm_id"])}</div>'
            + _metric_row("Recall", (a.get("metrics") or {}).get("recall"), pct=True)
            + "</div>"
            for a in node["arms"]
        )
        arms_html = f'<div class="arms">{arm_cards}</div>'
    kind = html.escape(str(node.get("kind", "")))
    op_type = html.escape(str(node.get("op_type") or ""))
    return (
        f'<div class="card kind-{kind}">'
        f'<div class="card-head"><span class="stage-id">{html.escape(str(node.get("stage_id", "")))}</span>'
        f'<span class="op-type">{op_type}</span></div>'
        f'{arms_html}'
        f'<div class="metrics">{"".join(rows)}</div>'
        f"</div>"
    )


def _pipeline_block(pipeline: Dict[str, Any]) -> str:
    nodes = sorted(pipeline.get("nodes", []), key=lambda n: n.get("stage_index", 0))
    cards = '<div class="arrow">→</div>'.join(_card(n) for n in nodes)
    return (
        f'<section class="pipeline"><h2>{html.escape(str(pipeline.get("pipeline_id", "")))}</h2>'
        f'<div class="strip">{cards}</div></section>'
    )


_STYLE = """
:root { --bg:#0f1117; --card:#1b1f2a; --line:#2c3242; --accent:#5b9bff; --text:#e6e9ef; --dim:#8a91a3; }
* { box-sizing: border-box; }
body { background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; margin:0; padding:32px; }
h1 { font-size:20px; margin:0 0 4px; }
.sub { color:var(--dim); font-size:13px; margin-bottom:24px; }
.pipeline { margin-bottom:32px; }
.pipeline h2 { font-size:15px; color:var(--accent); margin:0 0 12px; }
.strip { display:flex; align-items:stretch; gap:8px; overflow-x:auto; padding-bottom:8px; }
.arrow { display:flex; align-items:center; color:var(--dim); font-size:20px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px; min-width:190px; }
.card-head { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; gap:8px; }
.stage-id { font-weight:600; font-size:13px; }
.op-type { font-size:10px; text-transform:uppercase; letter-spacing:.04em; color:var(--dim); border:1px solid var(--line); border-radius:4px; padding:1px 5px; }
.metric { display:flex; flex-direction:column; margin-bottom:6px; }
.metric .label { font-size:11px; color:var(--dim); }
.metric .value { font-size:16px; font-weight:600; }
.metric .ci { font-size:10px; color:var(--dim); }
.arms { display:flex; gap:6px; margin-bottom:8px; }
.arm { background:#141824; border:1px dashed var(--line); border-radius:6px; padding:6px; flex:1; }
.arm-title { font-size:10px; color:var(--dim); margin-bottom:4px; }
.kind-source { border-left:3px solid #4caf88; }
.kind-fused { border-left:3px solid #c58af9; }
.kind-rerank { border-left:3px solid var(--accent); }
footer { color:var(--dim); font-size:11px; margin-top:24px; }
"""


def render_diagram_html(run_id: str, pipelines: List[Dict[str, Any]]) -> str:
    """Render the read-only pipeline diagram for a run as a standalone HTML document."""
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
<div class="sub">Run <code>{html.escape(run_id)}</code> · read-only · per-stage metrics with 95% bootstrap CIs</div>
{body}
<footer>Generated by <code>retobs diagram</code>. Diagram data embedded below for tooling.</footer>
<script type="application/json" id="retobs-diagram-data">{data_json}</script>
</body>
</html>
"""
