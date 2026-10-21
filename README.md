# AI Coach

A personal AI usage coach for people who use Claude Code and Claude Desktop for knowledge work, not software development.

AI Coach reads your **local** Claude Code / Cowork session logs, works out how you actually use Claude (what you work on, when, how much you delegate, where you get stuck), and has Claude write candid, personalized coaching. You get a clean HTML report that opens in your browser.

**100% local.** Your logs never leave your machine. The analysis is plain Python, and the only "AI" step is Claude, already running in your session, reading a summary of your own data.

## What you get

| Command | Output | Who it's for |
|---|---|---|
| `/coach` | `coach-output/report.html`: scores, strengths, 4 to 6 concrete opportunities, a one-week challenge, plus charts of your usage rhythm, task mix, and tools | **You only.** It quotes short excerpts of your own prompts. |
| `/field-notes` | `coach-output/insights.html`: an analyst-voice research note on what heavy AI agent use looks like, with every number tagged *measured* or *modeled* | **Shareable** (LinkedIn, a blog, a team update). Aggregate numbers only, no prompt content or project names. |

Both commands are namespaced by the plugin, so if another command shares a name you can type `/ai-usage-coach:coach` or `/ai-usage-coach:field-notes` instead.

## Requirements

- **Claude Code** (the CLI, or the Code tab in the Claude desktop app).
- **Python 3.9+** on your PATH as `python` (on Windows, the `py` launcher also works). No extra packages are needed.
- Some history to analyze. Claude Code keeps session logs in `~/.claude/projects` automatically.

## Installation

In Claude Code, run these two commands:

```
/plugin marketplace add <github-owner>/ai-coach
```

```
/plugin install ai-usage-coach@ai-coach
```

Replace `<github-owner>` with the GitHub user or organization that hosts this repo. You can also clone the repo and point the first command at the local folder path instead.

Restart Claude Code (or start a new session) if the commands don't show up right away.

To update later: `/plugin marketplace update ai-coach`.

## Usage

1. Open Claude Code in any folder where you're happy for a `coach-output/` folder to be created. A dedicated folder such as `Documents/AI Coach` works well.
2. Type `/coach` and press Enter.
3. Approve the Python commands when Claude asks. Claude scans your logs, reads the summary, writes your coaching, and opens the report in your browser.

Re-run it every few weeks to track how your habits change. Each run overwrites the previous report.

For the shareable version, type `/field-notes` in the same folder. Read it before you post it.

### Add your claude.ai chat history (optional)

Chats from claude.ai are stored on Anthropic's servers, not your PC, so they need an export:

- **Free, Pro, or Max plans:** claude.ai, then Settings, Privacy, **Export data**. You'll get an emailed download link.
- **Team or Enterprise plans:** only the organization's Primary Owner can export (Organization settings, Data and privacy, **Export Data**), and that export covers the whole organization. Extract your own conversations first.

Put `conversations.json` in a `chat-export` folder inside the folder you run `/coach` from, or pass the path directly: `/coach --chat-export C:\path\to\conversations.json`.

### Personalize the shareable report (optional)

By default `/field-notes` names nobody. To add a byline, your organization, or a persistent-memory agent you run on top of Claude Code, copy [`coach-config.example.json`](coach-config.example.json) to `coach-config.json` in the folder you run the commands from and fill in what applies:

| Key | What it does |
|---|---|
| `author` | Byline on the field-notes report. |
| `organization` | Header and footer of the field-notes report. |
| `agent_name` | Name of your memory agent, if you have one. Adds a "persistent-agent difference" section. |
| `agent_tool_prefix` | The agent's MCP tool prefix as the reports show it, e.g. `memory:` for tools named `mcp__memory__*`. Used to count memory operations. |
| `agent_workspace` | Folder name the agent runs in, so those sessions count as agent work. |

Leave any key blank to skip it. `coach-config.json` is git-ignored.

### Run without Claude (metrics only)

From the repo folder:

```bash
python ai-usage-coach/scripts/analyze.py --out coach-output
```

```bash
python ai-usage-coach/scripts/render.py --out coach-output
```

The report renders with all the charts and a placeholder where the coaching would go. Use `--projects-dir <path>` with `analyze.py` to point at a different log folder.

## How it works

```
~/.claude/projects/*.jsonl ──► analyze.py ──► metrics.json + digest.md
chat-export/conversations.json ─┘                   │
                                   Claude reads digest.md, writes coaching.json
                                                    │
                                     render.py ──► report.html

metrics.json ──► insights.py ──► insights_metrics.json ──► Claude writes insights_narrative.json
                                                    │
                                    insights.py ──► insights.html
```

All numbers are computed by the Python scripts, never by Claude, so the prose can't drift from the data. Task categories come from simple keyword rules in `analyze.py` (`CATEGORY_RULES`), and the time-saved model in the field-notes report uses conservative assumptions you can tune in the `ASSUMPTIONS` block at the top of `insights.py`. Those assumptions are printed in the report.

## Output files

Everything lands in `coach-output/` in the folder you ran the command from. Delete it any time; it's all regenerable.

| File | Contents |
|---|---|
| `metrics.json` | All computed metrics |
| `digest.md` | Compact summary of your usage that Claude reads to coach you (includes prompt excerpts) |
| `coaching.json` | Claude's coaching |
| `report.html` | The private coaching report |
| `insights_metrics.json` | Measured and modeled figures for the field-notes report |
| `insights_narrative.json` | Claude's research-voice prose for the field-notes report |
| `insights.html` | The shareable field-notes report |

## Privacy

- Nothing is uploaded. The scripts make no network calls; the HTML reports load Google Fonts for display only.
- `report.html` and `digest.md` contain short excerpts of your prompts and your workspace names. Treat them as private.
- `insights.html` contains aggregate numbers only, plus whatever names you put in `coach-config.json`. Still, read it before you share it.
- If you fork or contribute to this repo, the `.gitignore` keeps `coach-output/`, `chat-export/`, and `coach-config.json` out of commits.

## Repository layout

```
.claude-plugin/marketplace.json   Marketplace manifest (lets /plugin install find the plugin)
ai-usage-coach/                   The plugin
  .claude-plugin/plugin.json
  commands/coach.md               /coach
  commands/field-notes.md         /field-notes
  scripts/analyze.py              Log parser and metrics
  scripts/render.py               Coaching report renderer
  scripts/insights.py             Field-notes report
  scripts/config.py               Optional coach-config.json loader
coach-config.example.json         Template for personalization
```

## License

MIT. See [LICENSE](LICENSE).
