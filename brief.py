#!/usr/bin/env python3
"""Run the daddyshome briefings headlessly and render one dashboard.

Each report in reports.conf is handed to `claude -p` in its own directory.
Reports run in parallel. Every report must answer with the JSON contract in
REPORT_SCHEMA; anything else is treated as a failed report rather than
guessed at.

Writes the dashboard HTML and prints the spoken summary on stdout so the
caller can hand it to a speech engine.

    python3 brief.py [--out PATH] [--config PATH] [--timeout SECONDS]
    python3 brief.py --demo     render with sample data, call no models
"""

import argparse
import concurrent.futures
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime

CONFIG_DIR = os.path.expanduser("~/.config/daddyshome")
DEFAULT_CONFIG = os.path.join(CONFIG_DIR, "reports.conf")
DEFAULT_OUT = os.path.expanduser("~/.local/share/daddyshome/briefing.html")

# A headless session cannot prompt for permission, so anything it needs must be
# pre-approved here. Everything on this list is read-only by construction: no
# writes, no network, no history rewriting. Widen it only with the same care.
ALLOWED_TOOLS = [
    "Read", "Glob", "Grep",
    "Bash(git log:*)", "Bash(git status:*)", "Bash(git branch:*)",
    "Bash(git remote:*)", "Bash(git rev-list:*)", "Bash(git diff:*)",
    "Bash(ls:*)", "Bash(wc:*)", "Bash(find:*)",
    "Bash(python3 fetch_inbox.py:*)",
    "Bash(python3 repo_survey.py:*)",
]

REPORT_SCHEMA = """
Answer with a single JSON object and nothing else. No prose, no code fence.

{
  "headline": "one sentence, under 90 characters",
  "spoken":   "what to read aloud: AT MOST 3 short sentences, under 45 spoken
               words total. Plain spoken English, no markdown, no lists, no
               symbols. Lead with the number that matters and what needs doing.
               This is read alongside other reports, so be brief.",
  "stats":    [{"label": "short", "value": "12", "note": "optional context"}],
  "charts":   [{"title": "what is being counted",
                "unit":  "commits",
                "data":  [{"label": "category", "value": 4}]}],
  "sections": [{"title": "short", "items": ["one fact per item"]}],
  "alerts":   [{"level": "good|warning|serious|critical", "text": "short"}]
}

Rules:
- Every number must come from a file you read or a command you ran.
- If you cannot determine something, omit it. Never estimate or invent.
- Keep charts to at most 8 bars each, ordered largest first.
- "spoken" is read aloud, so write it the way a person would say it.
- Any key may be an empty list, but all keys must be present.
"""

# --- validated categorical palette (see dataviz references/palette.md) -------
PALETTE = {
    "light": {
        "surface": "#fcfcfb", "raised": "#ffffff", "line": "#e4e3de",
        "primary": "#0b0b0b", "secondary": "#52514e", "muted": "#7c7b75",
        "series": "#2a78d6", "track": "#eceae5",
        "good": "#008300", "warning": "#eda100",
        "serious": "#eb6834", "critical": "#e34948",
    },
    "dark": {
        "surface": "#1a1a19", "raised": "#232322", "line": "#35342f",
        "primary": "#ffffff", "secondary": "#c3c2b7", "muted": "#8f8e85",
        "series": "#3987e5", "track": "#2b2b29",
        "good": "#008300", "warning": "#c98500",
        "serious": "#d95926", "critical": "#e66767",
    },
}

# Status is never carried by colour alone: each level gets a distinct glyph and
# a written level name. Warning and serious sit close in hue, so their shapes
# have to differ clearly.
ALERT_ICON = {"good": "●", "warning": "▲", "serious": "◆", "critical": "■"}


# --- config ----------------------------------------------------------------

def parse_config(path):
    """Read LABEL :: DIRECTORY :: PROMPT lines."""
    reports = []
    if not os.path.exists(path):
        return reports
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("::", 2)]
            if len(parts) < 3 or not parts[1]:
                continue
            label, directory, prompt = parts
            reports.append({
                "label": label,
                "dir": os.path.expanduser(directory),
                "prompt": prompt,
            })
    return reports


# --- running the model -----------------------------------------------------

def extract_json(text):
    """Pull the JSON object out of a model reply, fenced or not."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object")


def normalise(raw, label):
    """Coerce a model reply into the shape the renderer expects."""
    def as_list(key):
        v = raw.get(key)
        return v if isinstance(v, list) else []

    charts = []
    for c in as_list("charts"):
        if not isinstance(c, dict):
            continue
        data = [d for d in (c.get("data") or [])
                if isinstance(d, dict) and isinstance(d.get("value"), (int, float))]
        if not data:
            continue
        data.sort(key=lambda d: d["value"], reverse=True)
        charts.append({
            "title": str(c.get("title", "")),
            "unit": str(c.get("unit", "")),
            "data": data[:8],
        })

    alerts = []
    for a in as_list("alerts"):
        if isinstance(a, dict) and a.get("text"):
            level = a.get("level", "warning")
            alerts.append({
                "level": level if level in ALERT_ICON else "warning",
                "text": str(a["text"]),
            })

    sections = []
    for s in as_list("sections"):
        if isinstance(s, dict) and s.get("items"):
            sections.append({
                "title": str(s.get("title", "")),
                "items": [str(i) for i in s["items"] if str(i).strip()],
            })

    stats = []
    for s in as_list("stats"):
        if isinstance(s, dict) and s.get("label") is not None:
            stats.append({
                "label": str(s["label"]),
                "value": str(s.get("value", "")),
                "note": str(s.get("note", "")),
            })

    return {
        "label": label,
        "headline": str(raw.get("headline", "")).strip(),
        "spoken": str(raw.get("spoken", "")).strip(),
        "stats": stats, "charts": charts,
        "sections": sections, "alerts": alerts,
        "error": None,
    }


def failed(label, message):
    return {"label": label, "headline": "Report unavailable", "spoken": "",
            "stats": [], "charts": [], "sections": [], "alerts": [],
            "error": message}


def run_report(report, timeout):
    label, directory = report["label"], report["dir"]
    if not os.path.isdir(directory):
        return failed(label, f"directory not found: {directory}")

    prompt = report["prompt"] + "\n\n" + REPORT_SCHEMA
    try:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json",
             "--allowed-tools", *ALLOWED_TOOLS],
            cwd=directory, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return failed(label, f"timed out after {timeout}s")
    except FileNotFoundError:
        return failed(label, "the `claude` command is not on PATH")

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return failed(label, f"exited {proc.returncode}: {detail[:300]}")

    try:
        envelope = json.loads(proc.stdout)
        body = envelope.get("result", proc.stdout) if isinstance(envelope, dict) else proc.stdout
    except json.JSONDecodeError:
        body = proc.stdout

    try:
        return normalise(extract_json(body), label)
    except (ValueError, json.JSONDecodeError) as exc:
        return failed(label, f"could not parse the reply: {exc}")


# --- rendering -------------------------------------------------------------

def e(text):
    return html.escape(str(text), quote=True)


def bar_path(x, y, w, h, r=4):
    """Rect with the value end rounded and the baseline end square."""
    r = max(0, min(r, w, h / 2))
    if r == 0 or w <= 0:
        return f"M{x},{y}h{max(w,0)}v{h}h{-max(w,0)}z"
    return (f"M{x},{y}h{w - r}a{r},{r} 0 0 1 {r},{r}"
            f"v{h - 2 * r}a{r},{r} 0 0 1 {-r},{r}h{-(w - r)}z")


def render_chart(chart, idx):
    data = chart["data"]
    top = max(d["value"] for d in data) or 1
    row_h, gap, label_w, value_w = 26, 6, 132, 54
    plot_w = 380
    height = len(data) * (row_h + gap) - gap
    width = label_w + plot_w + value_w

    marks = []
    for i, d in enumerate(data):
        y = i * (row_h + gap)
        w = max(2, round(plot_w * (d["value"] / top)))
        label = e(d["label"])
        val = d["value"]
        val_s = f"{val:g}"
        marks.append(
            f'<g class="bar-row" tabindex="0" role="listitem" '
            f'aria-label="{label}: {e(val_s)} {e(chart["unit"])}">'
            f'<title>{label}: {e(val_s)} {e(chart["unit"])}</title>'
            f'<text class="bar-label" x="{label_w - 10}" y="{y + row_h / 2}" '
            f'text-anchor="end" dominant-baseline="central">{label}</text>'
            f'<rect class="bar-track" x="{label_w}" y="{y}" width="{plot_w}" '
            f'height="{row_h}" rx="4"/>'
            f'<path class="bar-fill" d="{bar_path(label_w, y, w, row_h)}"/>'
            f'<text class="bar-value" x="{label_w + plot_w + 10}" '
            f'y="{y + row_h / 2}" dominant-baseline="central">{e(val_s)}</text>'
            f'</g>'
        )

    rows = "".join(
        f"<tr><td>{e(d['label'])}</td><td>{d['value']:g}</td></tr>" for d in data
    )
    unit = f' <span class="unit">({e(chart["unit"])})</span>' if chart["unit"] else ""
    return f"""
      <figure class="chart">
        <figcaption>{e(chart["title"])}{unit}</figcaption>
        <svg viewBox="0 0 {width} {height}" width="100%" height="{height}"
             role="list" aria-label="{e(chart["title"])}">{"".join(marks)}</svg>
        <details class="table-view">
          <summary>Table view</summary>
          <table><thead><tr><th>Label</th><th>{e(chart["unit"] or "Value")}</th></tr></thead>
          <tbody>{rows}</tbody></table>
        </details>
      </figure>"""


def render_report(rep, idx):
    if rep["error"]:
        return f"""
      <section class="report">
        <h2>{e(rep["label"])}</h2>
        <p class="failed"><span aria-hidden="true">■</span>
           <strong>Report unavailable.</strong> {e(rep["error"])}</p>
      </section>"""

    stats = "".join(
        f'<div class="stat"><div class="stat-value">{e(s["value"])}</div>'
        f'<div class="stat-label">{e(s["label"])}</div>'
        + (f'<div class="stat-note">{e(s["note"])}</div>' if s["note"] else "")
        + "</div>"
        for s in rep["stats"]
    )
    alerts = "".join(
        f'<li class="alert alert-{a["level"]}">'
        f'<span class="alert-icon" aria-hidden="true">{ALERT_ICON[a["level"]]}</span>'
        f'<span class="alert-level">{a["level"].title()}</span>'
        f'<span class="alert-text">{e(a["text"])}</span></li>'
        for a in rep["alerts"]
    )
    charts = "".join(render_chart(c, f"{idx}-{j}") for j, c in enumerate(rep["charts"]))
    sections = "".join(
        f'<div class="section"><h3>{e(s["title"])}</h3><ul>'
        + "".join(f"<li>{e(i)}</li>" for i in s["items"]) + "</ul></div>"
        for s in rep["sections"]
    )

    return f"""
      <section class="report">
        <h2>{e(rep["label"])}</h2>
        {f'<p class="headline">{e(rep["headline"])}</p>' if rep["headline"] else ""}
        {f'<ul class="alerts">{alerts}</ul>' if alerts else ""}
        {f'<div class="stats">{stats}</div>' if stats else ""}
        {f'<div class="charts">{charts}</div>' if charts else ""}
        {f'<div class="sections">{sections}</div>' if sections else ""}
      </section>"""


def css():
    def block(mode):
        p = PALETTE[mode]
        return "\n".join(f"    --{k}: {v};" for k, v in p.items())
    return f"""
  :root {{ color-scheme: light dark; }}
  .viz-root {{
{block("light")}
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
{block("dark")}
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
{block("dark")}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--surface); }}
  .viz-root {{
    background: var(--surface); color: var(--text, var(--primary));
    font: 15px/1.55 ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif;
    padding: 40px 28px 72px; max-width: 1180px; margin: 0 auto;
    color: var(--primary);
  }}
  header {{ border-bottom: 1px solid var(--line); padding-bottom: 20px; margin-bottom: 8px; }}
  h1 {{ font-size: 26px; letter-spacing: -0.02em; margin: 0 0 6px; }}
  .stamp {{ color: var(--muted); font-size: 13px; margin: 0; }}
  .spoken {{
    margin: 22px 0 0; padding: 16px 18px; border-radius: 10px;
    background: var(--raised); border: 1px solid var(--line);
    color: var(--secondary); font-size: 15px;
  }}
  .spoken strong {{ color: var(--primary); display: block; margin-bottom: 6px;
    font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; }}
  .report {{ margin-top: 44px; }}
  h2 {{ font-size: 13px; letter-spacing: 0.12em; text-transform: uppercase;
       color: var(--muted); margin: 0 0 10px; }}
  .headline {{ font-size: 19px; margin: 0 0 18px; letter-spacing: -0.01em; }}
  .failed {{ color: var(--secondary); background: var(--raised);
    border: 1px solid var(--line); border-left: 3px solid var(--critical);
    padding: 12px 14px; border-radius: 8px; }}
  .failed strong {{ color: var(--primary); }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 22px; }}
  .stat {{ background: var(--raised); border: 1px solid var(--line);
    border-radius: 10px; padding: 14px 18px; min-width: 128px; }}
  .stat-value {{ font-size: 27px; letter-spacing: -0.02em; }}
  .stat-label {{ color: var(--secondary); font-size: 13px; margin-top: 2px; }}
  .stat-note {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
  .alerts {{ list-style: none; padding: 0; margin: 0 0 20px; display: grid; gap: 6px; }}
  .alert {{ display: flex; align-items: baseline; gap: 9px; font-size: 14px;
    background: var(--raised); border: 1px solid var(--line);
    padding: 9px 13px; border-radius: 8px; }}
  .alert-level {{ font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase;
    color: var(--secondary); min-width: 62px; }}
  .alert-text {{ color: var(--primary); }}
  .alert-good .alert-icon {{ color: var(--good); }}
  .alert-warning .alert-icon {{ color: var(--warning); }}
  .alert-serious .alert-icon {{ color: var(--serious); }}
  .alert-critical .alert-icon {{ color: var(--critical); }}
  .charts {{ display: grid; gap: 26px; grid-template-columns: repeat(auto-fit, minmax(430px, 1fr)); }}
  .chart {{ margin: 0; min-width: 0; overflow-x: auto; }}
  /* Cap the plot at its natural width so the label column stays put instead of
     drifting toward the middle as the container grows. */
  .chart svg {{ display: block; max-width: 566px; }}
  figcaption {{ font-size: 14px; color: var(--primary); margin-bottom: 12px; }}
  .unit {{ color: var(--muted); }}
  .bar-label {{ fill: var(--secondary); font-size: 12.5px; }}
  .bar-value {{ fill: var(--primary); font-size: 12.5px; font-variant-numeric: tabular-nums; }}
  .bar-track {{ fill: var(--track); }}
  .bar-fill {{ fill: var(--series); }}
  .bar-row {{ cursor: default; outline: none; }}
  .bar-row:hover .bar-fill, .bar-row:focus-visible .bar-fill {{ opacity: 0.82; }}
  .bar-row:focus-visible .bar-track {{ stroke: var(--secondary); stroke-width: 1.5; }}
  .table-view {{ margin-top: 10px; font-size: 13px; color: var(--secondary); }}
  .table-view summary {{ cursor: pointer; color: var(--muted); }}
  .table-view table {{ border-collapse: collapse; margin-top: 8px; width: 100%; }}
  .table-view th, .table-view td {{ text-align: left; padding: 5px 10px 5px 0;
    border-bottom: 1px solid var(--line); }}
  .sections {{ display: grid; gap: 20px; margin-top: 26px;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
  h3 {{ font-size: 13px; margin: 0 0 7px; color: var(--secondary); }}
  .sections ul {{ margin: 0; padding-left: 18px; }}
  .sections li {{ margin-bottom: 5px; color: var(--primary); }}
  @media (max-width: 620px) {{
    .viz-root {{ padding: 26px 16px 48px; }}
    .charts {{ grid-template-columns: 1fr; }}
  }}"""


def render(reports, spoken):
    stamp = datetime.now().strftime("%A %d %B %Y, %H:%M")
    body = "".join(render_report(r, i) for i, r in enumerate(reports))
    spoken_block = (
        f'<p class="spoken"><strong>Spoken summary</strong>{e(spoken)}</p>'
        if spoken else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily briefing</title>
<style>{css()}</style>
</head>
<body>
<div class="viz-root">
  <header>
    <h1>Daily briefing</h1>
    <p class="stamp">{e(stamp)}</p>
  </header>
  {spoken_block}
  {body}
</div>
</body>
</html>"""


# --- demo data -------------------------------------------------------------

DEMO = [
    {"label": "PIPELINE", "headline": "Three prospects are overdue a follow-up.",
     "spoken": "Three prospects are overdue a follow up, the oldest by nine days. "
               "Nothing is blocking payment. Start with the oldest one.",
     "stats": [{"label": "Active prospects", "value": "23", "note": "across all stages"},
               {"label": "Overdue", "value": "3", "note": "oldest 9 days"},
               {"label": "Awaiting reply", "value": "7", "note": ""}],
     "charts": [{"title": "Prospects by stage", "unit": "prospects",
                 "data": [{"label": "Mockup sent", "value": 9},
                          {"label": "Emailed", "value": 7},
                          {"label": "Responded", "value": 4},
                          {"label": "Call booked", "value": 2},
                          {"label": "Closed", "value": 1}]}],
     "sections": [{"title": "Owed a follow-up",
                   "items": ["Example Co, 9 days", "Sample Ltd, 5 days"]}],
     "alerts": [{"level": "warning", "text": "Example Co has been waiting 9 days."}],
     "error": None},
    {"label": "INBOX", "headline": "Four unread, one needs a reply today.",
     "spoken": "Four unread messages. One needs a reply today. The rest is newsletters.",
     "stats": [{"label": "Unread", "value": "4", "note": "last 3 days"}],
     "charts": [{"title": "Messages by category", "unit": "messages",
                 "data": [{"label": "Worth knowing", "value": 2},
                          {"label": "Needs a reply", "value": 1},
                          {"label": "Noise", "value": 1}]}],
     "sections": [{"title": "Waiting on you", "items": ["A. Sender, weekly update"]}],
     "alerts": [], "error": None},
    {"label": "STANDUP", "headline": "Two repos have uncommitted work.",
     "spoken": "Two repositories have uncommitted work. Everything else is pushed.",
     "stats": [{"label": "Repos touched", "value": "5", "note": "last 7 days"},
               {"label": "Uncommitted", "value": "2", "note": ""}],
     "charts": [{"title": "Commits in the last 7 days", "unit": "commits",
                 "data": [{"label": "web-app", "value": 14},
                          {"label": "daddys-home", "value": 6},
                          {"label": "api-service", "value": 3},
                          {"label": "scratch", "value": 1}]}],
     "sections": [], "alerts": [{"level": "warning", "text": "2 repos have uncommitted changes."}],
     "error": None},
]


# --- entry point -----------------------------------------------------------

def build_spoken(reports):
    parts = [r["spoken"] for r in reports if r.get("spoken")]
    broken = [r["label"] for r in reports if r.get("error")]
    if broken:
        noun = "report" if len(broken) == 1 else "reports"
        parts.append(f"{', '.join(broken)} {'is' if len(broken) == 1 else 'are'} "
                     f"unavailable, sir. Details are on the {noun}.")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    if args.demo:
        reports = DEMO
    else:
        defined = parse_config(args.config)
        if not defined:
            print(f"No reports defined in {args.config}", file=sys.stderr)
            return 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(defined)) as pool:
            futures = [pool.submit(run_report, r, args.timeout) for r in defined]
            reports = [f.result() for f in futures]

    spoken = build_spoken(reports)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render(reports, spoken))

    print(spoken)
    return 0


if __name__ == "__main__":
    sys.exit(main())
