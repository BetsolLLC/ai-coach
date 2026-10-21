---
description: Generate a public, shareable "AI agent field notes" research report from my local Claude usage (analyst voice, aggregate only, safe to post)
allowed-tools: Bash, PowerShell, Read, Write
---

This repo was cloned and opened directly, not installed as a plugin. Read `ai-usage-coach/commands/field-notes.md` in this repo and follow it exactly, with two adjustments:

- Wherever it says `${CLAUDE_PLUGIN_ROOT}`, use the `ai-usage-coach` folder in this repo instead (for example `python ai-usage-coach/scripts/analyze.py --out coach-output`).
- Ignore its YAML front matter; these instructions replace it.

Pass through any arguments the user gave after the command: $ARGUMENTS
