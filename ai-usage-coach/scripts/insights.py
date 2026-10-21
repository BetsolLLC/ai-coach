#!/usr/bin/env python3
"""AI Usage Coach - public "Executive Insights" research note.

This is the OUTWARD-facing companion to render.py. Where report.html coaches the
individual privately (and quotes their prompts), this produces a SHAREABLE research
note in an analyst voice: "here is what extensive, real-world use of an AI agent
revealed", suitable for a LinkedIn post, a company blog, or social.

Design principles (set by the user):
  * Research / field-notes tone, NOT sales or marketing. Findings, not claims.
  * Aggregate only. No prompt excerpts, no client names, no raw project names.
    The user's own memory agent and organization (from coach-config.json) may be named.
  * Every number is either MEASURED (straight from the transcripts) or MODELED
    (an estimate from a stated assumption). The two are visually distinguished and
    the assumptions are printed in the open.

Pipeline:
  metrics.json  ──►  insights.py  ──►  insights_metrics.json   (computed facts, machine-readable)
                                  └─►  insights.html           (the public research note)

  Optional: Claude reads insights_metrics.json and writes insights_narrative.json
  (prose findings, headline, pull quotes) which this script folds into the page.
  Numbers are ALWAYS computed here so the narrative can't drift from the data.

Everything stays local. No network calls (the page links web fonts only for display).
"""

import argparse
import html
import json
import math
import webbrowser
from datetime import date, datetime
from pathlib import Path

from config import load_config

# ---------------------------------------------------------------------------
# Modeling assumptions. These are intentionally conservative and are printed
# verbatim in the report's methodology section so a skeptical reader can audit
# them. Tune here; the report and the numbers update together.
# ---------------------------------------------------------------------------
ASSUMPTIONS = {
    # Human-equivalent minutes of work that one unattended scheduled routine run
    # replaces (checking a source, compiling a summary, drafting a recurring note).
    "routine_minutes_low": 10,
    "routine_minutes_high": 25,
    # Minutes of "re-explaining context to a fresh assistant" that each persistent
    # memory operation (load/capture/etc.) avoids.
    "memory_minutes_low": 1,
    "memory_minutes_high": 3,
    "weeks_per_year": 52,
}

# The persistent-memory agent layer (if any) is identified by coach-config.json:
# agent_tool_prefix matches MCP tools as analyze.py's shorten_tool() renders them
# ("<server>:<tool>"). With no agent configured, the agent sections are omitted.
# Heuristic categories that indicate work flowing through the persistent agent.
AGENT_CATEGORIES = ("Scheduled Automation (Routines)", "Memory / Sidekick Agent")


def esc(s):
    return html.escape(str(s if s is not None else ""))


def fmt(n):
    n = float(n or 0)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n/1_000:.0f}k"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:,.1f}"


def hours(h):
    """Pretty-print an hours figure."""
    h = float(h or 0)
    if h >= 100:
        return f"{h:.0f}"
    if h >= 10:
        return f"{h:.0f}"
    return f"{h:.1f}"


def pct(x):
    return f"{round(x * 100)}%"


def parse_date(s):
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------
def compute_insights(metrics, cfg):
    """Turn raw metrics.json into a research-ready findings dict.

    Returns a dict with two clearly separated buckets: 'measured' (straight from
    the logs) and 'modeled' (estimates), plus the assumptions used.
    """
    t = metrics.get("totals", {})
    sessions = metrics.get("sessions", []) or []
    projects = metrics.get("projects", {}) or {}
    tools = metrics.get("tools", {}) or {}

    total_sessions = t.get("sessions", 0) or 0
    scheduled = t.get("scheduled_sessions", 0) or 0
    interactive = t.get("interactive_sessions", total_sessions - scheduled) or 0
    user_messages = t.get("user_messages", 0) or 0
    assistant_messages = t.get("assistant_messages", 0) or 0
    tool_calls = t.get("tool_calls", 0) or 0
    active_hours = t.get("active_hours", 0) or 0
    interruptions = t.get("interruptions", 0) or 0
    tokens_out = t.get("tokens_out", 0) or 0
    cache_read = t.get("tokens_cache_read", 0) or 0

    dr = t.get("date_range") or [None, None]
    d0, d1 = parse_date(dr[0]), parse_date(dr[1])
    window_days = (d1 - d0).days + 1 if (d0 and d1) else None
    window_weeks = round(window_days / 7, 1) if window_days else None

    # --- Leverage / amplification (measured) ---
    actions_per_instruction = (tool_calls / user_messages) if user_messages else 0
    turns_per_instruction = (assistant_messages / user_messages) if user_messages else 0

    # --- Autonomy (measured) ---
    autonomy_ratio = (scheduled / total_sessions) if total_sessions else 0
    autonomous_runtime_h = round(
        sum(r.get("active_minutes", 0) for r in sessions if r.get("scheduled")) / 60, 1
    )

    # --- First-time quality / friction (measured) ---
    interrupted_sessions = sum(1 for r in sessions if (r.get("interruptions") or 0) > 0)
    completion_rate = (
        (total_sessions - interrupted_sessions) / total_sessions if total_sessions else 0
    )
    actions_per_stop = (tool_calls / interruptions) if interruptions else None

    # --- Persistent-memory agent layer (measured) ---
    prefix = cfg.get("agent_tool_prefix") or ""
    memory_ops = sum(v for k, v in tools.items() if prefix and str(k).startswith(prefix))
    agent_sessions = agent_tokens = agent_tool_calls = 0
    for name, p in projects.items():
        cats = p.get("categories", {}) or {}
        if any(c in cats for c in AGENT_CATEGORIES):
            agent_sessions += p.get("sessions", 0)
            agent_tokens += p.get("tokens_out", 0)
            agent_tool_calls += p.get("tool_calls", 0)
    agent_session_share = (agent_sessions / total_sessions) if total_sessions else 0
    agent_token_share = (agent_tokens / tokens_out) if tokens_out else 0
    agent_toolcall_share = (agent_tool_calls / tool_calls) if tool_calls else 0

    # --- Modeled time saved (estimates; assumptions printed in report) ---
    a = ASSUMPTIONS
    routine_low_h = scheduled * a["routine_minutes_low"] / 60
    routine_high_h = scheduled * a["routine_minutes_high"] / 60
    mem_low_h = memory_ops * a["memory_minutes_low"] / 60
    mem_high_h = memory_ops * a["memory_minutes_high"] / 60
    saved_low_h = routine_low_h + mem_low_h
    saved_high_h = routine_high_h + mem_high_h
    saved_mid_h = (saved_low_h + saved_high_h) / 2

    per_week_low = (saved_low_h / window_weeks) if window_weeks else None
    per_week_high = (saved_high_h / window_weeks) if window_weeks else None
    annual_low = per_week_low * a["weeks_per_year"] if per_week_low is not None else None
    annual_high = per_week_high * a["weeks_per_year"] if per_week_high is not None else None

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": {
            "start": dr[0],
            "end": dr[1],
            "days": window_days,
            "weeks": window_weeks,
        },
        "measured": {
            "total_sessions": total_sessions,
            "interactive_sessions": interactive,
            "autonomous_sessions": scheduled,
            "autonomy_ratio": autonomy_ratio,
            "autonomous_runtime_h": autonomous_runtime_h,
            "active_hours": round(active_hours, 1),
            "user_messages": user_messages,
            "assistant_messages": assistant_messages,
            "tool_calls": tool_calls,
            "actions_per_instruction": round(actions_per_instruction, 1),
            "turns_per_instruction": round(turns_per_instruction, 1),
            "interruptions": interruptions,
            "interrupted_sessions": interrupted_sessions,
            "completion_rate": completion_rate,
            "actions_per_stop": round(actions_per_stop) if actions_per_stop else None,
            "tokens_out": tokens_out,
            "cache_read_tokens": cache_read,
            "memory_ops": memory_ops,
            "agent_sessions": agent_sessions,
            "agent_session_share": agent_session_share,
            "agent_token_share": agent_token_share,
            "agent_toolcall_share": agent_toolcall_share,
        },
        "modeled": {
            "routine_hours_low": round(routine_low_h, 1),
            "routine_hours_high": round(routine_high_h, 1),
            "memory_hours_low": round(mem_low_h, 1),
            "memory_hours_high": round(mem_high_h, 1),
            "saved_hours_low": round(saved_low_h, 1),
            "saved_hours_high": round(saved_high_h, 1),
            "saved_hours_mid": round(saved_mid_h, 1),
            "saved_per_week_low": round(per_week_low, 1) if per_week_low is not None else None,
            "saved_per_week_high": round(per_week_high, 1) if per_week_high is not None else None,
            "annualized_low": round(annual_low) if annual_low is not None else None,
            "annualized_high": round(annual_high) if annual_high is not None else None,
        },
        "assumptions": ASSUMPTIONS,
        "agent": {
            "name": cfg.get("agent_name") or "",
            "configured": bool(cfg.get("agent_name") or prefix or cfg.get("agent_workspace")),
        },
    }


# ---------------------------------------------------------------------------
# Default prose (used when no Claude-written narrative is present, so the page
# always stands on its own). Claude's insights_narrative.json overrides these.
# ---------------------------------------------------------------------------
def default_narrative(ins):
    m = ins["measured"]
    md = ins["modeled"]
    w = ins["window"]
    weeks = w.get("weeks")
    agent = ins.get("agent") or {}
    agent_label = f"The persistent-agent layer ({agent['name']})" if agent.get("name") else "The persistent-agent layer"

    findings = [
        {
            "label": "An agent does most of its work unattended",
            "stat": f"{pct(m['autonomy_ratio'])} of sessions ran with no human at the keyboard",
            "finding": (
                f"Of {fmt(m['total_sessions'])} total agent sessions, {fmt(m['autonomous_sessions'])} "
                f"were scheduled routines that executed on their own — {pct(m['autonomy_ratio'])} of all activity, "
                f"and roughly {hours(m['autonomous_runtime_h'])} hours of cumulative run-time."
            ),
            "interpretation": (
                "Once recurring work is described once and scheduled, the marginal human cost of running "
                "it again falls to zero. The interesting unit of AI work stops being 'a chat' and becomes "
                "'a standing process.'"
            ),
            "basis": "measured",
        },
        {
            "label": "One instruction sets off many autonomous actions",
            "stat": f"~{m['actions_per_instruction']} tool actions per human instruction",
            "finding": (
                f"{fmt(m['user_messages'])} human instructions produced {fmt(m['assistant_messages'])} "
                f"assistant turns and {fmt(m['tool_calls'])} concrete tool actions — an amplification of about "
                f"{m['actions_per_instruction']}x in actions (and {m['turns_per_instruction']}x in turns) per thing typed."
            ),
            "interpretation": (
                "The leverage isn't faster typing; it's that a single well-scoped instruction expands into a "
                "long chain of read/edit/run steps the operator never has to perform by hand."
            ),
            "basis": "measured",
        },
        {
            "label": "High-autonomy work rarely needed correction",
            "stat": f"{pct(m['completion_rate'])} of sessions ran to completion without a human stop",
            "finding": (
                f"Across {fmt(m['total_sessions'])} sessions and {fmt(m['tool_calls'])} tool actions, the operator "
                f"interrupted the agent only {fmt(m['interruptions'])} time(s)"
                + (f" — one course-correction per ~{fmt(m['actions_per_stop'])} autonomous actions." if m['actions_per_stop'] else ".")
            ),
            "interpretation": (
                "A low interruption rate is a proxy for first-time quality: the operator trusted the output enough "
                "to let runs finish. Trust, not raw speed, is what makes delegation stick."
            ),
            "basis": "measured",
        },
    ]
    memory_finding = [
        {
            "label": "Persistent memory removes the re-explaining tax",
            "stat": f"{fmt(m['memory_ops'])} persistent-memory operations across the window",
            "finding": (
                f"{agent_label} loaded, captured, and carried project context "
                f"{fmt(m['memory_ops'])} times — and {pct(m['agent_session_share'])} of all sessions, "
                f"plus {pct(m['agent_token_share'])} of all generated output, flowed through it."
            ),
            "interpretation": (
                "Plain, stateless assistants restart cold every session. A memory layer means the operator stops "
                "paying the 're-explain who I am and what we're doing' tax on every interaction."
            ),
            "basis": "measured",
        },
    ]
    time_finding = [
        {
            "label": "A conservative floor on time returned",
            "stat": f"~{hours(md['saved_hours_low'])}–{hours(md['saved_hours_high'])} hours over {weeks or '?'} weeks",
            "finding": (
                f"On deliberately conservative assumptions (printed below), the autonomous routines and persistent "
                f"memory returned an estimated {hours(md['saved_hours_low'])}–{hours(md['saved_hours_high'])} hours "
                f"in this window"
                + (f", or roughly {fmt(md['annualized_low'])}–{fmt(md['annualized_high'])} hours per year at the same cadence." if md.get("annualized_low") else ".")
            ),
            "interpretation": (
                "This is a floor, not a ceiling: it counts only recurring automation and avoided re-explaining, and "
                "ignores how much faster the interactive deliverables themselves got produced."
            ),
            "basis": "modeled",
        },
    ]
    findings = findings + (memory_finding if agent.get("configured") else []) + time_finding

    return {
        "title": "An Operator's Log: What Heavy Agent Use Revealed",
        "dek": (
            "We instrumented our own day-to-day use of an AI coding agent — and a persistent-memory agent built "
            "on top of it — to see what actually changes when you stop chatting and start delegating. These are the findings."
        ),
        "abstract": (
            f"Over {w.get('weeks') or '?'} weeks we logged {fmt(m['total_sessions'])} agent sessions and "
            f"{hours(m['active_hours'])} active hours of real work. Rather than a product pitch, we treated our own "
            "usage as a small field study: which patterns compound, where the leverage actually comes from, and what "
            "a persistent agent adds over a vanilla one. Every figure below is either measured directly from the "
            "session logs or modeled from a stated, conservative assumption."
        ),
        "agent_thesis": (
            "The sharpest difference we observed was not Claude versus no-Claude; it was a stateless assistant versus "
            f"a persistent one. {agent_label} adds three things a fresh chat cannot: durable "
            f"memory of projects and preferences, the ability to run on a schedule with nobody watching, and the "
            f"continuity that lets it finish long runs without correction. In this window {pct(m['agent_session_share'])} "
            f"of sessions and {pct(m['agent_token_share'])} of output ran through that layer."
        ) if agent.get("configured") else "",
        "caveats": (
            "This is one operator's data over one window — a case study, not a benchmark. 'Time saved' is a modeled "
            "estimate on conservative assumptions, not a measured stopwatch figure; we publish the assumptions so they "
            "can be challenged. Interruption rate is an imperfect proxy for quality. We share it in the spirit of "
            "Anthropic's own 'how we use Claude' writeups: useful signal from real use, openly caveated."
        ),
        "findings": findings,
        "pull_quotes": [
            f"{pct(m['autonomy_ratio'])} of our AI sessions ran with nobody at the keyboard.",
            f"One typed instruction set off ~{m['actions_per_instruction']} autonomous actions, on average.",
            f"{pct(m['completion_rate'])} of sessions finished without a single human course-correction.",
        ],
    }


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
def stat_card(value, label, basis, sub=None):
    tag = (
        "<span class='basis basis-measured'>measured</span>"
        if basis == "measured"
        else "<span class='basis basis-modeled'>modeled</span>"
    )
    subhtml = f"<div class='stat-sub'>{esc(sub)}</div>" if sub else ""
    return (
        f"<div class='kstat'><div class='kstat-top'>{tag}</div>"
        f"<b>{value}</b><span class='kstat-label'>{esc(label)}</span>{subhtml}</div>"
    )


def finding_block(n, f):
    basis = (f.get("basis") or "measured").lower()
    tag = (
        "<span class='basis basis-measured'>measured</span>"
        if basis == "measured"
        else "<span class='basis basis-modeled'>modeled</span>"
    )
    return (
        f"<div class='finding'>"
        f"<div class='finding-no'>{n:02d}</div>"
        f"<div class='finding-body'>"
        f"<div class='finding-head'>{tag}<h3>{esc(f.get('label'))}</h3></div>"
        f"<p class='finding-stat'>{esc(f.get('stat'))}</p>"
        f"<p class='finding-text'>{esc(f.get('finding'))}</p>"
        f"<p class='finding-interp'>{esc(f.get('interpretation'))}</p>"
        f"</div></div>"
    )


def compare_table(m, agent_name):
    rows = [
        ("Memory across sessions", "Resets every session", "Carries projects &amp; preferences forward"),
        ("Runs on a schedule", "Only when prompted", f"{fmt(m['autonomous_sessions'])} unattended runs this window"),
        ("Re-explaining context", "Every session, by hand", f"{fmt(m['memory_ops'])} memory ops did it automatically"),
        ("Share of work handled", "&mdash;", f"{pct(m['agent_session_share'])} of sessions · {pct(m['agent_token_share'])} of output"),
    ]
    body = "".join(
        f"<tr><td class='cmp-dim'>{d}</td><td class='cmp-plain'>{a}</td>"
        f"<td class='cmp-agent'>{b}</td></tr>"
        for d, a, b in rows
    )
    return (
        "<table class='cmp'><thead><tr><th>Capability</th>"
        f"<th>Stateless assistant</th><th>Persistent agent{f' ({esc(agent_name)})' if agent_name else ''}</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def model_table(ins):
    a = ins["assumptions"]
    md = ins["modeled"]
    m = ins["measured"]
    rows = [
        (
            "Recurring routines automated",
            f"{fmt(m['autonomous_sessions'])} runs &times; {a['routine_minutes_low']}&ndash;{a['routine_minutes_high']} min each",
            f"{hours(md['routine_hours_low'])}&ndash;{hours(md['routine_hours_high'])} h",
        ),
        (
            "Context not re-explained",
            f"{fmt(m['memory_ops'])} memory ops &times; {a['memory_minutes_low']}&ndash;{a['memory_minutes_high']} min each",
            f"{hours(md['memory_hours_low'])}&ndash;{hours(md['memory_hours_high'])} h",
        ),
    ]
    if not (ins.get("agent") or {}).get("configured"):
        rows = rows[:1]
    body = "".join(
        f"<tr><td>{d}</td><td class='mono'>{basis}</td><td class='num'>{val}</td></tr>"
        for d, basis, val in rows
    )
    total = (
        f"<tr class='model-total'><td>Estimated total returned</td><td class='mono'>conservative floor</td>"
        f"<td class='num'>{hours(md['saved_hours_low'])}&ndash;{hours(md['saved_hours_high'])} h</td></tr>"
    )
    return (
        "<table class='model'><thead><tr><th>Source of time returned</th>"
        "<th>Basis</th><th class='num'>Estimate</th></tr></thead>"
        f"<tbody>{body}{total}</tbody></table>"
    )


def build_html(ins, narrative, cfg):
    m = ins["measured"]
    md = ins["modeled"]
    w = ins["window"]
    n = narrative
    agent = ins.get("agent") or {}
    has_agent = agent.get("configured")
    author = esc(cfg.get("author"))
    org = esc(cfg.get("organization"))

    gen = datetime.now().strftime("%B %d, %Y")
    findings = n.get("findings") or []
    finding_html = "".join(finding_block(i + 1, f) for i, f in enumerate(findings))

    quotes = n.get("pull_quotes") or []
    quote_html = "".join(
        f"<blockquote class='pull'>&ldquo;{esc(q)}&rdquo;</blockquote>" for q in quotes
    )

    # Headline stat cards (always computed, deterministic)
    cards = "".join([
        stat_card(pct(m["autonomy_ratio"]), "of sessions ran unattended", "measured",
                  f"{fmt(m['autonomous_sessions'])} of {fmt(m['total_sessions'])} sessions"),
        stat_card(f"{m['actions_per_instruction']}&times;", "actions per human instruction", "measured",
                  f"{fmt(m['tool_calls'])} actions from {fmt(m['user_messages'])} instructions"),
        stat_card(pct(m["completion_rate"]), "of sessions finished without a stop", "measured",
                  f"{fmt(m['interruptions'])} interruption(s) total"),
        stat_card(f"{hours(m['autonomous_runtime_h'])}h", "of unattended agent run-time", "measured",
                  "work done with nobody watching"),
        stat_card(f"{hours(md['saved_hours_low'])}&ndash;{hours(md['saved_hours_high'])}h",
                  "estimated time returned", "modeled",
                  f"over {w.get('weeks') or '?'} weeks · conservative floor"),
    ] + ([
        stat_card(pct(m["agent_session_share"]), "of work ran through the memory agent", "measured",
                  f"{agent.get('name') or 'memory agent'} · {pct(m['agent_token_share'])} of output"),
    ] if has_agent else []))

    annual = ""
    if md.get("annualized_low") is not None:
        annual = (
            f"<p class='model-note'>At the same cadence that extrapolates to roughly "
            f"<b>{fmt(md['annualized_low'])}&ndash;{fmt(md['annualized_high'])} hours per year</b> "
            f"({hours(md['saved_per_week_low'])}&ndash;{hours(md['saved_per_week_high'])} h/week).</p>"
        )

    kicker = " &middot; ".join(x for x in (org, "Field Research", "AI Agents in Practice") if x)
    byline = f"By <b>{author}</b> &middot; " if author else ""
    footer_org = f"a {org} operator case study" if org else "an operator case study"
    agent_section = (
        f"""<h2><span class="no">03</span>The persistent-agent difference</h2><div class="rule"></div>
<div class="agent">
  <p class="lead">{esc(n.get('agent_thesis') or '')}</p>
  {compare_table(m, agent.get('name'))}
</div>
""" if has_agent else ""
    )
    mem_assumption = (
        f" Each persistent-memory operation is credited with <code>{ins['assumptions']['memory_minutes_low']}&ndash;"
        f"{ins['assumptions']['memory_minutes_high']} min</code> of context that did not have to be re-supplied by hand."
    ) if has_agent else ""
    no = (lambda k: f"{k:02d}") if has_agent else (lambda k: f"{k - 1 if k > 3 else k:02d}")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(n.get('title') or 'AI Agent Field Notes')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,900&family=Newsreader:ital@0;1&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono&display=swap" rel="stylesheet">
<style>
:root {{
  --paper:#fbfaf7; --paper2:#ffffff; --ink:#16181d; --ink2:#565b66; --line:#e4e2da;
  --accent:#1b4965; --accent2:#2a9d8f; --measured:#1f7a5c; --modeled:#b07515;
  --serif:"Fraunces", Georgia, serif; --body:"IBM Plex Sans","Segoe UI",sans-serif;
  --mono:"IBM Plex Mono", Consolas, monospace; --read:"Newsreader", Georgia, serif;
}}
* {{ box-sizing:border-box; margin:0; }}
body {{ background:var(--paper); color:var(--ink); font-family:var(--body); font-size:15px; line-height:1.6; }}
.wrap {{ max-width:1000px; margin:0 auto; padding:46px 26px 90px; }}
header {{ border-bottom:3px solid var(--ink); padding-bottom:26px; margin-bottom:34px; }}
.kicker {{ font-family:var(--mono); font-size:11.5px; letter-spacing:.2em; text-transform:uppercase; color:var(--accent); }}
h1 {{ font-family:var(--serif); font-weight:900; font-size:clamp(32px,5vw,52px); line-height:1.05; margin:12px 0 14px; max-width:20ch; }}
.dek {{ font-family:var(--read); font-size:clamp(17px,2.2vw,21px); color:var(--ink2); max-width:60ch; line-height:1.5; }}
.byline {{ font-family:var(--mono); font-size:11.5px; color:var(--ink2); margin-top:18px; letter-spacing:.04em; }}
.byline b {{ color:var(--ink); }}
h2 {{ font-family:var(--serif); font-size:27px; font-weight:900; margin:54px 0 4px; }}
h2 .no {{ color:var(--accent); font-size:16px; vertical-align:super; margin-right:8px; font-family:var(--mono); font-weight:400; }}
.rule {{ height:2px; background:var(--ink); width:56px; margin:0 0 22px; }}
.abstract {{ font-family:var(--read); font-size:18px; line-height:1.6; color:var(--ink); background:var(--paper2); border:1px solid var(--line); border-left:4px solid var(--accent); padding:22px 26px; }}
.kstats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; margin:8px 0 6px; }}
.kstat {{ background:var(--paper2); border:1px solid var(--line); border-top:3px solid var(--accent); padding:16px 18px; display:flex; flex-direction:column; }}
.kstat-top {{ margin-bottom:8px; }}
.kstat b {{ font-family:var(--serif); font-size:34px; font-weight:600; line-height:1; }}
.kstat-label {{ font-size:13px; color:var(--ink2); margin-top:6px; }}
.stat-sub {{ font-family:var(--mono); font-size:10.5px; color:var(--ink2); margin-top:8px; letter-spacing:.02em; }}
.basis {{ font-family:var(--mono); font-size:10px; letter-spacing:.12em; text-transform:uppercase; padding:2px 8px; border-radius:3px; }}
.basis-measured {{ background:rgba(31,122,92,.12); color:var(--measured); border:1px solid rgba(31,122,92,.3); }}
.basis-modeled {{ background:rgba(176,117,21,.12); color:var(--modeled); border:1px solid rgba(176,117,21,.3); }}
.legend {{ font-size:13px; color:var(--ink2); margin:16px 0 0; display:flex; gap:18px; flex-wrap:wrap; align-items:center; }}
.finding {{ display:grid; grid-template-columns:64px 1fr; gap:18px; padding:24px 0; border-bottom:1px solid var(--line); }}
.finding:last-child {{ border-bottom:none; }}
.finding-no {{ font-family:var(--serif); font-size:40px; font-weight:900; color:var(--line); line-height:1; }}
.finding-head {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:6px; }}
.finding-head h3 {{ font-family:var(--serif); font-size:21px; font-weight:600; }}
.finding-stat {{ font-family:var(--serif); font-style:italic; font-size:19px; color:var(--accent); margin:4px 0 10px; }}
.finding-text {{ margin-bottom:8px; }}
.finding-interp {{ font-family:var(--read); font-size:16px; color:var(--ink2); border-left:3px solid var(--line); padding-left:14px; }}
.agent {{ background:var(--paper2); border:1px solid var(--line); padding:26px 28px; }}
.agent p.lead {{ font-family:var(--read); font-size:18px; line-height:1.6; margin-bottom:20px; max-width:64ch; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; margin-top:6px; }}
th {{ text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.07em; color:var(--ink2); border-bottom:2px solid var(--ink); padding:8px 10px; }}
td {{ border-bottom:1px solid var(--line); padding:10px; vertical-align:top; }}
td.num, th.num {{ text-align:right; font-family:var(--mono); }}
td.mono {{ font-family:var(--mono); font-size:12px; color:var(--ink2); }}
.cmp .cmp-dim {{ font-weight:600; }}
.cmp .cmp-plain {{ color:var(--ink2); }}
.cmp .cmp-agent {{ color:var(--accent); font-weight:500; }}
.model .model-total td {{ border-top:2px solid var(--ink); font-weight:600; font-family:var(--serif); }}
.model-note {{ font-size:14px; color:var(--ink2); margin-top:14px; }}
.methodology {{ background:var(--paper2); border:1px dashed var(--line); padding:22px 26px; font-size:14px; color:var(--ink2); line-height:1.65; }}
.methodology h4 {{ font-family:var(--serif); font-size:16px; color:var(--ink); margin:14px 0 6px; }}
.methodology h4:first-child {{ margin-top:0; }}
.methodology code {{ font-family:var(--mono); font-size:12px; background:rgba(22,24,29,.06); padding:1px 5px; }}
.pulls {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:16px; }}
.pull {{ font-family:var(--serif); font-style:italic; font-size:19px; line-height:1.35; background:var(--accent); color:#fff; padding:22px 24px; border-radius:2px; }}
.pull:nth-child(2) {{ background:var(--accent2); }}
.pull:nth-child(3) {{ background:var(--ink); }}
footer {{ margin-top:64px; border-top:1px solid var(--line); padding-top:18px; font-family:var(--mono); font-size:11px; color:var(--ink2); line-height:1.7; }}
@media (max-width:680px) {{ .finding {{ grid-template-columns:1fr; gap:6px; }} .finding-no {{ font-size:28px; }} }}
</style></head><body><div class="wrap">

<header>
  <div class="kicker">{kicker}</div>
  <h1>{esc(n.get('title') or 'An Operator&rsquo;s Log')}</h1>
  <p class="dek">{esc(n.get('dek') or '')}</p>
  <div class="byline">{byline}observation window {esc(w.get('start'))} &rarr; {esc(w.get('end'))} ({esc(w.get('weeks'))} weeks) &middot; published {esc(gen)}</div>
</header>

<p class="abstract">{esc(n.get('abstract') or '')}</p>

<div class="legend">
  <span class="basis basis-measured">measured</span> straight from the session logs
  <span class="basis basis-modeled">modeled</span> an estimate from a stated assumption (see methodology)
</div>

<h2><span class="no">01</span>The headline numbers</h2><div class="rule"></div>
<div class="kstats">{cards}</div>

<h2><span class="no">02</span>What we found</h2><div class="rule"></div>
{finding_html}

{agent_section}
<h2><span class="no">{no(4)}</span>Modeling the time returned</h2><div class="rule"></div>
<p style="color:var(--ink2); max-width:64ch; margin-bottom:16px;">We resisted a single splashy number. Instead, here is an additive, deliberately conservative model with every assumption exposed. Treat it as a floor.</p>
{model_table(ins)}
{annual}

<h2><span class="no">{no(5)}</span>Shareable findings</h2><div class="rule"></div>
<div class="pulls">{quote_html}</div>

<h2><span class="no">{no(6)}</span>Methodology &amp; limitations</h2><div class="rule"></div>
<div class="methodology">
  <h4>Data source</h4>
  <p>All measured figures are computed locally from this operator's own Claude Code / Cowork session transcripts over the stated window. No prompt content, client names, or individual session details are published — only aggregates.</p>
  <h4>Modeling assumptions (the only non-measured inputs)</h4>
  <p>Each unattended routine run is credited with <code>{ins['assumptions']['routine_minutes_low']}&ndash;{ins['assumptions']['routine_minutes_high']} min</code> of human-equivalent work.{mem_assumption} The model deliberately excludes acceleration on interactive deliverables, so the true figure is higher.</p>
  <h4>Limitations</h4>
  <p>{esc(n.get('caveats') or '')}</p>
</div>

<footer>
  AI AGENT FIELD NOTES &middot; {footer_org} &middot; generated {esc(gen)}<br>
  Measured aggregates from local session logs; &ldquo;time returned&rdquo; is a modeled, conservative estimate. Shared as research, not a product claim.
</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Render the public AI-agent research note.")
    ap.add_argument("--out", default="coach-output")
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--render-only", action="store_true",
                    help="Skip analysis and render from an existing (possibly hand-preserved) "
                         "insights_metrics.json. Use when the study window's raw transcripts have "
                         "rotated out of the local logs and can no longer be recomputed.")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    cfg = load_config(out_dir)
    ipath = out_dir / "insights_metrics.json"

    if args.render_only:
        if not ipath.is_file():
            raise SystemExit(f"ERROR: {ipath} not found; --render-only needs an existing metrics file.")
        ins = json.loads(ipath.read_text(encoding="utf-8"))
        print(f"Rendering from preserved {ipath} (no re-analysis).")
    else:
        mpath = out_dir / "metrics.json"
        if not mpath.is_file():
            raise SystemExit(f"ERROR: {mpath} not found. Run analyze.py first.")
        metrics = json.loads(mpath.read_text(encoding="utf-8"))
        ins = compute_insights(metrics, cfg)
        ipath.write_text(json.dumps(ins, indent=1, default=str), encoding="utf-8")
        print(f"Wrote {ipath}")

    # Narrative: start from computed defaults, then overlay Claude's prose if present.
    narrative = default_narrative(ins)
    npath = out_dir / "insights_narrative.json"
    if npath.is_file():
        try:
            authored = json.loads(npath.read_text(encoding="utf-8"))
            narrative.update({k: v for k, v in authored.items() if v})
            print(f"Folded in narrative from {npath}")
        except json.JSONDecodeError as e:
            print(f"WARNING: insights_narrative.json is invalid ({e}); using computed defaults.")
    else:
        print("No insights_narrative.json found; using computed default prose "
              "(have Claude write one for richer findings).")

    report = out_dir / "insights.html"
    report.write_text(build_html(ins, narrative, cfg), encoding="utf-8")
    print(f"Wrote {report}")
    if not args.no_open:
        webbrowser.open(report.as_uri())


if __name__ == "__main__":
    main()
