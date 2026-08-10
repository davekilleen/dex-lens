"""Local-only HTML views for the M3 read-only concierge journey.

The views are intentionally boring HTML: no scripts, external resources,
browser storage, network APIs, sockets, or analytics.  Dynamic values are
escaped at the final rendering boundary and every form carries the supplied
CSRF token so the transport can enforce its own session policy.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable

from capability_exchange.capmap.model import CapabilityMap
from capability_exchange.capmap.render import render_capability_map as render_map_markdown
from capability_exchange.concierge.journey import (
    CollectionFallback,
    ConciergeJourney,
    ConciergeStage,
    FallbackEvidence,
    FallbackMode,
    PermissionMetadata,
)
from capability_exchange.evidence import EvidenceLevel
from capability_exchange.jobs import InspectionJob

__all__ = [
    "render_capability_map",
    "render_capability_map_view",
    "render_collecting",
    "render_fallback",
    "render_fallback_view",
    "render_job_map",
    "render_job_map_view",
    "render_adaptation",
    "render_adaptation_view",
    "render_journey",
    "render_permission",
    "render_permission_view",
]


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _document(title: str, body: str) -> str:
    """Wrap trusted static markup and escaped dynamic content in one document."""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_escape(title)} - Dex Lens</title>
  <style>
    :root {{ color-scheme: light; --ink: #161616; --muted: #5f6468;
      --line: #d9dddf; --paper: #fbfcfc; --accent: #0f766e; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink);
      font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; }}
    main {{ width: min(920px, calc(100vw - 32px)); margin: 48px auto; }}
    h1 {{ font-size: 2rem; line-height: 1.15; margin: 0 0 16px; }}
    h2 {{ font-size: 1.25rem; margin: 28px 0 12px; }}
    p, li {{ color: var(--muted); line-height: 1.55; }}
    .panel {{ border: 1px solid var(--line); border-radius: 8px; padding: 20px;
      margin: 16px 0; background: #fff; }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 20px; }}
    button {{ border: 1px solid #0b4f4a; background: var(--accent); color: white;
      border-radius: 6px; padding: 10px 14px; font: inherit; cursor: pointer; }}
    button.secondary {{ background: white; color: #0b4f4a; }}
    label {{ display: block; margin: 12px 0; color: var(--ink); }}
    input, textarea, select {{ display: block; width: 100%; margin-top: 5px;
      border: 1px solid var(--line); border-radius: 4px; padding: 8px; font: inherit; }}
    textarea {{ min-height: 70px; }}
    code, pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    .muted {{ color: var(--muted); }}
  </style>
</head>
<body><main>{body}</main></body>
</html>"""


def _csrf(csrf_token: str) -> str:
    return f'<input type="hidden" name="csrf_token" value="{_escape(csrf_token)}">'


def _list(values: Iterable[object], *, empty: str = "None declared") -> str:
    items = "".join(f"<li>{_escape(value)}</li>" for value in values)
    return f"<ul>{items or f'<li>{_escape(empty)}</li>'}</ul>"


def render_permission(metadata: PermissionMetadata, csrf_token: str) -> str:
    """Render the unscanned permission screen with the complete boundary."""

    local = "Yes — evidence stays on this device" if metadata.local_only else "No"
    offline = "Yes" if metadata.offline_capable else "No"
    catalog = (
        "No catalog is available or required"
        if metadata.no_catalog
        else "A verified catalog is available"
    )
    body = f"""
      <h1>Inspection permission</h1>
      <div class="panel">
        <p><strong>Nothing has been scanned yet. Nothing has been read yet.</strong>
        This screen is shown before
        the adapter can inspect anything.</p>
        <h2>Adapter</h2>
        <p>{_escape(metadata.adapter_id)} · version {_escape(metadata.adapter_version)}</p>
        <h2>Exact approved roots</h2>
        {_list(metadata.approved_roots)}
        <h2>Exact approved artifacts</h2>
        {_list(metadata.approved_artifacts)}
        <h2>Explicit exclusions — never read</h2>
        {_list(metadata.exclusions)}
        <h2>Data boundary</h2>
        <ul>
          <li>Local only: {_escape(local)}</li>
          <li>Works without a network connection: {_escape(offline)}</li>
          <li>Catalog: {_escape(catalog)}</li>
        </ul>
        <p><strong>Next action:</strong> {_escape(metadata.next_action)}</p>
        <form method="post" action="/approve">
          {_csrf(csrf_token)}
          <div class="actions">
            <button type="submit">Approve read-only inspection</button>
            <button class="secondary" type="submit" formaction="/decline">Decline and leave</button>
          </div>
        </form>
      </div>
    """
    return _document("Inspection permission", body)


def _job_form(job: InspectionJob, csrf_token: str) -> str:
    job_id = _escape(job.job_id)
    return f"""
      <div class="panel">
        <form method="post" action="/jobs/edit">
          {_csrf(csrf_token)}
          <input type="hidden" name="job_id" value="{job_id}">
          <label>Title<input name="title" value="{_escape(job.title)}"></label>
          <label>Situation<textarea name="situation">{_escape(job.situation)}</textarea></label>
          <label>Desired outcome<textarea
            name="desired_outcome">{_escape(job.desired_outcome)}</textarea>
          </label>
          <div class="actions"><button type="submit">Save draft</button></div>
        </form>
        <form method="post" action="/jobs/discard">
          {_csrf(csrf_token)}
          <input type="hidden" name="job_id" value="{job_id}">
          <button class="secondary" type="submit">Discard this draft</button>
        </form>
        <form method="post" action="/jobs/confirm">
          {_csrf(csrf_token)}
          <input type="hidden" name="job_id" value="{job_id}">
          <h3>Confirm this job as a Success Contract</h3>
          <label>Success evidence<textarea name="success_evidence" required></textarea></label>
          <label>Privacy limits<textarea name="privacy_limits"></textarea></label>
          <label>Approval limits<textarea name="approval_limits"></textarea></label>
          <label>Autonomy limits<textarea name="autonomy_limits"></textarea></label>
          <label>Importance<select name="importance">
            <option value="low">Low</option><option value="medium" selected>Medium</option>
            <option value="high">High</option>
          </select></label>
          <label>Cadence<select name="cadence">
            <option value="on-demand">On demand</option><option value="daily">Daily</option>
            <option value="weekly" selected>Weekly</option><option value="monthly">Monthly</option>
            <option value="irregular">Irregular</option>
          </select></label>
          <div class="actions"><button type="submit">Confirm this job</button></div>
        </form>
      </div>
    """


def render_job_map(jobs: Iterable[InspectionJob], csrf_token: str) -> str:
    """Render editable inferred/manual drafts with full confirmation fields."""

    drafts = tuple(jobs)
    rendered = "".join(_job_form(job, csrf_token) for job in drafts)
    if not rendered:
        rendered = '<p class="muted">No draft jobs remain. Add a job or leave this session.</p>'
    diagnose = ""
    if not drafts:
        diagnose = f"""
          <form method="post" action="/diagnose">
            {_csrf(csrf_token)}
            <button type="submit">Run read-only diagnosis</button>
          </form>
        """
    body = f"""
      <h1>Confirm your Job Map</h1>
      <p>These are suggestions for you to review. Edit, add, discard, or confirm
      each job. Diagnosis stays unavailable until every selected job has a full
      Success Contract.</p>
      {rendered}
      <div class="panel">
        <h2>Add a job yourself</h2>
        <form method="post" action="/jobs/add">
          {_csrf(csrf_token)}
          <label>Job id (optional)<input name="job_id"></label>
          <label>Title<input name="title" required></label>
          <label>Situation<textarea name="situation" required></textarea></label>
          <label>Desired outcome<textarea name="desired_outcome" required></textarea></label>
          <div class="actions"><button type="submit">Add draft job</button></div>
        </form>
      </div>
      <form method="post" action="/close">
        {_csrf(csrf_token)}
        <button class="secondary" type="submit">Close and delete local drafts</button>
      </form>
      {diagnose}
    """
    return _document("Confirm your Job Map", body)


def _fallback_level(item: FallbackEvidence) -> str:
    level = item.level
    if level is EvidenceLevel.SUPPORTED:
        return "Supported"
    if level is EvidenceLevel.REPORTED:
        return "Reported"
    # Unknown is the only safe display for anything else, including attempted
    # direct-inspection claims in a fallback result.
    return "Unknown"


def _fallback_reason(value: str) -> str:
    """Keep adapter guidance from introducing a forbidden positive label."""

    return re.sub("verified", "direct inspection", value, flags=re.IGNORECASE)


def render_fallback(fallback: CollectionFallback, csrf_token: str) -> str:
    """Render bounded guided/export-assisted input with honest capped labels."""

    evidence = "".join(
        f"<li><strong>{_escape(item.label)} — {_escape(_fallback_level(item))}</strong>: "
        f"{_escape(_fallback_reason(item.detail))}</li>"
        for item in fallback.evidence
    )
    if not evidence:
        evidence = "<li>Unknown — no direct evidence was collected.</li>"
    mode = "guided" if fallback.mode is FallbackMode.GUIDED else "export-assisted"
    guided_selected = " selected" if fallback.mode is FallbackMode.GUIDED else ""
    export_selected = (
        " selected" if fallback.mode is FallbackMode.EXPORT_ASSISTED else ""
    )
    body = f"""
      <h1>{_escape(mode.title())} evidence</h1>
      <div class="panel">
        <p>Evidence mode: {_escape(fallback.mode.value)}</p>
        <p>{_escape(_fallback_reason(fallback.reason))}</p>
        <p>This path does not claim direct inspection. Evidence is labelled
        Supported, Reported, or Unknown according to what you supply. References
        are locators or digests only, never raw file content.</p>
        <h2>Choose the fallback mode</h2>
        <form method="post" action="/fallback/mode">
          {_csrf(csrf_token)}
          <label>Mode<select name="mode">
            <option value="guided"{guided_selected}>
              Guided questions
            </option>
            <option value="export-assisted"{export_selected}>
              Export-assisted
            </option>
          </select></label>
          <div class="actions"><button type="submit">Use this mode</button></div>
        </form>
        <h2>Evidence supplied so far</h2>
        <ul>{evidence}</ul>
        <h2>Add one bounded claim</h2>
        <form method="post" action="/fallback/evidence">
          {_csrf(csrf_token)}
          <label>Label<input name="label" required></label>
          <label>Level<select name="level">
            <option value="supported">Supported — supplied export or material</option>
            <option value="reported">Reported — your account</option>
            <option value="unknown">Unknown — not enough to claim</option>
          </select></label>
          <label>Reference (locator or digest; no raw content)
            <input name="reference"></label>
          <label>Probe id (optional, e.g. recent-activity)
            <input name="probe_id"></label>
          <label>Bounded detail<textarea name="detail" required></textarea></label>
          <div class="actions"><button type="submit">Add evidence</button></div>
        </form>
        <h2>Import bounded lines</h2>
        <p class="muted">One per line: label|level|reference|detail. Use a locator
        or digest in the reference column, never pasted file contents.</p>
        <form method="post" action="/fallback/import">
          {_csrf(csrf_token)}
          <textarea name="evidence" required></textarea>
          <input type="hidden" name="mode" value="{_escape(fallback.mode.value)}">
          <div class="actions"><button type="submit">Import evidence</button></div>
        </form>
        <form method="post" action="/fallback/continue">
          {_csrf(csrf_token)}
          <div class="actions"><button type="submit">Continue to Job Map</button></div>
        </form>
        <form method="post" action="/close">
          {_csrf(csrf_token)}
          <button class="secondary" type="submit">Close and leave</button>
        </form>
      </div>
    """
    return _document(f"{mode.title()} evidence", body)


def render_collecting(csrf_token: str) -> str:
    """Keep cancellation available while the contained child is reading."""

    body = f"""
      <h1>Read-only inspection in progress</h1>
      <div class="panel">
        <p>Dex Lens is reading only the approved scope in its contained process.
        You can stop it now; stopping kills the contained collection and discards
        every partial result.</p>
        <div class="actions">
          <form method="get" action="/session">
            <button class="secondary" type="submit">Check progress</button>
          </form>
          <form method="post" action="/cancel">
            {_csrf(csrf_token)}
            <button type="submit">Cancel inspection</button>
          </form>
        </div>
      </div>
    """
    return _document("Inspection in progress", body)


def render_capability_map(
    capability_map: CapabilityMap,
    csrf_token: str,
    *,
    journey: ConciergeJourney | None = None,
) -> str:
    """Render the existing jobs-first map inside a safe local page."""

    markdown = render_map_markdown(capability_map)
    adaptation = ""
    if journey is not None and journey.stage is ConciergeStage.CAPABILITY_MAP:
        jobs = tuple(journey.confirmed_contracts)
        options = "".join(
            f'<option value="{_escape(contract.job_id)}">{_escape(contract.job_id)}</option>'
            for contract in jobs
        )
        adaptation = f"""
      <div class="panel">
        <h2>Adapt one bounded capability</h2>
        <p>Adaptation is separate from diagnosis. Select one confirmed job,
        review the exact local Markdown file, approve it once, and keep a
        receipt with an undo path. High-impact or uncertain jobs are refused.</p>
        <form method="post" action="/adaptation/select">
          {_csrf(csrf_token)}
          <label>Confirmed job<select name="job_id" required>{options}</select></label>
          <label>Capability id<input name="capability_id" required></label>
          <label>Approved skills root<input name="approved_skills_root" required></label>
          <label>Exact Markdown preview<textarea name="markdown" required># Dex Lens helper
</textarea></label>
          <label>Expected benefit<input name="expected_benefit" required></label>
          <label>Observable Success Contract signal<input name="observable_signal" required></label>
          <div class="actions"><button type="submit">Select this adaptation</button></div>
        </form>
      </div>
    """
    body = f"""
      <h1>Capability Map</h1>
      <pre>{_escape(markdown)}</pre>
      {adaptation}
      <form method="post" action="/close">
        {_csrf(csrf_token)}
        <button class="secondary" type="submit">Close and clear this session</button>
      </form>
    """
    return _document("Capability Map", body)


def _adaptation_preview_body(journey: ConciergeJourney, csrf_token: str) -> str:
    """Render one stage-7/8 page from immutable journey records."""

    stage = journey.stage
    selection = journey.adaptation_selection
    preview = journey.adaptation_preview
    refusal = journey.adaptation_refusal
    if stage is ConciergeStage.ADAPTATION_REFUSED:
        return f"""
      <h1>Adaptation not automated</h1>
      <div class="panel"><p><strong>Refused:</strong> {_escape(refusal)}</p>
      <p>The safe path is guidance only. No host file was changed.</p>
      <form method="post" action="/close">{_csrf(csrf_token)}
        <button class="secondary" type="submit">Close and leave</button>
      </form></div>
    """
    if stage is ConciergeStage.ADAPTATION_HARD_STOP:
        return f"""
      <h1>Adaptation hard stop</h1>
      <div class="panel"><p><strong>Automation stopped:</strong>
        {_escape(journey.hard_stop_reason)}</p>
        <p>No further automated changes are available in this session. Follow
        the incident and hard-stop runbooks before any review or retry.</p>
        <form method="post" action="/close">{_csrf(csrf_token)}
          <button class="secondary" type="submit">Close and leave</button>
        </form>
      </div>
    """
    if stage is ConciergeStage.ADAPTATION_SELECT and selection is not None:
        return f"""
      <h1>Selected adaptation</h1>
      <div class="panel">
        <p>One bounded local change is selected. Nothing has been written.</p>
        <ul><li>Job: {_escape(selection.job_id)}</li>
        <li>Capability: {_escape(selection.capability_id)}</li>
        <li>Target root: {_escape(selection.approved_skills_root)}</li>
        <li>Expected benefit: {_escape(selection.expected_benefit)}</li></ul>
        <form method="post" action="/adaptation/preview">{_csrf(csrf_token)}
          <button type="submit">Build exact preview</button>
        </form>
      </div>
    """
    if stage is ConciergeStage.ADAPTATION_PREVIEW and preview is not None:
        return f"""
      <h1>Review exact adaptation preview</h1>
      <div class="panel">
        <p>Nothing has been written. Approval is specific to this exact file,
        content hash, job, and capability.</p>
        <ul><li>Target: {_escape(getattr(preview, 'target_path', ''))}</li>
        <li>Bytes: {_escape(getattr(preview, 'content_size', ''))}</li>
        <li>Content SHA-256: {_escape(getattr(preview, 'content_sha256', ''))}</li>
        <li>Expected benefit: {_escape(getattr(preview, 'expected_benefit', ''))}</li>
        <li>Effects: {_list(getattr(preview, 'effects', ()))}</li>
        <li>Risks: {_list(getattr(preview, 'risks', ()))}</li></ul>
        <pre>{_escape(getattr(preview, 'content', ''))}</pre>
        <form method="post" action="/adaptation/approve">{_csrf(csrf_token)}
          <button type="submit">Approve this one change</button>
        </form>
      </div>
    """
    if stage is ConciergeStage.ADAPTATION_APPROVAL and preview is not None:
        return f"""
      <h1>Adaptation approved</h1>
      <div class="panel">
        <p>A single-use approval is bound to {_escape(getattr(preview, 'target_path', ''))}.
        The transaction will create one namespaced Markdown file and no network
        request.</p>
        <form method="post" action="/adaptation/apply">{_csrf(csrf_token)}
          <button type="submit">Apply approved change</button>
        </form>
      </div>
    """
    if stage is ConciergeStage.ADAPTATION_APPLY:
        return "<h1>Applying adaptation</h1><p>Writing one approved local Markdown file.</p>"
    if stage is ConciergeStage.ADAPTATION_RECEIPT:
        result = journey.adaptation_result
        receipt_path = getattr(result, "receipt_path", "")
        return f"""
      <h1>Adaptation receipt</h1>
      <div class="panel"><p>The approved local change is applied and receipted.</p>
        <p>Receipt: <code>{_escape(receipt_path)}</code></p>
        <form method="post" action="/adaptation/verify">{_csrf(csrf_token)}
          <button type="submit">Verify against the Success Contract</button>
        </form>
      </div>
    """
    if stage is ConciergeStage.ADAPTATION_VERIFY:
        verification = journey.adaptation_verification
        return f"""
      <h1>Adaptation verified</h1>
      <div class="panel"><p>Outcome: {_escape(getattr(verification, 'verdict', verification))}</p>
        <p>{_escape(getattr(verification, 'detail', 'Verification recorded'))}</p>
        <form method="post" action="/adaptation/undo">{_csrf(csrf_token)}
          <button class="secondary" type="submit">Undo this adaptation</button>
        </form>
      </div>
    """
    if stage is ConciergeStage.ADAPTATION_UNDO:
        undone = journey.adaptation_undo_result
        return f"""
      <h1>Adaptation undone</h1>
      <div class="panel"><p>The exact pre-change state was restored.</p>
        <p>Status: {_escape(getattr(undone, 'status', undone))}</p>
        <form method="post" action="/close">{_csrf(csrf_token)}
          <button class="secondary" type="submit">Close and leave</button>
        </form>
      </div>
    """
    return "<h1>Adaptation unavailable</h1><p>No bounded adaptation is selected.</p>"


def render_adaptation(journey: ConciergeJourney, csrf_token: str) -> str:
    """Render stages 7-8 without giving views any mutation capability."""

    return _document("Adaptation", _adaptation_preview_body(journey, csrf_token))


def render_journey(journey: ConciergeJourney, csrf_token: str) -> str:
    """Dispatch a page from explicit journey state for server integration."""

    if journey.stage is ConciergeStage.PERMISSION:
        return render_permission(journey.permission, csrf_token=csrf_token)
    if journey.stage is ConciergeStage.COLLECTING:
        return render_collecting(csrf_token=csrf_token)
    if journey.stage is ConciergeStage.FALLBACK and journey.fallback is not None:
        return render_fallback(journey.fallback, csrf_token=csrf_token)
    if journey.stage is ConciergeStage.CAPABILITY_MAP and journey.capability_map is not None:
        return render_capability_map(
            journey.capability_map,
            csrf_token=csrf_token,
            journey=journey,
        )
    if journey.stage in {
        ConciergeStage.ADAPTATION_SELECT,
        ConciergeStage.ADAPTATION_PREVIEW,
        ConciergeStage.ADAPTATION_APPROVAL,
        ConciergeStage.ADAPTATION_APPLY,
        ConciergeStage.ADAPTATION_RECEIPT,
        ConciergeStage.ADAPTATION_VERIFY,
        ConciergeStage.ADAPTATION_UNDO,
        ConciergeStage.ADAPTATION_REFUSED,
        ConciergeStage.ADAPTATION_HARD_STOP,
    }:
        return render_adaptation(journey, csrf_token=csrf_token)
    if journey.stage in {
        ConciergeStage.JOB_MAP,
        ConciergeStage.DIAGNOSIS,
    }:
        return render_job_map(journey.inspection_jobs, csrf_token=csrf_token)
    return _document("Session closed", "<h1>Session closed</h1><p>No inspection is running.</p>")


# Explicit aliases for transport code that uses ``*_view`` naming.
render_permission_view = render_permission
render_job_map_view = render_job_map
render_fallback_view = render_fallback
render_capability_map_view = render_capability_map
render_adaptation_view = render_adaptation
