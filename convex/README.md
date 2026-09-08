# The intake receiving end

This folder is the receiving side of the Lens intake sharing step: when a
person finishes a Lens run and says yes to sharing their intake answers with
Dave, the answers land in a Convex table. Two source files define all of it:

- `schema.ts` — one table, `intake_submissions`. Each row holds the chosen
  answers, the optional project link, a timestamp, and the Lens version.
  There is no email field on purpose: newsletter signup is a separate choice
  with a separate destination, and an email address has no place to land here.
- `intake.ts` — one function, `submitIntake`. It checks every answer against
  the fixed question and option lists and refuses anything outside them, then
  inserts one row.

The contract test `tests/share/test_intake_contract.py` pins the question ids
and option values in these files, so a change here fails the Python suite
until both sides are updated together.

## Deploying to your own Convex account

You need Node.js. From this directory (`convex/`):

1. `npx convex dev` — the first run asks you to log in to Convex in the
   browser and create (or pick) a project under your own account. This is
   where the deployment gets tied to your account, not to anything in this
   repository.
2. `npx convex deploy` — pushes `schema.ts` and `intake.ts` to that project's
   production deployment.

After deploying, the Convex dashboard shows the deployment's URL. Submissions
appear in the dashboard under the `intake_submissions` table.

## Where the URL goes on the Lens side

Exactly one place: the environment variable `DEX_LENS_INTAKE_URL`, set on the
machine that runs Lens. Lens reads that variable when the person agrees to
share; if it is unset, there is nowhere to send and nothing is sent. There is
no other configuration mechanism.

## What is not in this repository

No deployment key, no access token, and no deployment URL — not in these
files, not in CI, not in any test. The files here are the table definition
and the checking function only; everything that identifies your Convex
account stays in your Convex login and in the `DEX_LENS_INTAKE_URL` variable
on your own machine.
