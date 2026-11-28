---
name: context-costs
description: Use when dispatching subagents, resuming an agent, running a long Claude Code session, writing agent definitions, or when usage runs out faster than expected. How context and the prompt cache drive cost, and the rules that keep both small. Applies to any multi-agent or long-running work, not only the build loop.
---

# Context and cache costs

Practical rules for any workflow where an AI coding harness calls tools many times or delegates work to subagents.

> **Harness & model portability:** The core formula (`cost ≈ calls × average context`) and Rules 1–12 apply to **every**
> model family and harness (Claude, Gemini, OpenAI/GPT, open-weights/local). The 5-minute vs. 1-hour cache TTL notes and
> the `scripts/loop_ledger.py` / `scripts/context_breakdown.py` transcript scripts below are Claude Code / Anthropic
> specific — on other providers, map them to your provider's prefix/context caching (e.g., OpenAI automatic prefix
> caching, Gemini implicit/explicit context caching, or local KV-cache reuse) and your harness's usage logs.

## The one formula

Every call an agent makes re-reads its whole context. Most of that re-read is a cache read, which is cheap per token
but compounds across every turn, quickly becoming the dominant share of total cost.

> cost ≈ number of calls × average context size

A long-lived builder or planner making dozens of calls in a bloated context costs far more than the code it writes.
Planners and builders typically dominate total loop cost while review layers remain a small fraction — cut cost in the
workers, not the reviews.

Tool output is rarely the main thing filling a context; most growth comes from an agent's own writes, edits, and
reasoning carried forward across turns. So **fewer calls and fresh contexts pay more than quieter tool output alone.**

## How the prompt cache works, in practice

- A cached prefix is read back at about a tenth of the price of sending it fresh. Writing it costs a little more than
  fresh (1.25x for the 5-minute cache, 2x for the 1-hour cache).
- **A subagent's cache lasts 5 minutes by default; the main session's lasts an hour.** If a subagent waits longer than
  5 minutes and then makes a call, its whole context is written again at full price before it does anything.
- That is why the main session is the right place to orchestrate. Nested "feature controller" subagents that wait on
  their own subagents routinely lose their 5-minute cache between wake-ups and pay to re-write their entire context,
  whereas the main session's 1-hour cache stays warm across waits.
- If a subagent must orchestrate, give it a longer cache: `subagentPromptCacheTtl` in `settings.json` (or
  `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`), or `experimental.cacheTtl: 1h` in that agent's definition (Claude Code
  2.1.248+). Values are `5m` or `1h`. Per the Claude Code prompt-caching docs, the 1-hour setting is ignored for
  subagents on a Claude subscription using usage credits, so check your plan, and check with `scripts/context_breakdown.py`
  that the "after >5 min gaps" figure fell.

## Rules

1. **Fresh agent per phase.** Explore in one agent, write in another, fix in a third. Hand over a file, not a
   conversation. One agent that explores, writes, fixes and verifies carries everything it read into every later call.
2. **Resume an agent only while its cache is hot**: within 5 minutes of its last call, and only for a small follow-up.
   After that a resume re-writes its whole context first. A fix round on a bloated agent costs several times what a
   fresh agent with the finding and the diff costs.
3. **But give the fresh agent a handoff.** Every builder ends its report with a short "For whoever fixes this" section:
   files touched, the tests that cover them, the exact commands, what not to re-read. One fresh fixer sent in without it
   re-explored everything and cost more than the job it was fixing. Write the handoff at the end of the build, not when
   the fix arrives: by then the builder's cache has expired and waking it costs a full re-read.
4. **Lean agent definitions.** An agent with every tool and connector attached starts with a large system/tool prompt
   before it reads anything, and pays for that on every call. List only the tools the seat needs (e.g.
   `tools: Bash, Read, Edit, Write, Grep, Glob` for a builder). Most of the overhead comes from unused built-in tool
   definitions and skill lists. Agent definitions load when a session starts, so restart after changing one.
5. **Pin the model by its full id** where your harness lets you set one (not an alias) so an alias cannot quietly
   resolve to an older model.
6. **Batch.** All of a step's reads in one message, all of its edits in one message. Each round trip is another
   full-context re-read.
7. **Scripts for anything mechanical.** Build, restart, test gate, PR chores: one script that prints one line on
   success and only the failure otherwise. A controller should never spend a chain of Bash/git calls repeating a recipe.
8. **Quiet checks.** A passing test suite should cost one line of context.
9. **The controller stays thin.** It takes back status, commits and concerns from each agent, never the full output.
   Start it with `claude --autocompact <tokens>` (for example `300k`; check `claude --help` on your version) so it
   compacts before its context gets expensive. Compaction is safe when state lives in a file and the project CLAUDE.md
   says to read that file first, since CLAUDE.md is re-read after a compaction.
10. **Split big writers.** A planner that reads the whole codebase and then writes a full multi-task plan carries
    everything it read on every turn. Have an explorer write a skeleton and a pack of the code the tasks need, then one
    fresh writer per task.
11. **Effort is a cost lever.** About half of an agent's context growth is its own retained thinking. Lower effort on a
    seat is untested on these loops; if you try it, watch the review findings.
12. **Mind the wait.** Any agent that waits more than a few minutes on another job can lose its cache. Start long jobs
    so they notify the session when they exit, rather than having an agent sit and poll.

## Measure it

Two scripts in this plugin read Claude Code's own session transcripts (under `~/.claude/projects/`):

- `scripts/loop_ledger.py` (in this plugin): cost by job group (jobs, calls per job, context at first and last
  call, cache writes after long waits).
- `scripts/context_breakdown.py` (in this plugin): what one job's context is made of.

Arguments are in each script's header. The scale they print is weighted tokens (fresh + 1.25 x cache write + 0.1 x
cache read + 5 x output); read it as relative cost, not dollars. Run them before and after a change. Change one thing
at a time, and decide in advance what result means revert.
