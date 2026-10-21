#!/usr/bin/env python3
"""AI Usage Coach - report renderer.

Reads coach-output/metrics.json (+ optional coaching.json written by Claude)
and produces a single self-contained coach-output/report.html, then opens it.
"""

import argparse
import html
import json
import math
import webbrowser
from datetime import datetime
from pathlib import Path

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def esc(s):
    return html.escape(str(s if s is not None else ""))


def fmt(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n/1_000:.0f}k"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return f"{n:,}"


def bar_rows(items, max_rows=12, unit=""):
    items = list(items)[:max_rows]
    if not items:
        return "<p class='empty'>No data</p>"
    top = max(v for _, v in items) or 1
    rows = []
    for label, v in items:
        w = max(2, round(v / top * 100))
        rows.append(
            f"<div class='bar-row'><div class='bar-label' title='{esc(label)}'>{esc(label)}</div>"
            f"<div class='bar-track'><div class='bar-fill' style='width:{w}%'></div></div>"
            f"<div class='bar-val'>{fmt(v)}{unit}</div></div>"
        )
    return "".join(rows)


def week_chart(by_week):
    if not by_week:
        return "<p class='empty'>No data</p>"
    items = sorted(by_week.items())
    top = max(v for _, v in items) or 1
    cols = []
    for wk, v in items:
        h = max(4, round(v / top * 100))
        label = wk.split("-W")[1] if "-W" in wk else wk
        cols.append(
            f"<div class='wcol' title='{esc(wk)}: {v} sessions'>"
            f"<div class='wnum'>{v}</div><div class='wbar' style='height:{h}%'></div>"
            f"<div class='wlab'>W{esc(label)}</div></div>"
        )
    return f"<div class='weekchart'>{''.join(cols)}</div>"


def hour_heat(by_hour):
    vals = [int(by_hour.get(str(h), 0)) for h in range(24)]
    top = max(vals) or 1
    cells = []
    for h, v in enumerate(vals):
        a = (v / top) ** 0.6 if v else 0
        lab = f"{h:02d}"
        cells.append(
            f"<div class='hcell' title='{lab}:00 — activity {v}'>"
            f"<div class='hdot' style='opacity:{a:.2f}'></div><span>{lab}</span></div>"
        )
    return f"<div class='hourgrid'>{''.join(cells)}</div>"


def weekday_bars(by_weekday):
    items = [(WEEKDAYS[d], int(by_weekday.get(str(d), 0))) for d in range(7)]
    return bar_rows(items, 7)


def score_dial(score):
    score = max(0, min(10, float(score)))
    pct = score / 10
    r, c = 26, 26
    circ = 2 * math.pi * r
    return (
        f"<svg viewBox='0 0 60 60' class='dial'><circle cx='{c+4}' cy='{c+4}' r='{r}' class='dial-bg'/>"
        f"<circle cx='{c+4}' cy='{c+4}' r='{r}' class='dial-fg' stroke-dasharray='{circ*pct:.1f} {circ:.1f}'/>"
        f"<text x='{c+4}' y='{c+9}' class='dial-txt'>{score:g}</text></svg>"
    )


def coaching_html(coaching):
    if not coaching:
        return (
            "<div class='card coach-pending'><h3>Coaching not generated yet</h3>"
            "<p>Run <code>/coach</code> in Claude Code (or ask Claude to read "
            "<code>coach-output/digest.md</code> and write <code>coaching.json</code>, then re-run "
            "<code>render.py</code>) to add personalized coaching to this report.</p></div>"
        )
    out = []
    if coaching.get("headline"):
        out.append(f"<p class='coach-headline'>&ldquo;{esc(coaching['headline'])}&rdquo;</p>")
    if coaching.get("summary"):
        out.append(f"<p class='coach-summary'>{esc(coaching['summary'])}</p>")

    scores = coaching.get("scores") or []
    if scores:
        cells = "".join(
            f"<div class='score'>{score_dial(s.get('score', 0))}"
            f"<div class='score-area'>{esc(s.get('area'))}</div>"
            f"<div class='score-note'>{esc(s.get('note'))}</div></div>"
            for s in scores
        )
        out.append(f"<div class='scores'>{cells}</div>")

    strengths = coaching.get("strengths") or []
    if strengths:
        items = "".join(
            f"<li><strong>{esc(s.get('title'))}</strong> — {esc(s.get('detail'))}</li>"
            for s in strengths
        )
        out.append(f"<div class='card'><h3><span class='tag tag-good'>Working well</span></h3><ul class='clean'>{items}</ul></div>")

    opps = coaching.get("opportunities") or []
    if opps:
        cards = []
        for o in opps:
            impact = (o.get("impact") or "medium").lower()
            cards.append(
                f"<div class='opp'><div class='opp-head'><span class='impact impact-{esc(impact)}'>{esc(impact)} impact</span>"
                f"<h4>{esc(o.get('title'))}</h4></div>"
                f"<p class='opp-why'>{esc(o.get('why'))}</p>"
                f"<p class='opp-try'><strong>Try this:</strong> {esc(o.get('try_this'))}</p></div>"
            )
        out.append(f"<div class='card'><h3><span class='tag tag-opp'>Opportunities</span></h3><div class='opps'>{''.join(cards)}</div></div>")

    if coaching.get("task_mix_notes"):
        out.append(f"<div class='card'><h3>On your task mix</h3><p>{esc(coaching['task_mix_notes'])}</p></div>")
    if coaching.get("next_week_challenge"):
        out.append(
            f"<div class='card challenge'><h3>This week&rsquo;s challenge</h3>"
            f"<p>{esc(coaching['next_week_challenge'])}</p></div>"
        )
    return "".join(out)


def chat_section(chat):
    if not chat or chat.get("error"):
        note = esc(chat["error"]) if chat else (
            "Chat history lives on claude.ai, not on this machine. "
            "<strong>Individual plans (Free/Pro/Max):</strong> Settings &rarr; Privacy &rarr; Export data. "
            "<strong>Team/Enterprise plans:</strong> members can&rsquo;t self-export; the organization&rsquo;s "
            "<em>Primary Owner</em> must run it from Organization settings &rarr; Data and privacy &rarr; Export Data "
            "(note: that export covers the whole org, so extract just your own conversations). "
            "Either way, drop <code>conversations.json</code> into the <code>chat-export</code> folder and re-run <code>/coach</code>."
        )
        return f"<div class='card coach-pending'><h3>Chat (claude.ai) — not included</h3><p>{note}</p></div>"
    cats = bar_rows(sorted(chat.get("categories", {}).items(), key=lambda kv: -kv[1]))
    recent = "".join(
        f"<tr><td>{esc((c.get('created_at') or '')[:10])}</td><td>{esc(c['name'][:60])}</td>"
        f"<td class='num'>{c['messages']}</td><td>{esc(c['category'])}</td></tr>"
        for c in chat.get("conversations", [])[:15]
    )
    return f"""
    <div class='grid2'>
      <div class='card'><h3>Chat at a glance</h3>
        <div class='statline'><b>{fmt(chat['total_conversations'])}</b> conversations &middot;
        <b>{fmt(chat['total_messages'])}</b> messages</div>
        <h4>Topics</h4>{cats}</div>
      <div class='card'><h3>Recent conversations</h3>
        <table><thead><tr><th>Date</th><th>Title</th><th class='num'>Msgs</th><th>Topic</th></tr></thead>
        <tbody>{recent}</tbody></table></div>
    </div>"""


def build_html(metrics, coaching):
    t = metrics["totals"]
    dr = t.get("date_range") or ["", ""]
    gen = datetime.now().strftime("%B %d, %Y at %H:%M")

    proj_items = sorted(metrics["projects"].items(), key=lambda kv: -kv[1]["sessions"])
    proj_cards = "".join(
        f"<div class='proj'><div class='proj-name'>{esc(name)}"
        + ("<span class='pill'>Cowork</span>" if p["is_cowork"] else "")
        + f"</div><div class='proj-meta'>{p['sessions']} sessions &middot; ~{p['active_seconds']//3600}h "
          f"{(p['active_seconds']%3600)//60}m active &middot; {fmt(p['user_msgs'])} msgs</div>"
          f"<div class='proj-dates'>{esc(p['first'])} &rarr; {esc(p['last'])}</div></div>"
        for name, p in proj_items
    )

    model_rows = "".join(
        f"<tr><td>{esc(m)}</td><td class='num'>{fmt(v['calls'])}</td><td class='num'>{fmt(v['out'])}</td>"
        f"<td class='num'>{fmt(v['cache_read'])}</td></tr>"
        for m, v in sorted(metrics["models"].items(), key=lambda kv: -kv[1]["out"])
    )

    interactive = [r for r in metrics["sessions"] if not r.get("scheduled")]
    n_sched = len(metrics["sessions"]) - len(interactive)
    recent_sessions = "".join(
        f"<tr><td>{esc(r['date'])}</td><td>{esc(r['project'])}</td><td class='num'>{r['active_minutes']:g}m</td>"
        f"<td class='num'>{r['user_msgs']}</td><td>{esc(r['category'])}</td>"
        f"<td class='excerpt'>{esc(r['excerpt'][:110])}</td></tr>"
        for r in interactive[::-1][:20]
    )
    sched_note = (
        f"<p class='empty' style='margin-top:10px'>Plus {n_sched} automated scheduled-task runs "
        f"(excluded here, included in totals).</p>" if n_sched else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Usage Coach</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,900&family=Newsreader:ital@0;1&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
<style>
:root {{
  --paper:#f7f3ec; --paper2:#fffdf8; --ink:#1f1b16; --ink2:#5c544a; --line:#e3dccf;
  --accent:#c2491d; --accent2:#1d6a5a; --gold:#b98a2f;
  --serif:"Fraunces", Georgia, serif; --body:"IBM Plex Sans", "Segoe UI", sans-serif;
  --mono:"IBM Plex Mono", Consolas, monospace; --read:"Newsreader", Georgia, serif;
}}
* {{ box-sizing:border-box; margin:0; }}
body {{ background:var(--paper); color:var(--ink); font-family:var(--body); font-size:15px; line-height:1.55;
  background-image:radial-gradient(rgba(31,27,22,.045) 1px, transparent 1px); background-size:22px 22px; }}
.wrap {{ max-width:1060px; margin:0 auto; padding:48px 28px 80px; }}
header {{ border-bottom:3px solid var(--ink); padding-bottom:28px; margin-bottom:36px; position:relative; }}
.kicker {{ font-family:var(--mono); font-size:12px; letter-spacing:.18em; text-transform:uppercase; color:var(--accent); }}
h1 {{ font-family:var(--serif); font-weight:900; font-size:clamp(40px,6vw,64px); line-height:1.02; margin:10px 0 8px; }}
h1 em {{ font-style:italic; color:var(--accent); }}
.sub {{ font-family:var(--read); font-style:italic; font-size:18px; color:var(--ink2); }}
.stamp {{ position:absolute; right:0; top:6px; font-family:var(--mono); font-size:11px; color:var(--ink2);
  border:1px solid var(--line); padding:6px 10px; transform:rotate(2deg); background:var(--paper2); }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin:0 0 40px; }}
.stat {{ background:var(--paper2); border:1px solid var(--line); border-top:3px solid var(--accent); padding:16px 18px; }}
.stat:nth-child(2n) {{ border-top-color:var(--accent2); }}
.stat:nth-child(3n) {{ border-top-color:var(--gold); }}
.stat b {{ display:block; font-family:var(--serif); font-size:30px; font-weight:600; }}
.stat span {{ font-size:12px; text-transform:uppercase; letter-spacing:.08em; color:var(--ink2); }}
h2 {{ font-family:var(--serif); font-size:30px; font-weight:900; margin:52px 0 6px; }}
h2 .no {{ color:var(--accent); font-size:18px; vertical-align:super; margin-right:6px; font-family:var(--mono); font-weight:400; }}
.rule {{ height:2px; background:var(--ink); width:64px; margin:0 0 22px; }}
h3 {{ font-family:var(--serif); font-size:19px; margin-bottom:12px; }}
h4 {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--ink2); margin:14px 0 8px; }}
.card {{ background:var(--paper2); border:1px solid var(--line); padding:22px 24px; margin-bottom:18px;
  box-shadow:3px 3px 0 rgba(31,27,22,.06); }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
@media (max-width:800px) {{ .grid2 {{ grid-template-columns:1fr; }} .stamp{{display:none}} }}
.bar-row {{ display:grid; grid-template-columns:170px 1fr 52px; gap:10px; align-items:center; margin:7px 0; }}
.bar-label {{ font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-family:var(--mono); }}
.bar-track {{ background:rgba(31,27,22,.07); height:14px; }}
.bar-fill {{ background:linear-gradient(90deg,var(--accent),#e06a35); height:100%; }}
.bar-val {{ font-family:var(--mono); font-size:12px; text-align:right; color:var(--ink2); }}
.weekchart {{ display:flex; align-items:flex-end; gap:6px; height:150px; padding-top:10px; }}
.wcol {{ flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; height:100%; min-width:0; }}
.wbar {{ width:70%; background:var(--accent2); min-height:4px; }}
.wcol:hover .wbar {{ background:var(--accent); }}
.wnum {{ font-family:var(--mono); font-size:10px; color:var(--ink2); margin-bottom:3px; }}
.wlab {{ font-family:var(--mono); font-size:10px; color:var(--ink2); margin-top:5px; }}
.hourgrid {{ display:grid; grid-template-columns:repeat(12,1fr); gap:8px; }}
.hcell {{ text-align:center; }}
.hcell span {{ font-family:var(--mono); font-size:10px; color:var(--ink2); }}
.hdot {{ width:22px; height:22px; border-radius:50%; background:var(--accent); margin:0 auto 4px; border:1px solid var(--line); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.07em; color:var(--ink2);
  border-bottom:2px solid var(--ink); padding:6px 8px; }}
td {{ border-bottom:1px solid var(--line); padding:7px 8px; vertical-align:top; }}
td.num, th.num {{ text-align:right; font-family:var(--mono); }}
td.excerpt {{ font-family:var(--read); font-style:italic; color:var(--ink2); }}
.proj {{ border-left:3px solid var(--gold); padding:10px 16px; margin:10px 0; background:var(--paper2); border:1px solid var(--line); border-left:3px solid var(--gold); }}
.proj-name {{ font-family:var(--serif); font-size:17px; font-weight:600; }}
.proj-meta {{ font-size:13px; color:var(--ink2); }}
.proj-dates {{ font-family:var(--mono); font-size:11px; color:var(--ink2); }}
.pill {{ font-family:var(--mono); font-size:10px; background:var(--accent2); color:#fff; padding:2px 8px; border-radius:10px; margin-left:8px; vertical-align:middle; }}
.coach-headline {{ font-family:var(--serif); font-size:clamp(24px,3.4vw,34px); font-weight:600; font-style:italic; line-height:1.25; margin:6px 0 14px; }}
.coach-summary {{ font-family:var(--read); font-size:18px; color:var(--ink2); margin-bottom:24px; max-width:62ch; }}
.scores {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; margin-bottom:18px; }}
.score {{ background:var(--paper2); border:1px solid var(--line); padding:16px; text-align:center; }}
.dial {{ width:64px; height:64px; }}
.dial-bg {{ fill:none; stroke:rgba(31,27,22,.1); stroke-width:6; }}
.dial-fg {{ fill:none; stroke:var(--accent); stroke-width:6; stroke-linecap:round; transform:rotate(-90deg); transform-origin:center; }}
.dial-txt {{ font-family:var(--serif); font-size:18px; font-weight:600; text-anchor:middle; fill:var(--ink); }}
.score-area {{ font-weight:600; margin-top:6px; }}
.score-note {{ font-size:12px; color:var(--ink2); }}
.tag {{ font-family:var(--mono); font-size:11px; letter-spacing:.1em; text-transform:uppercase; padding:3px 10px; }}
.tag-good {{ background:var(--accent2); color:#fff; }}
.tag-opp {{ background:var(--accent); color:#fff; }}
ul.clean {{ list-style:none; }} ul.clean li {{ padding:8px 0; border-bottom:1px dashed var(--line); }}
ul.clean li:last-child {{ border-bottom:none; }}
.opps {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
@media (max-width:800px) {{ .opps {{ grid-template-columns:1fr; }} }}
.opp {{ border:1px solid var(--line); padding:16px; background:var(--paper); }}
.opp h4 {{ font-family:var(--serif); font-size:16px; text-transform:none; letter-spacing:0; color:var(--ink); margin:6px 0 8px; }}
.impact {{ font-family:var(--mono); font-size:10px; text-transform:uppercase; padding:2px 8px; border-radius:9px; }}
.impact-high {{ background:var(--accent); color:#fff; }}
.impact-medium {{ background:var(--gold); color:#fff; }}
.impact-low {{ background:var(--line); color:var(--ink2); }}
.opp-why {{ font-size:13.5px; color:var(--ink2); margin:6px 0; }}
.opp-try {{ font-size:13.5px; }}
.challenge {{ border:2px solid var(--accent); background:#fdf0e9; }}
.coach-pending {{ border-style:dashed; }}
.statline {{ font-size:15px; margin-bottom:6px; }}
code {{ font-family:var(--mono); font-size:12.5px; background:rgba(31,27,22,.07); padding:1px 5px; }}
.empty {{ color:var(--ink2); font-style:italic; }}
footer {{ margin-top:60px; border-top:1px solid var(--line); padding-top:16px; font-family:var(--mono); font-size:11px; color:var(--ink2); }}
</style></head><body><div class="wrap">

<header>
  <div class="kicker">Personal usage review &middot; 100% local</div>
  <h1>AI Usage <em>Coach</em></h1>
  <p class="sub">How you work with Claude — and where the next gear is.</p>
  <div class="stamp">{esc(dr[0])} &rarr; {esc(dr[1])}<br>generated {esc(gen)}</div>
</header>

<div class="stats">
  <div class="stat"><b>{fmt(t['sessions'])}</b><span>sessions</span></div>
  <div class="stat"><b>{t['active_hours']:g}h</b><span>active time</span></div>
  <div class="stat"><b>{fmt(t['user_messages'])}</b><span>your messages</span></div>
  <div class="stat"><b>{fmt(t['tool_calls'])}</b><span>tool calls</span></div>
  <div class="stat"><b>{fmt(t['tokens_out'])}</b><span>output tokens</span></div>
  <div class="stat"><b>{fmt(t['projects'])}</b><span>workspaces</span></div>
</div>

<h2><span class="no">01</span>Coaching</h2><div class="rule"></div>
{coaching_html(coaching)}

<h2><span class="no">02</span>Rhythm</h2><div class="rule"></div>
<div class="grid2">
  <div class="card"><h3>Sessions per week</h3>{week_chart(metrics['by_week'])}</div>
  <div class="card"><h3>Activity by hour</h3>{hour_heat(metrics['by_hour'])}
    <h4>By weekday</h4>{weekday_bars(metrics['by_weekday'])}</div>
</div>

<h2><span class="no">03</span>What you work on</h2><div class="rule"></div>
<div class="grid2">
  <div class="card"><h3>Task categories <span style="font-weight:400;font-size:12px;color:var(--ink2)">(sessions, keyword heuristic)</span></h3>
    {bar_rows(metrics['categories'].items())}</div>
  <div class="card"><h3>Workspaces</h3>{proj_cards}</div>
</div>

<h2><span class="no">04</span>How you and Claude operate</h2><div class="rule"></div>
<div class="grid2">
  <div class="card"><h3>Top tools Claude used for you</h3>{bar_rows(metrics['tools'].items(), 14)}</div>
  <div class="card"><h3>Models</h3>
    <table><thead><tr><th>Model</th><th class="num">Turns</th><th class="num">Out tokens</th><th class="num">Cache read</th></tr></thead>
    <tbody>{model_rows}</tbody></table>
    <h4>Friction signals</h4>
    <div class="statline">Interruptions (you hit stop): <b>{t['interruptions']}</b></div>
    <div class="statline">Subagent messages (delegated work): <b>{fmt(t['subagent_messages'])}</b></div>
  </div>
</div>

<h2><span class="no">05</span>Chat (claude.ai)</h2><div class="rule"></div>
{chat_section(metrics.get('chat'))}

<h2><span class="no">06</span>Recent interactive sessions</h2><div class="rule"></div>
<div class="card">
<table><thead><tr><th>Date</th><th>Workspace</th><th class="num">Active</th><th class="num">Msgs</th><th>Topic</th><th>Opening prompt</th></tr></thead>
<tbody>{recent_sessions}</tbody></table>
{sched_note}
</div>

<footer>AI USAGE COACH &middot; built locally &middot; data never leaves this machine &middot; re-run anytime with /coach</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Render the AI Usage Coach report.")
    ap.add_argument("--out", default="coach-output")
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    mpath = out_dir / "metrics.json"
    if not mpath.is_file():
        raise SystemExit(f"ERROR: {mpath} not found. Run analyze.py first.")
    metrics = json.loads(mpath.read_text(encoding="utf-8"))

    coaching = None
    cpath = out_dir / "coaching.json"
    if cpath.is_file():
        try:
            coaching = json.loads(cpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"WARNING: coaching.json is invalid ({e}); rendering without it.")

    report = out_dir / "report.html"
    report.write_text(build_html(metrics, coaching), encoding="utf-8")
    print(f"Wrote {report}")
    if not args.no_open:
        webbrowser.open(report.as_uri())


if __name__ == "__main__":
    main()
