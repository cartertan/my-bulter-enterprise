## Mission reliability and artifact delivery remediation

### Objective and release policy

Deliver a trustworthy local author/reviewer workflow that can eventually create and validate a template-based presentation. A successful model call, model agreement and a user-accepted deliverable are different outcomes. Keep them separate in storage, UI and release claims.

The initial acceptance exercise failed despite passing unit tests. Failures included unsupported team/template combinations, output exhaustion before review, incorrect arithmetic, unsupported citations, irrelevant demo memory and missing rendered artifacts. Reproduce these with synthetic fixtures; never publish the original customer template, personal notes or mission database.

Assumptions: one local user, one worker, explicit cloud consent, no automatic paid retries. Enterprise hosting, tenant isolation and authentication are separate workstreams and are not implied by this roadmap.

### Prioritized delivery pipeline

| Order / issue | Priority | Work package and dependencies | Acceptance gate | Status |
| --- | --- | --- | --- | --- |
| REL-001 | P0 | Classify output exhaustion; explicit incomplete-draft handoff; preserve partial evidence; distinguish execution from acceptance | Opt-in reviewer receives flagged partial output; default still stops; interrupted runs never become accepted artifacts; provider budgets honoured | Implemented in working tree, automated regression verified |
| REL-002 | P0 | Context budgeting and resumable per-section generation, after REL-001 | Large synthetic template + draft reaches review without dropping evidence; bounded continuation, cancellation and restart recovery; no automatic paid retry | Implemented section checkpoints and recovery; UI and real-provider validation pending |
| REV-001 | P0 | Structured per-agent review records and acceptance criteria, after REL-001 | Store agent identity independently of generated headings; parse criterion result/evidence; invalid or missing fields cannot pass; `completed` never implies `accepted` | Draft-bound criterion records implemented; timing and artifact validation pending |
| REV-002 | P0 | Deterministic checks and bounded author/reviewer revision rounds, after REL-002 and REV-001 | Code totals slide durations and checks artifact existence; two-agent loop stops on acceptance, limits or unresolved disagreement; 27 + 5 fails a 30-minute budget | Planned |
| MEM-001 | P0 | Explicit mission memory selection and visible provenance | Users can select approved preference notes within existing access policy; demo notes do not silently become personal requirements; selected hashes preserved; oversized selections rejected clearly | Implemented; automated and isolated UI checks passed; awaiting review |
| EVD-001 | P1 | Source register and bounded research evidence | Every factual claim links to retained source ID, retrieval date and scope; invented source IDs rejected; missing support remains unverified; browsing assistance identified honestly | Selected-source registry and exact-quote checks implemented; online research pending |
| ART-001 | P1 | Office capability preflight and safe relationship handling | Unsupported edits rejected before inference; allow only validated citation hyperlink relationships while rejecting external templates/objects and unsafe targets; template fidelity tests pass | ART-001A text/artifact review implemented; rendered validation pending; ART-001B implemented |
| ART-002 | P1 | Structured slide manifest, template-aware composition, diagrams/images and speaker notes, after EVD-001 and ART-001 | Synthetic reference design preserved; new visuals actually exist; text editable; explicit picture provenance; no placeholder contact information | Planned |
| ART-003 | P1 | Render and inspect every slide, after ART-002 | Inspect clipping, readability, missing assets and template fidelity; artifact hash and validation report bind reviews to the exact output | Planned |
| QA-001 | P0 throughout | Synthetic integration tests, clean-install smoke tests and source-only release checks | Tests, JS syntax, allowlist/secret-pattern checks pass; no private runtime data; known limits documented | Local gate implemented; hosted CI and clean-install validation pending |
| UAT-001 | Release gate | Replay national-wallet scenario after previous gates | Complete, sourced visual deck; verified ≤30-minute schedule; two actual agent review records; no unsupported claims; final user acceptance recorded separately | Blocked on implementation |

### Milestones and proposed pull requests

1. **Execution reliability:** REL-001, then REL-002. First PR covers typed provider errors, bounded partial handoff, UI disclosure and synthetic regressions. Second covers context reservation and resumable sections.
2. **Review integrity:** REV-001, MEM-001, then REV-002. Use structured data and deterministic validators; prompt changes alone cannot enforce factual accuracy or consent.
3. **Artifact delivery:** EVD-001 and ART-001, followed by ART-002 and ART-003. Keep text-only exports labelled as response exports until actual composition exists.
4. **Release candidate:** clean-install check, local-model UAT, packaging inspection, independent human review and release notes. Publish only after the original end-to-end scenario passes or clearly label the narrower supported scope.

Do not promise delivery dates before each package is estimated against a concrete design and test fixture. Each issue should record problem, scope, exclusions, dependencies, acceptance tests and evidence links.

### REL-002 design and test contract

- Preflight the source, instructions, selected memories and reserved handoff budget before the first model request. Distinguish the current character guard from a model's token context limit; do not claim character counts are token counts.
- Introduce a per-section work item with an immutable source revision, section ID, draft revision, provider outcome and review state. Never overwrite a prior draft when revising it.
- Generate and review bounded sections rather than forcing an entire slide deck through one output window. A completion checklist must identify every required section and its missing evidence.
- Permit an explicit resume action from a retained checkpoint. Revalidate memory permissions and source revisions before any resumed request. Show whether a resume will call a cloud provider and require the applicable consent.
- Reserve room for the next reviewer. If the task cannot fit, explain which inputs exceed the budget and require an explicit smaller scope; do not silently omit attachments or substitute summaries.
- Test large references, variable-length outputs, interrupted streams, stale source hashes, revoked memories, cancellation during resume, duplicate resume requests and process restarts. A fresh instance must reconstruct checkpoint state without rerunning completed calls.
- Retest the original failure shape with synthetic inputs of comparable size, then perform a separately labelled local-model run. Passing short mocked handoffs alone is not sufficient for this package.

### REL-001 implementation contract

- `review_partial_output` defaults to `false`. It requires at least two selected Bulters and attachment mode `reference`.
- An explicit token or application text limit marks that step `partial` with `error_code: output_limit` and preserves at most 16,000 characters.
- With opt-in and nonempty partial output, the next already-selected Bulter receives a flagged partial handoff. There is no retry, extra model selection or broader memory permission.
- A successful subsequent review leaves the run `completed_with_issues`. Office export remains blocked. JSON inspection remains available.
- A final-step output limit, empty partial text, network/provider error, cancellation or context overflow still prevents normal completion.
- New missions record `acceptance_status: not_assessed`; this slice does not add a user approval endpoint or machine acceptance engine.
- Provider output budgets now use the configured value for all supported adapters. Existing defaults remain unchanged.
- The UI checks backend capability before exposing the new option, and omits it from ordinary requests. An older running backend remains compatible while awaiting restart.
- Prompt guidance restricts agents to their own identity. This is advisory; REV-001 must make identity and review evidence structural.

### Definition of done for each pull request

REL-001 validation on 30 October 2026: 126 tests pass, including 22 new reliability cases; all three application JavaScript files pass syntax checks; 74 allowlisted files pass packaging preflight. An isolated browser smoke test with synthetic model streams confirmed that the author remains incomplete, the reviewer executes, the run visibly says “Review finished · incomplete draft,” and only JSON export is offered. After isolated checks, the normal loopback service was found stopped. The updated application was started with its existing local data, and the new option was verified in the live UI without starting a model mission. No real-provider recovery run or full presentation UAT is claimed. One existing Starlette/httpx deprecation warning remains.

- Reproduce the failure with synthetic, distributable fixtures before claiming the fix.
- Keep the diff focused and include migration/backward-compatibility behaviour where applicable.
- Run `python scripts/check_release.py` using the project's installed environment.
- Inspect UI behaviour for changed flows; unit tests do not establish usability or live-provider compatibility.
- Document what is implemented, what was tested and what remains unverified.
- Review exactly the intended staged files. Never stage runtime evidence, vaults, credentials, generated mission artifacts or personal screenshots.
- Merge only after review. Tag and publish a release from an inspected commit, not a dirty workspace.

### Repository handoff

Remediation branch: `codex/mission-reliability-remediation`. Existing uncommitted attachment-workflow changes preceded this work and remain intact. Reconcile those as a prerequisite review or separate commit before preparing the remediation PR; do not describe the combined diff as entirely new remediation work.

The repository's permitted edit scope currently covers `src/` and `scripts/`. A reusable local release command is included. A hosted GitHub Actions workflow is deferred until the repository-level workflow file is explicitly in scope. No remote push, repository creation or public release is part of this implementation slice.

## Warnings

- Partial review improves recovery, not factual correctness. Handoff reservation guards the application character limit, not provider token limits; missing draft content still requires further work.
- Existing Office template restrictions and lack of autonomous visual composition remain. The original end-to-end presentation scenario is still not ready to pass.
- Automated secret-pattern checks are a limited guard, not proof that all source or screenshots are safe to publish. Human review remains required.

### REL-002 progress: 1 November 2026

- Implemented preflight reservation for every later reviewer, including four-agent chains. Budgets are persisted with the mission and count JSON escaping rather than raw output length.
- A source that leaves less than 1,024 characters per prior draft after a 2,048-character optional-note reserve is rejected before inference. Sources are never trimmed. Notes remain selected dynamically within the actual context guard.
- Generation exceeding its reserved budget retains a marked incomplete prefix. Review proceeds only with existing explicit partial-review consent; no retry or additional paid request is introduced.
- Regression coverage uses 12,000-character synthetic evidence, oversized escaped drafts, two/three/four-agent teams, Unicode/control characters and preflight rejection without inference.
- Pending: immutable per-section revisions, explicit resume, restart/revocation/duplicate-resume tests and a representative real-provider run. REL-002 remains open. This change does not establish presentation acceptance.

### REL-002 recovery progress: 1 November 2026

- Added explicit recovery for failed, cancelled or interrupted reference missions created with source provenance. Completed agent steps are reused; the first unfinished step starts again. Partial text is not silently treated as a completed checkpoint.
- Each recovery creates a linked child mission. The original attempt and outputs remain intact. Each parent permits one child, with at most three recovery attempts per chain; no automatic retry occurs.
- Revalidate source hashes, agent configuration and every previously used note after vault sync. Changed or revoked inputs require a new mission. Cloud recovery requires renewed cloud/attachment consent. Recovery does not repeat Telegram notifications.
- The mission workspace offers **Resume unfinished steps**, explains new provider calls and shows recovery lineage. Legacy missions and Office edit modes do not expose recovery.
- Automated cases cover failed and crash-interrupted restart recovery, completed-step reuse, duplicate requests, cancellation, source absence, revoked notes, changed agents, missing cloud consent and the retry cap.
- Remaining: per-section work items and revisions, representative real-model validation and browser validation of the new control. Step-level recovery does not complete REL-002 or establish artifact acceptance.

### MEM-001 progress: 1 November 2026

- Missions can explicitly select up to 20 required notes. Selection uses only those notes in every step; no automatic retrieval substitutes other notes. An empty selection retains automatic retrieval.
- Required notes must be active and permitted for every team member and the whole mission's cloud policy. Missing, revoked or oversized selections fail before inference. Handoff budgets include the complete required-note payload.
- Step records expose note titles, categories, source paths and revision hashes. Required hashes are checked on recovery even when no prior step completed.
- Added reference/preference/demo categories to local memory and Obsidian note properties. Explicitly marked demos are excluded from automatic retrieval but may be selected deliberately. Existing unlabelled demo material needs user classification; titles alone do not establish preference authority.
- Validation: 150 tests pass, JavaScript syntax and 74-file packaging gates pass. An isolated browser check confirmed preference selection survives adding a reviewer and clearly labels demo notes. No customer data or live model calls were used. Review and end-to-end acceptance remain pending.

### ART-001B progress: 1 November 2026

- Unified Office relationship checks across paragraph preflight, placeholder export and exact-text export. External relationships are allowed only for recognized hyperlink types with bounded, structurally validated HTTPS targets and DNS-style hosts; targets are never fetched or resolved.
- Retain citation relationships byte-for-byte. Reject external templates, objects and images; scripts/file URLs; credentials; IP/intranet hosts; nondefault ports; malformed escapes/modes/XML; duplicate relationship IDs; DTDs; embeddings and ActiveX parts.
- Validation: 190 tests pass, all JavaScript syntax checks and the 74-file packaging gate pass. Synthetic DOCX/PPTX linked-run fixtures cover edit and placeholder exports, library reopening, and byte-for-byte equality of all unchanged package parts. API regression verifies rejection before model invocation.
- Remaining: independent code/security review and rendered template-fidelity acceptance. URL syntax checks do not prove source trustworthiness or DNS safety when a user later clicks a link. HTTP and non-HTTPS citation schemes remain unsupported. Issue #7 stays open and in review; broader presentation delivery is not ready for retest.

### REL-002 section checkpoints: 1 November 2026

- Added optional explicit section scopes (maximum six, 1,000 characters each). The selected team runs once per section, with a maximum 24 calls and the existing ten-minute attempt timeout. The composer discloses repeated provider calls and possible cloud charges before submission.
- Each section retains the complete original task, references and required notes. Prior agent outputs are handed off only within that section; they are not silently summarized or carried into unrelated sections. Preflight reserves budgets for every section before starting inference.
- Durable step records bind section ID/scope, draft attempt revision, source revision and provider outcome. Review state remains explicitly not assessed. Recovery reuses the completed prefix across section boundaries and restarts only unfinished work in a new child attempt.
- Section progress appears in the mission workspace. Office export is blocked until artifact assembly exists, so the last reviewer response cannot masquerade as the complete multi-section deliverable. JSON retains every section and draft.
- Validation: 198 tests pass, JavaScript syntax and 74-file package checks pass. New integration tests cover cross-section isolation, shared-source retention, process restart, exact-checkpoint recovery and unchanged original drafts; invalid/duplicate/oversized scopes and unsupported Office modes fail before inference.
- Pending: browser smoke test of the new section controls, representative local-model run, structured review and artifact assembly. No live provider call or rendered presentation acceptance is claimed. REL-002 remains open.

### REV-001 structured draft assessment: 1 November 2026

- Added optional user-defined structured criteria (up to eight) for two-Bulter reference missions, including section missions. The author receives criteria; the reviewer must return schema-valid JSON for every criterion and the exact retained draft hash.
- Reviewer and author identity come from execution records, never model headings. Records bind section, draft revision and SHA-256. Duplicate JSON keys, unknown fields, stale hashes, missing/duplicate criteria, empty pass evidence and invented quotations fail closed. Partial author text cannot receive a passing criterion assessment.
- Passing assessments require exact draft quotations; they do not verify external factual claims or source accuracy. Fail/unknown results remain needs_revision; invalid responses remain invalid. Both produce completed_with_issues while user acceptance stays not_assessed. Office export is blocked for this workflow until artifact assembly exists.
- UI exposes structured criteria and recorded findings. Context preflight reserves the review schema and criterion text. No extra retry or revision calls are introduced.
- Validation: 213 tests pass, JavaScript syntax and 74-file packaging checks pass. Tests cover forged identity, prose agreement, stale hashes, criterion coverage, duplicate keys, invented quotations, incomplete drafts and API status/export boundaries.
- Pending: deterministic slide timing and artifact-existence checks, artifact-hash binding, bounded revision rounds, browser smoke test and real-model evaluation. Issue #4 remains open and in progress; these are draft assessments, not presentation acceptance.

### REV-002 deterministic timing: 1 November 2026

- Added an optional whole-presentation time budget (1–240 minutes, including discussion), requiring structured review without section scopes. The author supplies bounded JSON slides with IDs, titles, body text, speaker notes and integer speaking seconds plus discussion seconds.
- The app validates the complete outline and calculates totals in integer seconds. Missing/ambiguous fields, duplicate slide IDs, coerced numbers and incomplete output cannot pass. Model-provided totals are not accepted. The check binds the exact draft hash.
- Reviewers receive the computed timing report. A model pass cannot override an overrun or invalid timing: the review remains needs_revision, execution completed_with_issues and user acceptance not_assessed. This validates declared timings, not actual delivery speed or a rendered artifact.
- Validation: 226 tests pass, JavaScript syntax and 74-file packaging checks pass. The original 27 + 5 minute failure reproduces as 1,920 seconds, 120 seconds over a 30-minute budget; exact-boundary, malformed timing and false-positive reviewer regressions pass.
- Pending: artifact creation/existence/hash verification, bounded revision rounds, browser checks and representative real-model evaluation. The JSON outline is not a finished presentation.

### Final acceptance sequencing

- Carter's intervention is deferred until the end. Complete remaining implementation and all feasible independent checks first; consolidate presentation, test evidence and limitations into one final review package.
- Code or security review still required by a work item is an independent validation task, not a reason to pause the rest of the backlog. Escalate early only for a genuine dependency on user input or new authorization.

### REV-002 bounded draft revision: 1 November 2026

- Added an explicit **Revise draft and review again** action for unresolved whole-draft structured reviews. It creates a linked child attempt, reruns both agents and supplies complete prior draft/review feedback as untrusted reference data. Prior attempts remain intact and new assessments bind the new draft hash.
- Reuses recovery's source, memory, agent and cloud-consent validation. Full feedback must fit preflight; oversized feedback is rejected without truncation or provider calls. Duplicate child attempts are blocked.
- At most two revision rounds are permitted, within the existing three-attempt recovery ceiling. A passing assessment stops revisions; disagreement remains visibly unresolved. User acceptance is never inferred. There is no automatic retry or paid loop.
- Validation: 231 tests pass, JavaScript syntax and 74-file packaging gates pass. New tests cover full author/reviewer reruns, new-draft hash binding, immutable history, duplicate requests, stop-on-pass, revision cap, missing cloud consent, changed sources and oversized feedback.
- Pending: browser validation, real-model evaluation, per-section revision, artifact assembly/verification and any separately consented automatic revision orchestration. Carter's final review remains deferred until independent work is complete.

### ART-001A artifact-bound Office peer review: 1 November 2026

- Office edit/design-reuse missions now accept two Bulters when explicit structured review criteria are supplied. Single-agent exact-text editing remains supported. This adds text replacement and resulting-file review, not layout editing or visual composition.
- The author proposes grounded replacements; the app applies them to a new Office package before invoking the reviewer. The reviewer receives the complete resulting paragraph projection and artifact SHA-256 instead of being asked to produce more replacement JSON.
- Persist the exact generated bytes privately, with source revision and mission identity. Structured assessment binds the text projection and actual artifact hash. Download checks stored bytes, hash, mission identity and passing review; it never regenerates a different revision from reviewer prose. Failed assessments block download.
- Reject resulting text that exceeds reserved review capacity rather than silently dropping paragraphs. Reference inputs remain untrusted; user acceptance stays not_assessed. The UI discloses package/text-only validation and pending rendered-layout inspection.
- Validation: 239 tests pass, JavaScript syntax and 74-file packaging checks pass. Synthetic DOCX/PPTX tests cover both edit modes, actual edited-text review, passing/failing verdicts, byte-exact export, mismatched format and stored-content corruption. Existing single-agent tests continue passing.
- Pending: rendered/layout validation, Office revision/recovery, browser and representative local-model checks, new diagrams/pictures and source-based composition. Issue #6 remains open and in progress; no presentation-readiness claim.

### ART-001A Office recovery and revision: 1 November 2026

- Extended explicit recovery and bounded revision to two-agent structured Office edit workflows. Recovery after an interrupted reviewer reuses exact artifact bytes under a new child ownership record and hands the artifact text, not author edit JSON, to the reviewer.
- Verify retained bytes, source/memory/agent permissions and the recomputed text projection before recovery or revision. Modified projections fail before inference. Revision creates a new artifact from the original source with full previous artifact/review feedback and a new hash-bound assessment; prior artifacts and missions remain unchanged.
- Corrected author checkpoint status when proposed edits cannot produce a valid artifact. The author step is failed, so recovery cannot skip nonexistent artifact creation.
- Validation: 247 tests pass, JavaScript syntax and 74-file package checks pass. DOCX/PPTX restart regressions cover reviewer interruption without repeated author inference, invalid author proposals, failed-review revisions, changed artifact hashes, exact export and corrupted projection rejection.
- Pending: browser/real-model checks, rendered-layout validation and visual composition. Single-agent legacy Office missions remain outside checkpoint recovery. Final user acceptance remains deferred.

### EVD-001 selected-source registry: 2 November 2026

- Added an opt-in citation requirement for timed structured outlines. The app records selected text attachments and connector snapshots by source ID, title, origin, available recorded date and content hash. It does not invent URLs or retrieval dates; absent dates stay explicitly unavailable.
- Each slide must include structured claims with retained-source IDs and exact evidence quotations. Unknown source IDs, invented quotations, missing slide claims, incomplete drafts and truncated connector evidence cannot pass source-reference checks. Failed checks block a model passing assessment from resolving the mission.
- Source-reference validity is distinct from factual accuracy, quotation context and claim entailment, which remain not_assessed. A supported quotation alone does not prove a claim. No automatic internet research or source authority verification is introduced.
- The registry and claims are included in context reservation, revision feedback and visible mission provenance. Existing attachment/cloud and connector-local-only policies remain in force.
- Validation: 256 tests pass, JavaScript syntax and 74-file packaging gates pass. Regressions cover invented source IDs/quotes, missing claims, partial/truncated references, empty-source preflight and a false-positive reviewer verdict.
- Pending: bounded online research and URL provenance, factual/entailment review, visual slide assembly and rendered validation. Issue #8 remains in progress; final acceptance stays deferred.

### ART-002 editable flow-slide composition: 2 November 2026

- Added opt-in standard PowerPoint composition inside the app, using the validated timed outline. It creates real editable text and flow-diagram shapes/arrows, speaker notes, timing footers and selected-source labels. At least one declared flow is required; describing a diagram in prose does not satisfy the mode.
- Resulting bytes use the same persisted artifact, hash-bound text review and integrity-checked download path as Office edits. Recovery/revision retains artifact lineage. User acceptance remains unassessed and each slide visibly identifies itself as a draft with validation pending.
- Layout budgets reject oversized titles/body/flow labels, unresolved markers and unknown/oversized citation lists rather than shrinking or deleting content. Full source quotations remain in speaker notes. No additional dependency, external call or standalone substitute presentation was introduced.
- Validation: 262 tests pass, JavaScript syntax and 75-file packaging checks pass. Integration tests inspect the actual PPTX: editable nodes/arrows, slide count, notes, timing, shape bounds, review hash and byte-exact download. Invalid-content regressions cover layout limits, placeholders and unknown source IDs.
- Remaining: template-aware styling, pictures with provenance, rendered clipping/readability validation, browser checks, real-model evaluation and bounded online research. Standard composition deliberately rejects uploaded templates; it is not template fidelity or a finished national-wallet presentation.

### ART-002 template theme composition: 2 November 2026

- Composition can now take an attached PPTX as an optional design reference. It retains the source theme, masters/layouts and slide dimensions, samples theme colors/fonts, and replaces obsolete sample slides with generated content on the composition grid.
- Preflight validates Office package safety and supported landscape dimensions before inference. Unsupported portrait/extreme dimensions or non-PPTX designs fail explicitly; no source file is modified.
- This is theme/master reuse, not reproduction of arbitrary slide-specific artwork or exact source arrangements. The UI states that limit. Source slide content is not silently copied into the new presentation.
- Validation: 265 tests pass, JavaScript syntax and 75-file package gates pass. Synthetic tests verify custom theme color/font adoption, unchanged theme/master bytes, retained dimensions, replacement of sample slides, full two-agent composition/export and portrait rejection before inference.
- Pending: real template render/fidelity checks, pictures and provenance, rendered readability/clipping validation, browser/real-model evaluation and bounded online research. Final user review remains deferred.


### ART-002 uploaded picture composition: 2 November 2026

- Composed decks can embed selected normalized image attachments in dedicated picture slides with captions and aspect-preserving placement. Editable flow diagrams remain required on separate slides. An optional requirement rejects missing uploads before inference and missing picture output before review.
- The app records attachment identity, filename and normalized-image SHA-256 in speaker notes and private artifact metadata. The exported file remains bound to the reviewed artifact hash. Existing local vision and attachment-sharing restrictions still apply.
- No remote image URL is fetched, no new dependency is added, and no rights or factual-interpretation approval is inferred from an uploaded image. Unknown image IDs, missing captions, mixed diagram/picture panels and non-normalized assets fail validation.
- Validation: 274 tests pass, all three JavaScript syntax checks and the 75-file source packaging gate pass. Synthetic integration tests inspect actual embedded bytes, captions, aspect ratio, provenance, exact downloads and required-picture failure before reviewer execution, with and without templates.
- Remaining: rendered readability/clipping and actual template fidelity, browser/real-model end-to-end evaluation, bounded online research and final user acceptance. Package/text review does not constitute visual acceptance.

### ART-002 explicit line overflow guard: 2 November 2026

- Fixed a layout hole: text within character limits could contain many short lines and overflow a slide panel. Composition now rejects explicit line counts exceeding panel height at the configured font and line spacing, including CRLF and PowerPoint soft breaks.
- Text panels and diagram nodes use explicit scaled margins, line spacing and zero paragraph spacing, avoiding inherited template paragraph gaps. CRLF/CR normalize to paragraph breaks without dropping content. Four short citation labels remain supported.
- Validation: 287 tests pass, all three JavaScript syntax checks and the 75-file package gate pass. Thirteen new regressions cover title/body/diagram/citation overflow for three newline forms and a valid four-reference panel with deterministic spacing.
- This guard detects explicit-line overflow only. Font-dependent wrapping, long words, overlapping template graphics and overall readability still require actual rendering and inspection; no visual acceptance is claimed. Issues remain open and final user review stays deferred.

### ART-002 reproducible local render evidence: 2 November 2026

- Added `scripts/render_presentation.py`: validates an exported PPTX against its expected artifact SHA-256 and Office package checks, runs local LibreOffice and Poppler, verifies the PDF page count and every slide image, then writes hashes for the PDF and per-slide PNGs into a report.
- Requires a new private output directory (mode 0700); existing evidence is never overwritten. Missing renderers, stale hashes, timeouts and incomplete output fail without a success report. Reports always leave visual inspection pending and user acceptance unassessed.
- Usage: `python scripts/render_presentation.py exported.pptx --sha256 ARTIFACT_SHA256 --output NEW_PRIVATE_DIRECTORY`. Local `soffice` and `pdftoppm` are optional system prerequisites for this developer validation tool; no Python dependency was added. It is not yet a browser render/review workflow.
- Validation: 294 tests pass, three JavaScript syntax checks and the 76-file source package gate pass. Seven regression cases cover success, stale hash, existing directory, missing renderer, wrong page count, missing image and timeout. A real local one-slide synthetic composition rendered successfully; its inspected image displayed the full title, body, three flow nodes/arrows and footer without visible clipping. Font substitution was apparent, so this is not font-fidelity acceptance.
- Remaining: multi-slide and real-template rendering, clipping/readability inspection of actual mission artifacts, browser/real-model end-to-end evaluation, online research and final user acceptance. Render evidence stays private and is not published with source.

## Warnings

- Rendering invokes installed native Office/PDF tools on validated files. Keep these tools updated and use trusted inputs. Successful rendering or page-count checks do not prove visual fidelity, factual correctness, licensing or acceptance.
