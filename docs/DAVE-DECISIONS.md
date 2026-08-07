# Dave's task board — Outward Dex

Things only Dave can do. Everything else is the build team's problem.

Plain language on purpose. The formal versions live in `docs/handoff/HANDOFF.md`
Section 6 (D0–D9) — this file is the working list.

Last updated: 2026-08-07

---

## Do now (long lead time)

### 1. Find the pilot people — 6 to 8 of them
**Dave owns this.** In progress as of 2026-08-07.

Who qualifies:
- On a Mac, using Claude Code with a local folder of their own setup
- Uses it at least weekly, for about a month or more
- Has at least one *real, repeated* job it helps with — not a demo
- Willing to let it read those folders, read-only
- Technical ability is **not** required

The mix matters: **4–5 people who don't use Dex at all**, and 2–3 who do (or who
have heavily customised Claude Code). The whole point is proving this works for
people outside the Dex world.

Why it's urgent despite the code not being ready: recruiting takes weeks, and the
build can't start the pilot without them.

---

## Do before anyone's real machine is touched

### 3. Get the pilot consent terms reviewed
**Blocks:** the pilot starting.

Somebody needs to look over the consent wording, the data-deletion promise, what
happens if something goes wrong on a participant's machine, and the "you can
withdraw anything, any time" disclosures. Doesn't need a law firm — it needs a
decision on *who reviews it and to what standard*, recorded before anyone is
enrolled.

### 4. Decide who signs off the safety gates
**Blocks:** letting the product make any automatic change on a real person's machine.

Six safety gates have to be proven before that happens. Somebody independent has
to review the evidence and say "yes, that holds." Options: a second Fable review,
an outside reviewer, or Dave. Needs to be recorded, not assumed.

### 5. Name an owner for each unresolved risk
Any risk left open at the end needs a name against it. With a team of one, the
realistic answer is probably "Dave owns all of them" — but that has to be stated
explicitly rather than left blank.

---

## Later / smaller

- **Should the repo be public or private during the build?** Currently private.
- **Schedule the Dex Core side of the catalogue work.** Dave approved this on
  Dex#347 already; it needs slotting into Core's release process, since it lives
  outside this codebase.

---

## Already decided — no action needed

| Decision | Answer | Where |
| --- | --- | --- |
| Accept the six safety gates and seven hardening items as binding | Yes | Dex#347, 2026-08-07 11:19 |
| Two-stage handoff (this pack authorises the build; the pilot pack authorises expansion) | Yes | Dex#347, 2026-08-07 11:19 |
| Raw personal material in shared cards | Dropped for the pilot | Dex#347, 2026-08-07 12:06 |
| Pilot success threshold | Strict majority: 6→4, 7→4, 8→5 | Dex#347, 2026-08-07 12:06 |
| Who moderates shared cards | AI-led review, Dave gives final one-click approval | Dex#347, 2026-08-07 12:10 |
| Catalogue generator + signing in Core | Approved | Dex#347, 2026-08-07 12:06 |
| Does diagnosis phone out to a cloud AI? | No — fully local for now. Revisit before the job-proposal step ships | Chat, 2026-08-07 |
| **Public name** | **Dex Lens** | Chat, 2026-08-07 |

### On the name

**Dex Lens** is the public name. "Dex Capability Exchange" stays as the internal
/ formal name for the contribution machinery; "Outward Dex" is retired.

Not yet done, and needed before any user-facing copy is written:

- Decide how the name is used in the one trusted command the person types.
- Check the vocabulary table in `HANDOFF.md` Section 1.5 still reads correctly
  with "Lens" in play — nothing there conflicts today, but UI copy will touch it.
