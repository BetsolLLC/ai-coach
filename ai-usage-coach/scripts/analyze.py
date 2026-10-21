#!/usr/bin/env python3
"""AI Usage Coach - analyzer.

Scans local Claude Desktop / Claude Code session transcripts (~/.claude/projects)
plus an optional claude.ai data export (conversations.json) and produces:

  coach-output/metrics.json   - full computed metrics (consumed by render.py)
  coach-output/digest.md      - compact digest for Claude to read and coach from

Everything stays 100% local. No network calls.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from config import load_config

GAP_CAP_SECONDS = 15 * 60  # cap idle gaps when estimating active time
EXCERPT_LEN = 220

CATEGORY_RULES = [
    ("Data & Spreadsheets", r"\b(spreadsheet|excel|xlsx|csv|pivot|sheet|numbers? (from|in)|tabs?|rows?|columns?|forecast|budget|financ|revenue|metrics)\b"),
    ("Documents & Decks", r"\b(deck|slides?|pptx|powerpoint|presentation|one[- ]pager|docx?|word doc|memo|report|proposal|pdf)\b"),
    ("App Building", r"\b(app|build|code|script|python|html|dashboard|plugin|database|sqlite|api|debug|fix|feature|deploy)\b"),
    ("Memory / Sidekick Agent", r"\b(memory|remember|recall|vault|routines?|journal|log this|note this)\b"),
    ("Automation & Scheduling", r"\b(schedul|automat|cron|recurring|every (day|week|morning)|remind)\b"),
    ("Research & Analysis", r"\b(research|analy[sz]e|compare|summar|investigate|dig (into|through)|find out|review th)\b"),
    ("Email & Comms", r"\b(email|e-mail|message|reply|draft|slack|teams|communicat)\b"),
]


def parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def text_of(content):
    """Extract plain text from a message content (string or block list)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return ""


def has_tool_result(content):
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def clean_excerpt(text, limit=EXCERPT_LEN):
    text = re.sub(r"<[^>]+>", " ", text)          # strip tags / system reminders markup
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "..."
    return text


def apply_agent_name(agent_name):
    """Let mentions of the user's own memory agent (by name) count as agent work."""
    if not agent_name:
        return
    for i, (name, pattern) in enumerate(CATEGORY_RULES):
        if name == "Memory / Sidekick Agent":
            CATEGORY_RULES[i] = (name, pattern.replace(r"(", r"(" + re.escape(agent_name.lower()) + "|", 1))


def categorize(text):
    t = (text or "").lower()
    for name, pattern in CATEGORY_RULES:
        if re.search(pattern, t):
            return name
    return "Other"


def pretty_project(dirname):
    """Turn 'C--Users-...-Desktop-My-Project' into 'My Project'."""
    name = dirname
    for marker in ("-Desktop-", "-Documents-", "-Downloads-"):
        if marker in name:
            name = name.split(marker, 1)[1]
            break
    return name.replace("-", " ").strip() or dirname


def analyze_session(path):
    """Parse one .jsonl transcript into a session summary dict."""
    s = {
        "file": path.name,
        "user_msgs": 0,
        "assistant_msgs": 0,
        "tool_calls": Counter(),
        "models": Counter(),
        "tokens_out": 0,
        "tokens_in": 0,
        "tokens_cache_read": 0,
        "tokens_cache_write": 0,
        "interruptions": 0,
        "sidechain_msgs": 0,
        "entrypoint": None,
        "first_ts": None,
        "last_ts": None,
        "active_seconds": 0,
        "first_user_text": None,
        "user_texts": [],
        "timestamps": [],
        "errors": 0,
    }
    seen_usage_ids = set()
    prev_ts = None

    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return None

    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = parse_ts(obj.get("timestamp"))
            if ts:
                if s["first_ts"] is None or ts < s["first_ts"]:
                    s["first_ts"] = ts
                if s["last_ts"] is None or ts > s["last_ts"]:
                    s["last_ts"] = ts
                if prev_ts is not None:
                    gap = (ts - prev_ts).total_seconds()
                    if 0 < gap:
                        s["active_seconds"] += min(gap, GAP_CAP_SECONDS)
                prev_ts = ts
                s["timestamps"].append(ts)

            if obj.get("isSidechain"):
                if obj.get("type") in ("user", "assistant"):
                    s["sidechain_msgs"] += 1
                continue

            otype = obj.get("type")
            msg = obj.get("message") or {}

            if otype == "user" and msg.get("role") == "user":
                content = msg.get("content")
                if has_tool_result(content):
                    continue
                text = text_of(content)
                if not text.strip():
                    continue
                if obj.get("isMeta"):
                    continue
                if text.startswith("[Request interrupted"):
                    s["interruptions"] += 1
                    continue
                if text.startswith("<") and "system-reminder" in text[:60]:
                    continue
                s["user_msgs"] += 1
                cleaned = clean_excerpt(text)
                if cleaned:
                    s["user_texts"].append(cleaned)
                    if s["first_user_text"] is None:
                        s["first_user_text"] = cleaned
                if s["entrypoint"] is None and obj.get("entrypoint"):
                    s["entrypoint"] = obj.get("entrypoint")

            elif otype == "assistant" and msg.get("role") == "assistant":
                model = msg.get("model")
                content = msg.get("content") or []
                mid = msg.get("id")

                is_new_api_msg = mid and mid not in seen_usage_ids
                if is_new_api_msg:
                    seen_usage_ids.add(mid)
                    s["assistant_msgs"] += 1
                    if model:
                        s["models"][model] += 1
                    usage = msg.get("usage") or {}
                    s["tokens_out"] += usage.get("output_tokens", 0) or 0
                    s["tokens_in"] += usage.get("input_tokens", 0) or 0
                    s["tokens_cache_read"] += usage.get("cache_read_input_tokens", 0) or 0
                    s["tokens_cache_write"] += usage.get("cache_creation_input_tokens", 0) or 0

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            name = block.get("name", "unknown")
                            s["tool_calls"][name] += 1

            elif otype == "system" and obj.get("level") == "error":
                s["errors"] += 1

    if s["first_ts"] is None:
        return None
    return s


def iso_week(dt):
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def shorten_tool(name):
    return name.replace("mcp__", "").replace("__", ":")


def analyze_code_sessions(projects_dir):
    sessions = []
    for proj_dir in sorted(Path(projects_dir).iterdir()):
        if not proj_dir.is_dir():
            continue
        project = pretty_project(proj_dir.name)
        for jf in sorted(proj_dir.glob("*.jsonl")):
            s = analyze_session(jf)
            if s is None:
                continue
            # Skip empty shells (no real user interaction)
            if s["user_msgs"] == 0 and s["assistant_msgs"] == 0:
                continue
            s["project"] = project
            sessions.append(s)
    return sessions


def find_chat_export(explicit, out_dir, plugin_root):
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    for base in (Path.cwd(), out_dir, plugin_root, plugin_root.parent):
        candidates.append(base / "chat-export" / "conversations.json")
        candidates.append(base / "conversations.json")
    for c in candidates:
        try:
            if c and c.is_file():
                return c
        except OSError:
            continue
    return None


def analyze_chat_export(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        return {"error": f"Could not parse {path}: {e}"}
    if not isinstance(data, list):
        return {"error": "Unexpected export format (expected a list of conversations)."}

    convos = []
    by_week = Counter()
    by_hour = Counter()
    for c in data:
        msgs = c.get("chat_messages") or []
        human = [m for m in msgs if m.get("sender") == "human"]
        created = parse_ts(c.get("created_at"))
        if created:
            by_week[iso_week(created)] += 1
            by_hour[created.astimezone().hour] += 1
        first_text = clean_excerpt(human[0].get("text", "")) if human else ""
        convos.append({
            "name": c.get("name") or "(untitled)",
            "created_at": c.get("created_at"),
            "messages": len(msgs),
            "human_messages": len(human),
            "first_text": first_text,
            "category": categorize((c.get("name") or "") + " " + first_text),
        })

    convos.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {
        "source": str(path),
        "total_conversations": len(convos),
        "total_messages": sum(c["messages"] for c in convos),
        "total_human_messages": sum(c["human_messages"] for c in convos),
        "by_week": dict(by_week),
        "by_hour": {str(k): v for k, v in by_hour.items()},
        "categories": dict(Counter(c["category"] for c in convos)),
        "conversations": convos,
    }


def build_metrics(sessions, chat, agent_workspace=""):
    by_week = Counter()
    by_hour = Counter()
    by_weekday = Counter()
    tool_totals = Counter()
    model_tokens = defaultdict(lambda: {"calls": 0, "out": 0, "in_uncached": 0, "cache_read": 0, "cache_write": 0})
    projects = defaultdict(lambda: {
        "sessions": 0, "user_msgs": 0, "tokens_out": 0, "active_seconds": 0,
        "tool_calls": 0, "interruptions": 0, "first": None, "last": None,
        "categories": Counter(), "is_cowork": False,
    })
    categories = Counter()
    session_rows = []

    for s in sessions:
        local_first = s["first_ts"].astimezone()
        by_week[iso_week(local_first)] += 1
        for ts in s["timestamps"][::5] or s["timestamps"]:
            lt = ts.astimezone()
            by_hour[lt.hour] += 1
            by_weekday[lt.weekday()] += 1
        for tool, n in s["tool_calls"].items():
            tool_totals[shorten_tool(tool)] += n
        for model, n in s["models"].items():
            mt = model_tokens[model]
            mt["calls"] += n
        # token attribution: per-session totals to dominant model
        if s["models"]:
            dominant = s["models"].most_common(1)[0][0]
            mt = model_tokens[dominant]
            mt["out"] += s["tokens_out"]
            mt["in_uncached"] += s["tokens_in"]
            mt["cache_read"] += s["tokens_cache_read"]
            mt["cache_write"] += s["tokens_cache_write"]

        is_scheduled = bool(s["first_user_text"] and s["first_user_text"].startswith(
            "This is an automated run of a scheduled task"))
        if is_scheduled:
            cat = "Scheduled Automation (Routines)"
        else:
            cat = categorize(" ".join(s["user_texts"][:5]))
            if agent_workspace and s["project"].lower().startswith(agent_workspace.lower()):
                cat = "Memory / Sidekick Agent"
        categories[cat] += 1

        p = projects[s["project"]]
        p["sessions"] += 1
        p["user_msgs"] += s["user_msgs"]
        p["tokens_out"] += s["tokens_out"]
        p["active_seconds"] += int(s["active_seconds"])
        p["tool_calls"] += sum(s["tool_calls"].values())
        p["interruptions"] += s["interruptions"]
        p["categories"][cat] += 1
        if "cowork" in s["project"].lower() or (s.get("entrypoint") or "").startswith("cowork"):
            p["is_cowork"] = True
        fd = local_first.date().isoformat()
        ld = s["last_ts"].astimezone().date().isoformat()
        p["first"] = min(p["first"] or fd, fd)
        p["last"] = max(p["last"] or ld, ld)

        session_rows.append({
            "scheduled": is_scheduled,
            "project": s["project"],
            "date": local_first.date().isoformat(),
            "start": local_first.strftime("%H:%M"),
            "active_minutes": round(s["active_seconds"] / 60, 1),
            "user_msgs": s["user_msgs"],
            "assistant_msgs": s["assistant_msgs"],
            "tool_calls": sum(s["tool_calls"].values()),
            "top_tools": [shorten_tool(t) for t, _ in s["tool_calls"].most_common(3)],
            "tokens_out": s["tokens_out"],
            "interruptions": s["interruptions"],
            "sidechain_msgs": s["sidechain_msgs"],
            "errors": s["errors"],
            "category": cat,
            "models": list(s["models"].keys()),
            "entrypoint": s.get("entrypoint"),
            "excerpt": s["first_user_text"] or "",
        })

    session_rows.sort(key=lambda r: (r["date"], r["start"]))

    for p in projects.values():
        p["categories"] = dict(p["categories"])

    total_active_h = sum(s["active_seconds"] for s in sessions) / 3600

    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "sessions": len(sessions),
            "scheduled_sessions": sum(1 for r in session_rows if r["scheduled"]),
            "interactive_sessions": sum(1 for r in session_rows if not r["scheduled"]),
            "projects": len(projects),
            "user_messages": sum(s["user_msgs"] for s in sessions),
            "assistant_messages": sum(s["assistant_msgs"] for s in sessions),
            "tool_calls": sum(sum(s["tool_calls"].values()) for s in sessions),
            "tokens_out": sum(s["tokens_out"] for s in sessions),
            "tokens_cache_read": sum(s["tokens_cache_read"] for s in sessions),
            "active_hours": round(total_active_h, 1),
            "interruptions": sum(s["interruptions"] for s in sessions),
            "subagent_messages": sum(s["sidechain_msgs"] for s in sessions),
            "date_range": [
                min(s["first_ts"] for s in sessions).astimezone().date().isoformat(),
                max(s["last_ts"] for s in sessions).astimezone().date().isoformat(),
            ] if sessions else None,
        },
        "by_week": dict(sorted(by_week.items())),
        "by_hour": {str(h): by_hour.get(h, 0) for h in range(24)},
        "by_weekday": {str(d): by_weekday.get(d, 0) for d in range(7)},
        "tools": dict(tool_totals.most_common(25)),
        "models": {m: v for m, v in model_tokens.items()},
        "categories": dict(categories.most_common()),
        "projects": dict(projects),
        "sessions": session_rows,
        "chat": chat,
    }
    return metrics


def fmt_int(n):
    return f"{n:,}"


def build_digest(metrics):
    """Compact markdown digest sized for Claude to read in one pass."""
    t = metrics["totals"]
    lines = []
    lines.append("# AI Usage Coach - data digest")
    lines.append("")
    lines.append("This digest summarizes local Claude Desktop usage (Claude Code + Cowork sessions"
                 + (", plus claude.ai Chat export" if metrics.get("chat") and not metrics["chat"].get("error") else "; no Chat export found")
                 + "). Use it to write coaching.json.")
    lines.append("")
    lines.append("## Totals")
    dr = t.get("date_range") or ["?", "?"]
    lines.append(f"- Period: {dr[0]} to {dr[1]}")
    lines.append(f"- Sessions: {t['sessions']} across {t['projects']} projects "
                 f"({t['interactive_sessions']} interactive, {t['scheduled_sessions']} automated scheduled runs) "
                 f"| active time ~{t['active_hours']} h")
    lines.append(f"- User messages: {fmt_int(t['user_messages'])} | assistant turns: {fmt_int(t['assistant_messages'])} | tool calls: {fmt_int(t['tool_calls'])}")
    lines.append(f"- Output tokens: {fmt_int(t['tokens_out'])} | cache-read tokens: {fmt_int(t['tokens_cache_read'])}")
    lines.append(f"- Interruptions (user hit stop): {t['interruptions']} | subagent messages: {fmt_int(t['subagent_messages'])}")
    lines.append("")
    lines.append("## Projects")
    for name, p in sorted(metrics["projects"].items(), key=lambda kv: -kv[1]["sessions"]):
        kind = " (Cowork)" if p["is_cowork"] else ""
        lines.append(f"- **{name}**{kind}: {p['sessions']} sessions, {p['user_msgs']} user msgs, "
                     f"~{round(p['active_seconds']/3600,1)} h active, {p['interruptions']} interruptions, "
                     f"{p['first']} to {p['last']}")
    lines.append("")
    lines.append("## Top tools")
    lines.append(", ".join(f"{k} ({v})" for k, v in list(metrics["tools"].items())[:15]) or "none")
    lines.append("")
    lines.append("## Models")
    for m, v in metrics["models"].items():
        lines.append(f"- {m}: {v['calls']} api turns, {fmt_int(v['out'])} output tokens")
    lines.append("")
    lines.append("## Heuristic task categories (keyword-based; refine these)")
    for c, n in metrics["categories"].items():
        lines.append(f"- {c}: {n} sessions")
    lines.append("")
    lines.append("## Interactive sessions (chronological; automated scheduled runs excluded)")
    lines.append(f"Note: {t['scheduled_sessions']} automated scheduled-task runs are excluded below but counted in totals/categories.")
    lines.append("Format: date | project | active min | user msgs | tool calls | interruptions | top tools | first prompt excerpt")
    for r in metrics["sessions"][-250:]:
        if r["scheduled"]:
            continue
        tools = "/".join(r["top_tools"]) or "-"
        lines.append(f"- {r['date']} | {r['project']} | {r['active_minutes']}m | {r['user_msgs']}u | "
                     f"{r['tool_calls']}t | {r['interruptions']}x | {tools} | {r['excerpt'][:160]}")
    chat = metrics.get("chat")
    if chat and not chat.get("error"):
        lines.append("")
        lines.append("## Chat (claude.ai export)")
        lines.append(f"- {chat['total_conversations']} conversations, {fmt_int(chat['total_messages'])} messages "
                     f"({fmt_int(chat['total_human_messages'])} from user)")
        lines.append("### Recent conversations")
        for c in chat["conversations"][:120]:
            d = (c.get("created_at") or "")[:10]
            lines.append(f"- {d} | {c['human_messages']}u/{c['messages']} | {c['name'][:70]} | {c['first_text'][:120]}")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Analyze local Claude usage logs.")
    ap.add_argument("--projects-dir", default=str(Path.home() / ".claude" / "projects"))
    ap.add_argument("--chat-export", default=None, help="Path to claude.ai conversations.json export")
    ap.add_argument("--out", default="coach-output", help="Output directory")
    args = ap.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    plugin_root = Path(__file__).resolve().parent.parent
    cfg = load_config(out_dir)
    apply_agent_name(cfg["agent_name"])

    projects_dir = Path(args.projects_dir)
    if not projects_dir.is_dir():
        print(f"ERROR: projects dir not found: {projects_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {projects_dir} ...")
    sessions = analyze_code_sessions(projects_dir)
    print(f"  {len(sessions)} sessions parsed.")

    chat_path = find_chat_export(args.chat_export, out_dir, plugin_root)
    chat = None
    if chat_path:
        print(f"Found Chat export: {chat_path}")
        chat = analyze_chat_export(chat_path)
        if chat.get("error"):
            print(f"  WARNING: {chat['error']}")
    else:
        print("No claude.ai Chat export found (drop conversations.json into a 'chat-export' folder to include Chat).")

    metrics = build_metrics(sessions, chat, cfg["agent_workspace"])

    mpath = out_dir / "metrics.json"
    mpath.write_text(json.dumps(metrics, indent=1, default=str), encoding="utf-8")
    dpath = out_dir / "digest.md"
    dpath.write_text(build_digest(metrics), encoding="utf-8")

    print(f"Wrote {mpath}")
    print(f"Wrote {dpath}")
    print("Next: have Claude read digest.md and write coaching.json, then run render.py.")


if __name__ == "__main__":
    main()
