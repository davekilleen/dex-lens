# Customised Claude Host

This fixture represents a user who has already customised their AI workspace with
local instructions and a hand-written skill.

The assistant may use local skills under `.claude/skills/`. It must keep all
analysis inside the inspected directory and must not make network calls, send
messages, install software, or edit files unless the user explicitly asks.

## Operating rhythm

- Build a daily plan from current notes.
- Summarise meeting follow-ups into next actions.
- Flag weak evidence instead of guessing.
