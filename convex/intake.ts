// The receiving function for the Lens intake sharing step (intake goal
// G11). It accepts exactly the closed answer set G9 describes and
// refuses everything else: an unknown question id, an option outside a
// question's list, an oversized or non-https project link, a link
// without the answer that permits one, or a malformed timestamp.
//
// The closed lists below are the contract. The Python contract test
// (tests/share/test_intake_contract.py) parses this file and fails if a
// question id or option value here drifts from the pinned set — keep
// the two in step deliberately, never by editing one side alone.

import { v } from "convex/values";
import { mutation } from "./_generated/server";

// Every question whose answer is a choice from a fixed list, and the
// full list for each. "not-sure" is always acceptable (goal G2).
export const OPTION_QUESTIONS = {
  "dex-installed": ["yes", "no", "not-sure"],
  "customisation": ["barely-touched", "quite-a-bit", "unrecognisable", "not-sure"],
  "first-installed": ["last-week", "last-month", "last-3-months", "at-launch", "not-sure"],
  "last-update": ["last-week", "last-month", "longer-ago", "never", "not-sure"],
  "from-open-source": ["yes", "no-built-it-myself", "not-sure"],
} as const;

// The one question whose answer is free text: the link to the
// open-source project the person built from. It travels in the
// `project_link` field, is only allowed when "from-open-source" was
// answered "yes", must start with https://, and is bounded in length.
export const LINK_QUESTION_ID = "project-link";
export const PROJECT_LINK_MAX_LENGTH = 300;
export const PROJECT_LINK_PREFIX = "https://";

// RFC3339 timestamp shape, e.g. "2026-09-08T14:03:00Z" or
// "2026-09-08T14:03:00.123+02:00".
const RFC3339 =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

export const submitIntake = mutation({
  args: {
    answers: v.record(v.string(), v.string()),
    project_link: v.optional(v.string()),
    submitted_at: v.string(),
    lens_version: v.string(),
  },
  handler: async (ctx, args) => {
    for (const [questionId, option] of Object.entries(args.answers)) {
      const options: readonly string[] | undefined =
        OPTION_QUESTIONS[questionId as keyof typeof OPTION_QUESTIONS];
      if (options === undefined) {
        throw new Error(`Refused: "${questionId}" is not an intake question.`);
      }
      if (!options.includes(option)) {
        throw new Error(
          `Refused: "${option}" is not an option for "${questionId}".`,
        );
      }
    }

    if (args.answers["dex-installed"] === undefined) {
      throw new Error(
        'Refused: every intake payload answers "dex-installed".',
      );
    }

    if (args.project_link !== undefined) {
      if (args.answers["from-open-source"] !== "yes") {
        throw new Error(
          'Refused: a project link is only accepted when "from-open-source" is "yes".',
        );
      }
      if (args.project_link.length > PROJECT_LINK_MAX_LENGTH) {
        throw new Error(
          `Refused: the project link is longer than ${PROJECT_LINK_MAX_LENGTH} characters.`,
        );
      }
      if (!args.project_link.startsWith(PROJECT_LINK_PREFIX)) {
        throw new Error(
          `Refused: the project link must start with ${PROJECT_LINK_PREFIX}`,
        );
      }
    }

    if (!RFC3339.test(args.submitted_at)) {
      throw new Error(
        "Refused: submitted_at must be an RFC3339 timestamp.",
      );
    }

    await ctx.db.insert("intake_submissions", {
      answers: args.answers,
      project_link: args.project_link,
      submitted_at: args.submitted_at,
      lens_version: args.lens_version,
    });
  },
});
