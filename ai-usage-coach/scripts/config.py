"""AI Usage Coach - optional personalization.

Everything works with no config at all. To personalize the reports, put a
coach-config.json in the folder you run /coach from (next to coach-output/).
See coach-config.example.json in the repo root for the full set of keys.
"""

import json
import sys
from pathlib import Path

CONFIG_NAME = "coach-config.json"

DEFAULTS = {
    # Shown in the byline of the shareable field-notes report. Blank = omitted.
    "author": "",
    # Shown in the kicker/footer of the shareable report. Blank = omitted.
    "organization": "",
    # Optional persistent-memory agent you run on top of Claude Code (an MCP
    # server that stores memory across sessions). Leave blank if you don't have one.
    "agent_name": "",
    # MCP tool prefix for that agent, as analyze.py prints tools: "<server>:".
    # Example: tools named mcp__memory__save appear as "memory:save", so use "memory:".
    "agent_tool_prefix": "",
    # Workspace (project folder) name the agent lives in, if it has a dedicated one.
    # Sessions in workspaces starting with this name count as agent work.
    "agent_workspace": "",
}


def load_config(out_dir=None):
    """Merge coach-config.json (cwd first, then the output folder's parent) over DEFAULTS."""
    cfg = dict(DEFAULTS)
    candidates = [Path.cwd() / CONFIG_NAME]
    if out_dir:
        candidates.append(Path(out_dir).resolve().parent / CONFIG_NAME)
    for c in candidates:
        if c.is_file():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"WARNING: could not read {c} ({e}); using defaults.", file=sys.stderr)
                break
            cfg.update({k: v for k, v in data.items() if k in DEFAULTS and isinstance(v, str)})
            break
    return cfg
