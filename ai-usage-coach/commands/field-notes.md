---
description: Generate a public, shareable "AI agent field notes" research report from my local Claude usage (analyst voice, aggregate only, safe to post)
allowed-tools: Bash, PowerShell, Read, Write
---

You are acting as a **research analyst**, not a marketer. The user wants a **publicly shareable** report (for a LinkedIn post, a company blog, or social) that treats their own real-world use of Claude, and of any persistent-memory agent they run on top of it, as a small **field study**. The model is Anthropic's own "how we use Claude" writeups: credible, data-grounded, openly caveated, the opposite of a sales pitch. The audience is tech-savvy, leadership-level people interested in relying heavily on AI agents.

This is the **outward** companion to `/coach` (which is private and quotes prompts). This report is **aggregate-only and contains no prompt excerpts, no client names, and no raw project names**. The only names allowed are the ones in the user's optional `coach-config.json` (`author`, `organization`, `agent_name`); if a field is blank, don't name it.

Run this pipeline:

## Step 1 — Refresh metrics

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/analyze.py" --out coach-output
```

(If the user passed a chat export path after the command, append `--chat-export <path>`.) This refreshes `coach-output/metrics.json`.

## Step 2 — Compute the deterministic insight metrics

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/insights.py" --out coach-output --no-open
```

This writes `coach-output/insights_metrics.json` — **all numbers, computed deterministically** and split into `measured` (straight from the logs) and `modeled` (estimates from stated assumptions). It also renders a first pass of `insights.html` using built-in default prose.

## Step 3 — Write the research narrative

Read `coach-output/insights_metrics.json` in full. **Every figure you cite must come from that file** — never invent or round numbers into something punchier. Then write `coach-output/insights_narrative.json` with EXACTLY this schema (valid JSON, no trailing commas):

```json
{
  "title": "<a research-note title, not a slogan>",
  "dek": "<1-2 sentence standfirst explaining what was studied and why>",
  "abstract": "<3-4 sentence neutral summary: window, sample size, what we looked for>",
  "findings": [
    {
      "label": "<short finding title>",
      "stat": "<the headline number for this finding, taken from insights_metrics.json>",
      "finding": "<what the data shows, with the specific numbers>",
      "interpretation": "<what it means for someone relying on AI agents — the 'so what'>",
      "basis": "measured | modeled"
    }
  ],
  "agent_thesis": "<only if insights_metrics.json has agent.configured = true: a paragraph on the incremental benefit of a persistent agent over a stateless assistant (memory across sessions, scheduled autonomy, fewer redos), grounded in the agent_session_share / agent_token_share / autonomous_sessions / memory_ops figures. Otherwise an empty string.>",
  "caveats": "<honest limitations: one operator, one window; 'time saved' is modeled not measured; interruption rate is an imperfect quality proxy; shared as research not a product claim>",
  "pull_quotes": ["<3 short, screenshot-ready lines using real numbers>"]
}
```

Rules:
- **5–7 findings.** Lead with the strongest *measured* facts (autonomy ratio, actions-per-instruction amplification, run-to-completion rate, agent share); include at least one *modeled* finding (time returned) clearly tagged `modeled`.
- **Analyst voice, not marketing.** No superlatives that the data can't support, no exclamation marks, no "revolutionary." Findings and interpretation, calmly stated. A skeptical CTO is the reader.
- **Aggregate only.** No prompt content, no customer names, no individual project names. Only the author, organization, and agent names from `coach-config.json` may appear.
- **Honesty wins with this audience.** Keep the conservative framing of the modeled time-saved (it's a floor). Don't strip the caveats.
- Match the figures exactly to `insights_metrics.json`. If a number isn't in that file, don't claim it.

## Step 4 — Render and open

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/insights.py" --out coach-output
```

This folds your `insights_narrative.json` into `coach-output/insights.html` and opens it in the browser.

## Step 5 — Summarize

End with a short chat summary: the title, the 2–3 strongest measured findings (with numbers), the modeled time-returned band, and the three pull-quotes ready to paste. Remind the user that the report is aggregate-only and safe to share, that the modeled figures are a conservative floor with assumptions printed in the report, and that they can tune those assumptions in `scripts/insights.py` (the `ASSUMPTIONS` block) if they want a different basis. If they have a branding skill installed, mention it can turn the report into a branded one-pager or deck.
