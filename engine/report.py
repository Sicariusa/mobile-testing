"""Report — render a self-contained HTML timeline from the run's evidence.

One file, inline CSS/JS, no external assets. Per step it shows: index + action,
a colour-coded status, how the target was resolved (``resolved_by`` + score),
how the outcome was validated (``validated_by``), the recovery attempts, any
OCR matches, and before/after thumbnails.
"""
from __future__ import annotations

import html
import json
import os
from typing import Any

_STATUS_COLOR = {
    "PASS": "#1f9d55",
    "FAIL": "#d64545",
    "BLOCKED": "#c98a1b",
    "CRASH": "#a032c0",
    "SKIPPED": "#8a94a6",
}


def render(timeline: dict[str, Any], out_path: str) -> str:
    meta = timeline.get("meta", {})
    steps = timeline.get("steps", [])
    cards = "\n".join(_step_card(s) for s in steps)
    overall = meta.get("overall", "UNKNOWN")
    overall_color = _STATUS_COLOR.get(overall, "#8a94a6")

    counts: dict[str, int] = {}
    for s in steps:
        counts[s["status"]] = counts.get(s["status"], 0) + 1
    summary = " · ".join(f"{k}: {v}" for k, v in counts.items()) or "no steps"

    doc = _TEMPLATE.format(
        title=html.escape(str(meta.get("name", "Mobile QA Run"))),
        run_id=html.escape(str(meta.get("run_id", ""))),
        package=html.escape(str(meta.get("package", ""))),
        overall=html.escape(str(overall)),
        overall_color=overall_color,
        summary=html.escape(summary),
        cards=cards,
        raw=html.escape(json.dumps(timeline, indent=2)),
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return out_path


def _step_card(step: dict[str, Any]) -> str:
    status = step.get("status", "?")
    color = _STATUS_COLOR.get(status, "#8a94a6")
    idx = step.get("index", "?")
    action = html.escape(str(step.get("action", "")))
    target = step.get("target")
    value = step.get("value")

    meta_bits = []
    if step.get("resolved_by"):
        conf = step.get("resolved_confidence")
        conf_s = f" @{conf:.2f}" if isinstance(conf, (int, float)) else ""
        meta_bits.append(f"resolved_by <b>{html.escape(str(step['resolved_by']))}</b>{conf_s}")
    if step.get("validated_by"):
        conf = step.get("validation_confidence")
        conf_s = f" @{conf:.2f}" if isinstance(conf, (int, float)) else ""
        meta_bits.append(f"validated_by <b>{html.escape(str(step['validated_by']))}</b>{conf_s}")
    if step.get("duration_ms"):
        meta_bits.append(f"{step['duration_ms']} ms")
    meta_line = " &nbsp;·&nbsp; ".join(meta_bits)

    sub = []
    if target:
        sub.append("target: <code>" + html.escape(json.dumps(target)) + "</code>")
    if value not in (None, ""):
        sub.append("value: <code>" + html.escape(str(value)) + "</code>")
    if step.get("detail"):
        sub.append(html.escape(str(step["detail"])))
    if step.get("error"):
        sub.append("<span class='err'>" + html.escape(str(step["error"])) + "</span>")
    if step.get("crash_signature"):
        sub.append("<span class='err'>crash: " + html.escape(str(step["crash_signature"])) + "</span>")
    sub_line = "<br>".join(sub)

    recovery = step.get("recovery", {}).get("attempts", [])
    recovery_html = ""
    if recovery:
        rows = "".join(
            f"<li><b>{html.escape(a.get('method',''))}</b> → {html.escape(a.get('outcome',''))}"
            + (f" <span class='muted'>{html.escape(str(a.get('detail','')))}</span>" if a.get("detail") else "")
            + "</li>"
            for a in recovery
        )
        recovery_html = f"<details><summary>recovery ({len(recovery)})</summary><ul>{rows}</ul></details>"

    ocr = step.get("ocr_matches", [])
    ocr_html = ""
    if ocr:
        rows = "".join(
            f"<li>“{html.escape(str(m.get('text','')))}” "
            f"<span class='muted'>conf {m.get('confidence', 0):.2f}</span></li>"
            for m in ocr
        )
        ocr_html = f"<details><summary>OCR matches ({len(ocr)})</summary><ul>{rows}</ul></details>"

    thumbs = ""
    b, a = step.get("before_thumb"), step.get("after_thumb")
    if b or a:
        thumbs = "<div class='thumbs'>"
        if b:
            thumbs += f"<figure><img src='{html.escape(b)}' loading='lazy'><figcaption>before</figcaption></figure>"
        if a:
            thumbs += f"<figure><img src='{html.escape(a)}' loading='lazy'><figcaption>after</figcaption></figure>"
        thumbs += "</div>"

    return f"""
    <div class="card">
      <div class="card-head">
        <span class="badge" style="background:{color}">{html.escape(status)}</span>
        <span class="step-title">#{idx} &nbsp; {action}</span>
        <span class="meta">{meta_line}</span>
      </div>
      <div class="sub">{sub_line}</div>
      {recovery_html}
      {ocr_html}
      {thumbs}
    </div>"""


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Mobile QA Report</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0;
         background: #f6f7f9; color: #1c2330; }}
  header {{ background: #10131a; color: #fff; padding: 20px 28px; }}
  header h1 {{ margin: 0 0 6px; font-size: 20px; }}
  header .row {{ display: flex; gap: 18px; flex-wrap: wrap; align-items: center;
                font-size: 13px; color: #b9c2d0; }}
  header .overall {{ padding: 3px 12px; border-radius: 20px; color: #fff;
                     font-weight: 700; background: {overall_color}; }}
  main {{ max-width: 960px; margin: 0 auto; padding: 22px 16px 60px; }}
  .card {{ background: #fff; border: 1px solid #e3e7ee; border-radius: 10px;
           padding: 14px 16px; margin-bottom: 14px; }}
  .card-head {{ display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }}
  .badge {{ color: #fff; font-weight: 700; font-size: 12px; padding: 2px 10px;
            border-radius: 6px; }}
  .step-title {{ font-weight: 600; font-size: 15px; }}
  .meta {{ color: #6a7688; font-size: 12px; margin-left: auto; }}
  .sub {{ margin-top: 8px; font-size: 13px; color: #3a4658; line-height: 1.5; }}
  code {{ background: #eef1f6; padding: 1px 5px; border-radius: 4px; font-size: 12px; }}
  details {{ margin-top: 8px; font-size: 13px; }}
  summary {{ cursor: pointer; color: #35507a; }}
  ul {{ margin: 6px 0 0; padding-left: 18px; }}
  .muted {{ color: #8a94a6; }}
  .err {{ color: #d64545; }}
  .thumbs {{ display: flex; gap: 14px; margin-top: 12px; flex-wrap: wrap; }}
  .thumbs figure {{ margin: 0; }}
  .thumbs img {{ max-width: 320px; width: 100%; border: 1px solid #d9dee7;
                 border-radius: 6px; background: #fff; }}
  .thumbs figcaption {{ font-size: 11px; color: #8a94a6; text-align: center; margin-top: 4px; }}
  footer {{ max-width: 960px; margin: 0 auto; padding: 0 16px 40px; }}
  footer details pre {{ background: #10131a; color: #cfd8e3; padding: 14px;
                        border-radius: 8px; overflow: auto; font-size: 12px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="row">
    <span class="overall">{overall}</span>
    <span>package: {package}</span>
    <span>run: {run_id}</span>
    <span>{summary}</span>
  </div>
</header>
<main>
{cards}
</main>
<footer>
  <details><summary>raw timeline.json</summary><pre>{raw}</pre></details>
</footer>
</body>
</html>"""
