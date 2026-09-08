// The one table on the receiving end of the Lens intake sharing step
// (intake goal G11). A row is exactly what G9 allows the payload to be:
// the chosen answers, the optional project link, a timestamp, and the
// Lens version. Convex adds its own `_id` and `_creationTime` to every
// row automatically; nothing else is stored.
//
// There is deliberately NO email field. The newsletter signup is a
// separate choice with a separate destination (G9/G10) — an email
// address must never be able to enter this table, so the schema does
// not give it a place to land.

import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  intake_submissions: defineTable({
    // Question id -> the option the person chose. Which ids and options
    // are acceptable is enforced by the submitIntake mutation in
    // intake.ts against its closed lists; the schema keeps the shape.
    answers: v.record(v.string(), v.string()),
    // Present only when the person said their system came from an
    // open-source project and gave a link. Bounded and checked in
    // intake.ts.
    project_link: v.optional(v.string()),
    // When Lens sent the payload, as an RFC3339 timestamp string,
    // e.g. "2026-09-08T14:03:00Z". Checked in intake.ts.
    submitted_at: v.string(),
    // The Lens release that produced the payload.
    lens_version: v.string(),
  }),
});
