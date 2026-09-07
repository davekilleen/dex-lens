# Dex Lens autonomous Wow Gate design

**Date:** 2026-09-02
**Status:** Approved by Dave on 2026-09-02. Implementation may proceed through
green draft PRs only.
**Builds on:** `2026-08-27-dex-lens-deterministic-diagnosis-engine-design.md`
and the green Lens/Core significant-capability draft PRs.
**Delivery boundary:** Draft PRs only. This design does not authorise merge,
release, signing, catalogue publication, installation, website deployment, or
any production change.

## Executive decision

Dex Lens will turn one request from a person into a complete, evidence-bound
analysis workflow. The deterministic engine remains the authority. It will now
issue and reconcile a compulsory queue of bounded specialist work rather than
waiting for a human evaluator to manufacture proposal JSON.

The local MCP server remains the structured connection between the engine and
Claude, Codex, or another compatible assistant. The assistant supplies semantic
judgement; the engine owns the checklist, evidence identities, workflow graph,
availability, ranking inputs, limits, stage transitions, and final report.

The finished report may contain **up to ten** ranked Dex recommendations. Ten is
a ceiling, not a target. A recommendation that cannot clear the evidence and
relevance gates is omitted rather than used to fill the list.

This design deliberately avoids adding a Lens-owned model account, API key, or
outbound model call. It uses the assistant the person already chose. That keeps
the product harness-neutral and avoids creating a second privacy relationship.

## Why the current green candidate is not enough

The two significant-capability draft PRs make the catalogue and the comparison
substantially more complete:

- every signed Dex capability is accounted for;
- every discovered local observation remains visible;
- exact MCP tools and significant end-to-end families are preserved;
- configuration, runtime, and health are separated; and
- factual report counts cannot drift from the ledger.

The private read-only evaluation still exposed one decisive weakness. Only the
skill-copy recommendation was generated automatically. Five of the conclusions
that made the report look intelligent were constructed by the evaluator and
submitted as specialist proposals. Most catalogue entries and local
observations therefore remained unknown even though the final score looked
high.

That is useful scaffolding, not the intended product experience. A first-time
tester must not need an expert standing behind the run, deciding what the
specialists should say. The product has to perform that work from the person's
single request and show exactly where its conclusions came from.

## Product promise

A person can say:

> Use Dex Lens to understand my setup. Tell me what is excellent, what Dex
> should learn from it, and which Dex ideas would help me most.

After the existing scope approval, Lens completes the read-only run without
asking the person to steer its checklist. The result:

1. explicitly considers the whole released Dex capability contract;
2. reconstructs meaningful flows across skills, tools, integrations,
   automations, entities, memory, and safety systems;
3. distinguishes code that exists from work that is configured, running, and
   producing a healthy result;
4. ranks no more than ten specific, personally relevant Dex recommendations;
5. gives grounded credit for the person's strongest methods;
6. proposes transferable ideas Dex should learn when the evidence supports
   them;
7. explains unavoidable technical terms in plain language; and
8. says what it could not prove instead of filling gaps with confident prose.

Diagnosis remains separate from installation, repair, sharing, and
contribution. Nothing in this workflow changes the inspected system.

## Options considered

### A. Engine-owned work queue with MCP specialists — selected

The engine creates fixed evidence packets, assigns closed specialist roles,
requires packet receipts, validates every proposal, runs a sceptical pass, and
then ranks and renders. MCP carries the packets and responses. A capable host
may process them in parallel; another host may process them sequentially.

This gives semantic range without giving a language model authority over facts
or completion. It also works with Claude, Codex, and future MCP-compatible
assistants without Lens storing a provider credential.

### B. Deterministic rules only

Rules are retained for facts that can be proved mechanically. They are not
sufficient on their own for method comparison, reciprocal learning, or subtle
cross-surface insights. This option would be repeatable but would continue to
feel like an inventory scanner.

### C. A free-form multi-agent swarm

Independent agents would likely produce more colourful prose, but they could
skip capability families, disagree silently, leak stale counts, or invent
relationships. This recreates the failure the deterministic engine was built
to remove.

## Vocabulary

- A **work packet** is an engine-issued, bounded assignment tied to one run,
  one fingerprint, one catalogue, one specialist role, and a fixed identity
  set.
- A **workflow node** is a safe structural identity such as a trigger, skill,
  MCP server/tool, provider type, scheduled action, entity type, memory store,
  or guarded outcome.
- A **workflow edge** is a proved relationship such as “invokes”, “reads from”,
  “creates”, “updates”, “checks”, or “recovers”. It carries evidence IDs and a
  confidence class; prose cannot create it.
- A **candidate insight** is an evidence-referenced strength, concern,
  recommendation, or lesson proposed by a specialist.
- A **recommendation rank** is the deterministic ordering of candidates that
  passed the bar. It is a prioritisation aid, not a scientific score.
- A **no-help run** is a run started with one normal product request in which no
  evaluator writes, edits, selects, or injects conclusions or proposal JSON.
- A **useful surprise** is a non-obvious cross-surface insight supported by at
  least two independent evidence identities and accepted by the sceptical
  pass.

## Architecture

```text
one user request
      |
      v
local scope approval (existing consent authority)
      |
      v
DeterministicDiagnosisEngine
  collect -> verify catalogue -> derive safe facts -> build workflow graph
      |
      v
engine-owned specialist work queue
  tools/integrations | automations/health | people/work | strengths/lessons
  release distance   | contradictions    | workflow synthesis
      |
      v
MCP work packets -> chosen host assistant/sub-agents -> typed proposals
      |                                      |
      +---------- evidence validation <------+
                         |
                         v
mandatory sceptical reconciliation
                         |
                         v
deterministic recommendation ranking + canonical report
```

The engine remains a deep module with one run state. The MCP server does not
gain a second checklist, raw filesystem access, shell access, network access,
or a mutation route.

## Autonomous run protocol

### Modes

Lens retains an `inventory-only` compatibility mode for a caller that cannot
provide semantic analysis. It may close with honest unknowns, but it cannot be
described as a full diagnosis or pass the Wow Gate.

The installed skill will use `guided-analysis` mode. In this mode the engine will
not render the final report until every required work packet has either:

- produced validated output;
- returned an explicit evidence-insufficient result; or
- exhausted a bounded retry and been recorded as unresolved.

The person is not asked to prompt each stage. After consent, the host adapter
keeps calling status/work/submit/advance until the engine reaches the next real
person decision or closes.

### Required stages

1. Prepare the candidate scope without reading it.
2. Receive the existing local approval receipt.
3. Capture the bounded fingerprint and optional consented live-state evidence.
4. Verify and pin the exact signed catalogue bytes.
5. Derive deterministic observations, exact family coverage, and workflow
   graph candidates.
6. Issue specialist work packets.
7. Validate and reconcile specialist proposals.
8. Issue the sceptical reconciliation packet over the accepted candidates.
9. Derive final dispositions, recommendation order, strengths, lessons, and
   limits.
10. Render, check, save, and close through the existing canonical path.

Every stage is idempotent and checkpointed. Resuming a run cannot duplicate a
packet, silently replace a response, or skip the sceptical pass.

## Specialist work

The closed roles are:

1. **Tools and integrations** — MCP servers and exact tools, provider types,
   connector breadth, connection lifecycle, and external task systems.
2. **Automations and health** — scheduled definitions, installed state, live
   state, recent outcomes, Doctor, monitoring, and restore proof.
3. **People and work continuity** — meeting follow-through, automatic task
   creation, living people/company context, and linked commitments.
4. **Operating rhythm and memory** — planning/review loops, sourced memory,
   decisions, and continuity across sessions.
5. **Strengths and reciprocal learning** — distinctive methods that deserve
   credit and might improve Dex.
6. **Release distance** — material released Dex capabilities that are newer
   than a proved inspected lineage.
7. **Contradictions and reliability** — conflicts between written intent,
   configuration, runtime, health, and outcome evidence.
8. **Workflow synthesis** — cross-surface paths and missing links that no
   single observation reveals.
9. **Sceptical reconciler** — mandatory final challenge of every surviving
   strength, lesson, surprise, and recommendation.

The engine may split a role into several bounded packets when the identity set
is large. Packet generation and completion are deterministic; the number of
language-model workers is a host implementation detail.

Each packet contains only safe, typed data already permitted by the diagnosis
boundary:

- run, fingerprint, catalogue, and packet digests;
- role and explicit question;
- allowed catalogue, family, workflow, observation, and evidence IDs;
- bounded structural attributes and operational states;
- the closed response schema; and
- the output and retry limits.

It contains no raw secret, credential, absolute private path, unbounded file
content, or unrelated personal text. Specialist output is untrusted until the
engine validates it.

## MCP surface

The existing five tools remain and one read-only tool is added:

- `prepare_diagnosis`
- `get_diagnosis_status`
- `advance_diagnosis`
- `get_diagnosis_work` — returns the next bounded packet or a typed “none”
  result
- `submit_specialist_proposal`
- `get_diagnosis_result`

`submit_specialist_proposal` now requires the engine-issued packet identity
and packet digest. A proposal cannot cite identities outside that packet, and a
packet cannot be submitted twice with different content. Status reports exact
packet totals, completed roles, unresolved roles, and the next legal action.

No tool launches a shell, edits a file in the inspected system, sends data,
installs anything, or contacts a model provider. The selected host assistant
processes a packet with its existing model session. Hosts with sub-agents may
fan out independent packets; hosts without them use the same protocol in
sequence.

## Deterministic detectors and workflow reconstruction

Specialists do not replace deterministic detection. Lens first produces every
fact that safe structure can prove:

- skill identities, copies, variants, and declared purpose;
- MCP server identities and safely enumerable tools;
- integration/provider types and whether only a directory, configuration, or
  live connection is proved;
- scheduled work, referenced executables, install/load state, recency, and
  outcome health when live inspection was approved;
- people/company, meeting, task, memory, backup, repair, and health markers;
- known trigger, action, output, and recovery relationships; and
- exact released Dex family/member availability from the signed catalogue.

The graph uses closed node and edge kinds. An edge is emitted only by a
reviewed structured detector or an accepted proposal that cites the exact
supporting observations. A specialist may suggest a relationship; it cannot
make an unsupported relationship true.

This allows Lens to find insights such as a health system that watches several
jobs but not a backup, or a meeting flow that creates notes but loses follow-up
tasks. The report describes the human outcome rather than dumping filenames or
technical plumbing.

## Significant capability guarantee

The Wow Gate contains an explicit, versioned expectation manifest. It does not
hard-code marketing copy or pretend that every connector definition is an
active connection. It requires the run to consider these outcome areas and to
show their evidence state:

1. proactive health and Dex Doctor;
2. connection management, provider discovery, and the connector registry
   breadth derived from signed source truth;
3. Work MCP and its exact published tools;
4. Career/Resume MCP and their exact published tools;
5. automatic task creation and linked follow-through;
6. living people and company pages that update over time;
7. meetings becoming context, commitments, and actions;
8. Todoist, Trello, Things, and other published task interoperability;
9. durable memory, sourced decisions, and cross-session continuity;
10. daily and weekly planning/review rhythm;
11. safe change, update, verification, and rewind;
12. backup creation and restore confidence;
13. privacy-safe feedback and contribution; and
14. adoption and creation of useful ways of working.

For each area the engine records one of: present, partial, absent, unknown, not
relevant to the approved jobs, or not currently available from Dex. The report
need not burden the reader with all fourteen rows, but the canonical appendix
and quality gate must contain them all. Internal availability language is
translated into plain English; the public report does not talk about “parked”
or “dormant” systems.

Counts such as the size of a connector directory are derived at run time from
the exact signed source. They are never copied from an old release note or
rounded into a claim about live connections.

## Recommendation contract: up to ten

A candidate recommendation survives only when all of these are true:

- the Dex capability is currently available to the person;
- the inspected system does not already provide an equal or stronger method;
- the finding is relevant to a confirmed user job, an evidence-supported
  workflow already present in the inspected system, or a proved reliability
  risk;
- its rationale cites exact evidence IDs;
- the expected benefit and adoption effort can be explained plainly;
- it does not duplicate another higher-level recommendation; and
- the sceptical reconciler accepts it or leaves no unresolved contradiction.

Ordering is deterministic and explainable. Candidates are sorted by:

1. urgency of a proved reliability or continuity risk;
2. relevance to the person's confirmed jobs;
3. expected leverage across reconstructed workflows;
4. evidence strength;
5. lower adoption effort; and
6. stable capability identity as the final tie-break.

The report stores the factor values and gives each item a rank from 1 to 10. It
does not show a pseudo-scientific percentage. It presents:

- **The best first move** — rank 1;
- **Next most useful** — ranks 2 and 3 when present; and
- **Also worth considering** — ranks 4 through 10 when they clear the bar.

Fewer than ten is a successful result. Zero is valid when nothing available is
both missing and useful.

## Praise, reciprocal value, and useful surprises

Praise is not generic encouragement. A strength must cite evidence for the
method, explain the outcome it protects, and state why it is unusually strong
or well-connected. A reciprocal lesson must identify what Dex could copy or
adapt and must not expose private implementation details.

A useful surprise must join at least two independently collected observations
or workflows. It is rejected if it merely rephrases one filename, relies on a
private anecdote not in the run, or implies live behaviour from configuration
alone.

The report always contains:

- “What is especially strong here”;
- “What Dex should learn from you”, or an honest empty answer;
- the ranked recommendations that cleared the bar;
- “Connections Lens noticed” for accepted workflow insights; and
- clear limits on what was not observed or could not be proved.

## Failure handling

- A malformed or out-of-packet proposal is rejected and may be retried once.
- Two contradictory specialist claims remain unresolved until the sceptical
  pass; the engine never chooses the more confident prose.
- A timed-out packet becomes an explicit unknown, not an implicit success.
- Guided analysis cannot claim “complete” while required packet receipts are
  missing.
- A catalogue, fingerprint, scope, engine, or packet digest change starts a
  new run identity.
- An unavailable Dex capability cannot enter the recommendation set.
- Unsupported praise, lessons, surprises, and recommendations fail report
  validation.
- The inspected repository remains read-only. Lens writes only to its guarded
  application storage outside the approved scope.

## No-help evaluation and iteration loop

The private evaluation is a product rehearsal, not a source of committed
fixtures.

1. Pin one immutable commit of Dave's consented private evaluation repository
   in a disposable, read-only checkout.
2. Cache and pin the signed catalogue, then disable unnecessary network access.
3. Start the run with the same single request a beta tester would use.
4. Permit only the product's engine, MCP tools, chosen assistant, and
   engine-issued specialist packets. No evaluator may write or edit a
   conclusion, select a recommendation, or submit hand-built proposal JSON.
5. Save the raw report and run audit only in a private temporary evaluation
   area; never add them to Git, a PR, Dispatch, or Mission Control.
6. Grade the run mechanically and through an independent sceptical review.
7. Convert each genuine miss into the smallest invented or sanitised failing
   regression fixture. Observe it fail before changing production code.
8. Implement the narrow fix, rerun repository checks, and repeat from a clean
   private checkout.
9. Stop only after the hard gates pass twice from clean state and a separate
   holdout fixture has not regressed.

Public branches may record only aggregate scores, rule/fixture identities, and
non-private acceptance evidence.

## Wow Gate scorecard

The numeric grade helps compare iterations; it can never override a hard
failure.

- 25 points — all fourteen significant outcome areas explicitly considered;
- 20 points — useful workflow reconstruction across multiple surfaces;
- 20 points — specific, correctly ordered recommendations with no padding;
- 15 points — grounded strengths and transferable lessons for Dex;
- 15 points — evidence integrity, operational honesty, and no unsupported
  claims; and
- 5 points — one-request autonomy, clear progress, plain language, and an
  honest close.

Passing requires at least 90/100 and every hard gate below. A hand-seeded
proposal makes the run an automatic failure regardless of score.

## Hard acceptance gates

The build is not complete unless all of these are proved:

- zero evaluator-authored or manually seeded conclusions in the no-help run;
- every engine-issued mandatory packet has a receipt or an explicit bounded
  unresolved result;
- all fourteen agreed game-changing outcome areas are present in the final
  assessment manifest;
- exact catalogue, MCP server/tool, provider-type, family, and local
  observation equality gates remain green;
- at most ten recommendations are rendered, in deterministic rank order;
- every recommendation is available, relevant, non-duplicative, and
  evidence-backed;
- strengths, reciprocal lessons, and useful surprises cite valid evidence;
- at least one credible cross-surface useful surprise is found in the rich
  private evaluation, without making it a requirement for sparse systems;
- configuration is never described as runtime or healthy outcome evidence;
- report facts, ledger facts, packet audit, and saved bytes reconcile exactly;
- direct, CLI, and MCP routes retain canonical equality for the same run;
- interruption, duplicate submission, hostile payload, prompt injection,
  missing-agent, and stale-packet tests fail closed;
- no raw private content, path, secret, report, or proposal enters a public
  commit, CI log, PR, Dispatch entry, or Mission Control evidence;
- focused and full Lens checks pass;
- affected Core schema/catalogue checks pass if the contract changes;
- an independent code review and an independent sceptical report review both
  pass; and
- the Lens and any required Core changes finish as green draft PRs only.

## Test strategy

Implementation follows strict red-green-refactor order. The first failures
cover:

1. recommendation eleven rejected while ten validate and rank stably;
2. a guided run refusing to render before mandatory packet completion;
3. packet identity/digest binding and duplicate-response refusal;
4. deterministic detector proposals appearing without manual submission;
5. workflow edges requiring valid evidence and operational axes;
6. the sceptical pass downgrading an unsupported recommendation or strength;
7. every significant expectation manifest row appearing exactly once;
8. inventory-only output never presenting itself as a full diagnosis;
9. resume preserving packet state without duplicate agent work;
10. direct/CLI/MCP equality with the new work tool and packet audit;
11. report sections and ranking derived from typed result data; and
12. the automated Wow Gate refusing a high numerical score when proposal
    provenance says “manual”.

The repository suite then covers Ruff, boundary inventory, schema generation,
packaging, containment, egress, hostile fixtures, and release dry-run checks.
No public release rehearsal or production installer test is performed under
this goal because publication is explicitly out of scope.

## Expected implementation seams

The exact plan will be written only after this design is approved. Expected
Lens seams are:

- `diagnosis/work.py` for packets, queue state, and receipts;
- `diagnosis/workflows.py` for typed graph construction;
- `diagnosis/ranking.py` for the recommendation bar and ordering;
- `diagnosis/specialists.py` for packet-bound proposal validation;
- `diagnosis/orchestrator.py` and `run.py` for guided-analysis stages;
- `diagnosis/mcp_server.py` and `cli.py` for thin adapter support;
- `diagnosis/comparison.py` and `report.py` for typed ranked output;
- the installed Dex Lens skill for the one-request host loop; and
- `tests/diagnosis`, `tests/evals`, and `scripts` for the deterministic and
  private-evaluation gates.

Core changes are avoided unless Lens requires additive signed metadata that
the existing significant-capability contract does not already provide. The
current Core draft PR is the starting contract, not an excuse to duplicate its
registry or generators.

## Out of scope

- Merge, release, signing, catalogue publication, deployment, or installer
  promotion.
- Automatic repair or modification of the inspected system.
- A Lens-owned model provider, API key, or background network service.
- Sending raw private content to Dex, GitHub, CI, Mission Control, Dispatch, or
  another user.
- Treating every provider definition as an active connection.
- Recommending unfinished Dex work as something a person can use now.
- Replacing evidence with release-note prose or hard-coded feature counts.
- Filling ten recommendation slots for presentation symmetry.

## Approval

Dave approved this written contract on 2026-09-02, including the Engine + MCP
architecture, autonomous specialist workflow, no-help private evaluation, and
the ceiling of ten ranked recommendations. Merge, release, publication and
deployment remain separately held.
