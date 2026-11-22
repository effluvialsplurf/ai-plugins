# Loop state: [FEATURE]

Re-read this file first after a compaction or restart; it is the loop's memory. Update it at every stage change,
every dispatch and every decision. Keep it short: one line per event.

- **Stage:** [plan | build T<n> | task review T<n> | fix T<n> | whole-branch review | PR open | waiting on review | done]
- **Branch / worktree:** [branch] at [worktree path]
- **Design input:** [egm <path to docs/designs/*.md> [report <path to egm review report>], or blank for the plugin's own design stage]
- **Plan:** [path to plan and task files]
- **PR:** [url, or none yet]
- **Watchers running:** [stall-watch registry path / watch-pr seen-file and pid, or none]
- **Waiting on:** [which agent or run (label, log path, .done file) / the user / CI, or nothing]
- **Next action:** [one concrete step]

## Decisions

Rulings that bind later work (scope calls, interface choices, findings accepted as defensible), each with the date.

- [YYYY-MM-DD] [decision and why]

## Log

One line per event, newest last: `YYYY-MM-DD HH:MM  <event>` (dispatch with label, report received, review verdict,
fix commit, push, PR comment handled).

- [YYYY-MM-DD HH:MM] [event]
