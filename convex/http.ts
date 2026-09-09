// The one HTTP doorway for the Lens intake sharing step.
//
// Lens sends a plain JSON POST to the URL in DEX_LENS_INTAKE_URL. Convex
// mutations are not reachable by plain POST, so this route is where that
// POST lands: it checks the body carries exactly the four contract fields,
// translates the absent project link (Lens serializes it as JSON null;
// the mutation takes it as absent), and hands the result to submitIntake,
// which enforces the closed question and option lists.
//
// Deployed, the route lives at https://<deployment>.convex.site/lens/intake
// — note .convex.site, the HTTP-actions host, not .convex.cloud.
//
// The Python contract test (tests/share/test_intake_contract.py) parses
// this file and fails if the route path, method, or null handling drifts.

import { httpRouter } from "convex/server";
import { api } from "./_generated/api";
import { httpAction } from "./_generated/server";

const PAYLOAD_FIELDS = new Set([
  "answers",
  "project_link",
  "submitted_at",
  "lens_version",
]);

function jsonResponse(body: Record<string, unknown>, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const http = httpRouter();

http.route({
  path: "/lens/intake",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    let body: Record<string, unknown>;
    try {
      body = await request.json();
    } catch {
      return jsonResponse({ error: "Refused: the body must be JSON." }, 400);
    }
    for (const key of Object.keys(body)) {
      if (!PAYLOAD_FIELDS.has(key)) {
        return jsonResponse(
          { error: `Refused: "${key}" is not an intake payload field.` },
          400,
        );
      }
    }
    const answers = body.answers;
    if (typeof answers !== "object" || answers === null || Array.isArray(answers)) {
      return jsonResponse(
        { error: "Refused: answers must be an object of question ids to options." },
        400,
      );
    }
    for (const [questionId, option] of Object.entries(answers)) {
      if (typeof option !== "string") {
        return jsonResponse(
          { error: `Refused: the answer to "${questionId}" must be a string.` },
          400,
        );
      }
    }
    if (typeof body.submitted_at !== "string" || typeof body.lens_version !== "string") {
      return jsonResponse(
        { error: "Refused: submitted_at and lens_version must be strings." },
        400,
      );
    }
    const project_link =
      body.project_link === null || body.project_link === undefined
        ? undefined
        : body.project_link;
    if (project_link !== undefined && typeof project_link !== "string") {
      return jsonResponse(
        { error: "Refused: project_link must be a string when present." },
        400,
      );
    }
    try {
      await ctx.runMutation(api.intake.submitIntake, {
        answers: answers as Record<string, string>,
        project_link,
        submitted_at: body.submitted_at,
        lens_version: body.lens_version,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Refused.";
      return jsonResponse({ error: message }, 400);
    }
    return jsonResponse({ ok: true }, 200);
  }),
});

export default http;
