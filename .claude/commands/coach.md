---
description: Analyze my local Claude usage logs, write personalized coaching, and open the AI Usage Coach report
allowed-tools: Bash, PowerShell, Read, Write
---

This repo was cloned and opened directly, not installed as a plugin. Read `ai-usage-coach/commands/coach.md` in this repo and follow it exactly, with two adjustments:

- Wherever it says `${CLAUDE_PLUGIN_ROOT}`, use the `ai-usage-coach` folder in this repo instead (for example `python ai-usage-coach/scripts/analyze.py --out coach-output`).
- Ignore its YAML front matter; these instructions replace it.

Pass through any arguments the user gave after the command: $ARGUMENTS
