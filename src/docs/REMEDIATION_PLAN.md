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

### ART-002 raster integrity and text-presence checks: 2 November 2026

- Render evidence now fully verifies and decodes each PNG instead of accepting its file signature alone. Reports include raster dimensions and per-slide comparisons between editable PPTX text (including groups/tables, excluding notes) and extracted PDF text.
- Missing text is retained in the private report as `needs_review`; the CLI exits with code 2 while preserving the completed render. Whitespace and Unicode compatibility normalization tolerate ordinary wrapping. Empty-text slides remain unassessed, and neither text presence nor rendering grants visual/user acceptance.
- Validation: 300 tests pass, three JavaScript syntax checks and the 76-file source package gate pass. Added corrupt-raster rejection, missing-text/whitespace checks and grouped/table text coverage. A real two-slide synthetic diagram/picture deck rendered; both images were inspected with no visible clipping, and the picture/caption were present.
- The real test correctly surfaced an extraction discrepancy: a PDF CID marker interrupted the first title despite its visible text being complete. The warning remains in the private evidence. Text extraction can produce false alarms and can also include text that is clipped or obscured; it is a review aid, not a visual verdict. Font substitution, actual-template fidelity and end-to-end mission acceptance remain pending.

### ART-002 inspect unresolved artifact drafts: 2 November 2026

- Fixed a review-workflow gap: a completed author artifact was unavailable for visual inspection when its peer review had unresolved findings. A separate authenticated inspection-only download now serves the retained bytes for finished attempts, without changing review results or user acceptance.
- The endpoint requires a complete author step, matching mission ownership/format, matching artifact hashes and a freshly recomputed paragraph projection. Running attempts, partial authors, missing/corrupt artifacts and stale projections fail closed. Downloads are explicitly named review-only drafts with no-store and artifact-hash headers.
- The UI exposes a capability-gated inspection action. Ordinary completed-artifact export still requires the existing passing review and completed mission; the inspection action cannot bypass that export gate or mark acceptance complete.
- Validation: 316 tests pass, three JavaScript syntax checks and the 76-file package gate pass. Sixteen DOCX/PPTX API regressions cover unresolved-review inspection plus hash, ownership, format, projection, partial-author, running and missing-artifact rejection. Each also confirms ordinary export remains blocked.
- Remaining: browser validation of the new action, actual mission/template rendering and end-to-end model evaluation. Draft inspection is for private review and is not a release or acceptance decision. Final user review stays deferred.

### REL-002 / REV-001 section-scoped revision rounds: 2 November 2026

- Section missions with complete structured author/reviewer pairs can now enter an explicit revision round. Each section receives only its own full prior draft and feedback; every section gets a fresh author/reviewer pair. The UI clearly labels this as revising all sections and gates it on server capability.
- All section context budgets and recorded section identities are checked before scheduling any model calls. An oversized later section rejects the whole request without creating a child attempt. Existing consent, source/memory revalidation, duplicate-child protection, two-round revision cap and three-attempt recovery ceiling remain in place.
- Original attempts remain immutable; new section reviews bind the new drafts. Passing reviews stop further revisions. This is not automatic orchestration, selective failed-section retry or Office artifact assembly; section Office exports remain blocked.
- Validation: 319 tests pass, three JavaScript syntax checks and the 76-file package gate pass. New end-to-end API cases verify section feedback isolation, all-section preflight, mismatched history rejection, immutable parent attempts, fresh review hashes and unchanged export/acceptance gates. Existing whole-draft revision and Office recovery tests still pass.
- Remaining: browser/representative-model validation, section artifact assembly, bounded online research, actual-template rendering and final acceptance. No user intervention is required for this slice.

### REL-002 / ART-002 restart-safe draft inspection: 2 November 2026

- Fixed a restart edge case in the inspection workflow: startup marks active missions interrupted, which previously hid a complete, retained author artifact even if only the reviewer was interrupted. The API and UI now permit inspection-only download for interrupted attempts with a complete author step.
- Ownership, format, artifact hash and projection checks remain mandatory. Running or partial authors remain blocked, as does ordinary accepted-output export. Inspection does not resume inference, change mission state or grant acceptance.
- Validation: 325 tests pass, three JavaScript syntax checks and the 76-file package gate pass. Six fresh-app restart regressions cover DOCX/PPTX with completed, running and partial author steps. The active-run regression now sets its state after startup so it explicitly distinguishes a running mission from an interrupted one.
- Remaining: browser/real-model validation, section artifact assembly, bounded online research and actual-template/end-to-end validation. No acceptance criteria were closed by this change.

### REV-001 browser validation and attempt disclosure: 2 November 2026

- An isolated browser smoke test with synthetic data and mocked model responses found a misleading lineage message: revision attempts claimed completed steps were reused, although both agents ran again. Child attempts now record an explicit revision/recovery kind, and the UI describes the correct behavior. Older records without a kind use neutral wording instead of guessing.
- Browser validation confirmed unresolved composed-draft status, timing and structured-review displays, the inspection-only action, absence of ordinary completed-export controls, and visible revision history. After the fix, the browser correctly stated that author/reviewer run again and the original attempt is preserved. The inspection action was exercised; byte-integrity guarantees remain covered by API tests, not inferred from the unchanged browser view.
- Validation: 326 tests pass, three JavaScript syntax checks and the 76-file source package gate pass. Added executable JavaScript disclosure checks for revision, recovery, legacy and original attempts; strengthened API lineage assertions for revision and recovery. The synthetic server was stopped and its temporary browser tab closed.
- Remaining: representative real-model and actual-template tests, section assembly, online research and broader browser coverage. No private notes/customer template or paid inference was used; this synthetic smoke test is not final wallet-presentation acceptance.

### REV-001 / ART-002 real local-model prompt validation: 2 November 2026

- A bounded synthetic two-agent mission using the installed local gemma4:e4b model exposed two prompt ambiguities. The original author example omitted required flow_steps, and the reviewer later copied the timing-outline hash instead of the resulting artifact-review hash. Both failures were correctly rejected by existing validation.
- The timed author example is now mode-specific and includes real flow geometry for composition, with explicit instructions not to copy sample content/timings. Execution, initial context reservation and revision reservation use the same example. Timing/source hashes remain in stored provenance but are omitted from the model-facing deterministic-check summaries to avoid competing review hashes.
- Three isolated local runs were performed as the prompts were corrected: missing diagram rejected; artifact created but stale review hash rejected; then complete author/reviewer execution with criteria_pass and the requested 60 seconds plus zero discussion. Inspection and ordinary reviewed export returned matching artifact bytes. User acceptance remained not_assessed. No paid calls, private memory, customer template or substitute wallet presentation was used.
- Validation: 328 tests pass, three JavaScript syntax checks and the 76-file package gate pass. New tests validate both example schemas and strengthened composition tests ensure the outline hash is absent from reviewer prompts while timing results remain available.
- The actual local-model artifact was rendered and visually inspected: title, body, consent/issuance nodes and arrow were visible without clipping. PDF extraction still flagged title/body fragments despite their visible presence; the private render report retains needs_review. Font fidelity and extraction reliability remain unresolved.
- This single-slide synthetic success is not representative national-wallet acceptance. Remaining work includes broader model testing, actual-template fidelity, section assembly, bounded online research and final end-to-end acceptance.

### ART-002 supplied-template render validation and footer spacing: 2 November 2026

- Tested the user-supplied template privately through the app's upload, composition, local author/reviewer, inspection and reviewed-export paths using a one-slide synthetic brief. The initial run completed with a passing review and matching export hash. Rendering exposed an actual layout defect: generated timing text overlapped retained footer branding.
- The composition grid now reserves its bottom half-inch for retained footer material. Timing, citation, picture-caption and body panels were repositioned/sized together; five-node flows and four reference labels remain supported. This is a fixed reserved band, not arbitrary template collision detection.
- Validation: 329 tests pass, three JavaScript syntax checks and the 76-file package gate pass. A synthetic master-footer regression verifies preserved footer content and non-overlapping generated panels for both flow and picture slides.
- A second local app run created a fresh template-based artifact. Its rendered image confirmed the generated footer no longer overlapped the retained branding. That run's peer review was invalid and ordinary export remained unaccepted; inspection-only output was used for visual verification. This variability remains evidence against declaring end-to-end readiness.
- Private customer template, generated artifacts, databases and render images were not published. Font substitution/PDF extraction discrepancies, wider template layout fidelity, broader model reliability, section assembly and online research remain pending. No acceptance criteria were closed.

### REV-001 actionable invalid-review diagnostics: 2 November 2026

- The failed reviewer response from the recent local template test was malformed JSON, but the application previously displayed one generic error covering every validation failure. Review records now carry stable error codes and actionable messages distinguishing malformed/duplicate JSON, schema mismatch, wrong draft hash, criterion coverage, incomplete drafts and missing/unverifiable quotations.
- Existing UI and revision feedback already display/carry these records, so future failures identify the correction needed without another model call. Invalid results still contain no accepted criteria; no automatic JSON repair, hash substitution or weakened acceptance rule was introduced.
- Validation: 331 tests pass, three JavaScript syntax checks and the 76-file package gate pass. Existing adversarial review tests now assert each diagnostic category; two new cases verify parser/schema errors do not echo payload content. Revalidation of the retained failed local response reports review_json while keeping the assessment invalid, without running inference or altering stored history.
- Remaining: reliable model conformance, wider model/browser tests, section assembly, online research and full template/end-to-end acceptance. Better diagnostics do not establish that a failed reviewer result is fixed or accepted.

### REV-001 schema-constrained local review: 2 November 2026

- Structured reviewer calls to local Ollama now supply a JSON schema using its documented format parameter, with zero temperature. The schema fixes the expected draft hash, criterion IDs and count while rejecting extra fields. Call options are copied; bot/mission configuration is not mutated. Other providers and ordinary drafting calls retain their existing request formats. Reference: [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
- Syntax constraints supplement rather than replace existing checks: exact evidence quotations, duplicate criteria, artifact identity, timing/source failures and user acceptance are still validated independently. Unsupported servers fail through the existing provider error path; no retry, cloud fallback or paid call is introduced.
- Validation: 333 tests pass, three JavaScript syntax checks and the 76-file package gate pass. Regressions verify transport isolation, schema freshness and requested hash/count/IDs, unchanged stored team configuration, and continued rejection of invalid responses from a mock provider that ignores the schema.
- A bounded real local gemma4:e4b text mission completed both steps with criteria_pass and acceptance not_assessed. A separate template smoke test stopped before review because the author generated a zero-duration slide; it remained failed with no artifact. This run did not establish template-review reliability, and author schema conformance remains an explicit follow-up.
- Remaining: author conformance and wider local-model tests, provider-specific structured output beyond Ollama, section assembly, online research, template rendering/fidelity and final acceptance. No acceptance criteria were closed.

### REV-001 timed-author schema constraints: 2 November 2026

- Local Ollama timed-author calls now use the same TimedPresentation JSON schema as post-generation validation, including positive integer speaking durations, nonnegative discussion and bounded slide fields. The existing provider transport supplies zero temperature for these structured calls. Ordinary drafting and non-Ollama behavior remain unchanged.
- Validation: 337 tests pass, three JavaScript syntax checks and the 76-file package gate pass. Composition integration tests assert the transmitted schema; four new cases prove zero, negative, boolean and string durations still fail before review/artifact export when a provider ignores grammar. Stored team configuration remains unchanged.
- A bounded real local-model run with the supplied template completed author/reviewer execution, passed the configured timing budget, and returned an inspection artifact matching its hash. However, it produced two slides totaling 90 seconds despite the brief asking for one slide and 60 seconds. The configured review criterion covered consent only, so the passing assessment did not detect that mismatch. This is explicitly not successful compliance with the full brief or final acceptance.
- Schemas constrain syntax and field bounds, not arbitrary natural-language requirements. Follow-up remains for explicit slide-count/exact-duration constraints and broader criteria coverage, alongside section assembly, research, actual-template fidelity and final end-to-end validation. No acceptance criteria were closed; all source/runtime artifacts stay private.

### REV-001 explicit slide-count and exact-duration constraints: 2 November 2026

- Added optional exact slide count and exact total duration inputs for timed presentations. Total explicitly includes discussion. Requests reject missing budgets, invalid types/ranges, targets above budget and impossible minimum per-slide timings before execution; no natural-language requirement is silently inferred.
- Constraints persist with the mission and carry into context reservation, author/reviewer prompts, local author schema slide-count bounds and revision attempts. Deterministic validation marks count/total mismatches invalid even when within the maximum budget; a model pass cannot override them or unlock ordinary export. The UI displays configured targets and observed counts/totals.
- Validation: 348 tests pass, three JavaScript syntax checks and the 76-file package gate pass. Eleven regressions cover exact success, slide-count mismatch, under/over exact total including discussion, invalid input, false-positive peer review and preservation across revision.
- A bounded real local-model run using the supplied template and explicit one-slide/60-second constraints completed with one slide, 60 seconds, zero discussion and a passing review. Inspection returned bytes matching the artifact hash, while user acceptance remained not_assessed. This validates that synthetic scenario only, not arbitrary prompt compliance or national-wallet readiness.
- Remaining: browser validation of the new controls, wider model/template tests, section assembly, online research and final end-to-end acceptance. Requirements outside the configured checks still require appropriate review criteria and independent validation.

### REV-001 safe author-outline failure messages: 2 November 2026

- Fixed an error-reporting defect observed in the earlier local author failure: schema exceptions exposed raw input values and library internals in the mission error. Timed-outline parsing now uses one shared boundary that returns actionable format/type guidance without repeating model-controlled values or keys.
- Timing, source validation and artifact composition use the same parser. Invalid JSON, extra/duplicate fields and invalid durations remain rejected. Original model output stays in its existing private step record for inspection; no history is rewritten and no automatic repair or inference is performed.
- Validation: 352 tests pass, three JavaScript syntax checks and the 76-file package gate pass. Four new cases cover private marker values/keys, malformed JSON and duplicate fields; existing API invalid-duration tests confirm the mission error is sanitized and artifact/export gates remain closed.
- Remaining: browser verification of exact constraints, wider model/template validation, section assembly, online research and final end-to-end acceptance. This diagnostic fix does not establish author correctness or complete any acceptance gate.


### REV-001 speaker-note review coverage: 2 November 2026

- Resulting PowerPoint artifact review now includes speaker-body notes, including composed timing/source notes. Previously reviewers only received slide text, so substantive speaker details were outside their evidence. Slide-number/footer placeholders remain excluded, and exact template-edit targets remain unchanged.
- New artifacts record projection version 2; inspection and recovery recompute that version while existing unversioned artifacts retain their original projection. Complete review text still must fit the reserved budget; notes are never silently truncated.
- Validation: 353 tests pass, all three JavaScript syntax checks and the 76-file package gate pass. Regression coverage verifies opt-in extraction, placeholder exclusion, peer evidence quoted from speaker notes, and exact inspection downloads with the new projection; existing legacy inspection/recovery tests also pass.
- Remaining: section assembly, bounded online research, broader browser/model/template validation and final end-to-end acceptance. This closes a text-review coverage gap, not rendered or factual acceptance; all issues remain open.


### REV-001 exact quotation preservation: 2 November 2026

- Found and reproduced silent trimming in the shared form-input configuration: source and reviewer quotations lost leading/trailing whitespace before exact-match validation. This could accept a submitted quotation that did not occur verbatim in the retained source or draft, and persisted peer evidence differed from the model response.
- Evidence strings now explicitly preserve whitespace while ordinary form fields retain their existing normalization. Source quotes still reject whitespace-only values; review quote bounds and safe error codes remain enforced. No dependency or network behavior changed.
- Validation: six regression cases failed before the fix. All 364 tests now pass, alongside three JavaScript syntax checks and the 76-file package gate. Eleven added cases cover spaces, tabs/newlines, Unicode whitespace, blank rejection, exact persisted peer evidence, and API missions where an inexact source or review quotation blocks a model pass and export.
- This is exact-text integrity, not factual truth or entailment. Existing mission history is not rewritten or retroactively revalidated. Section assembly, online research, broader browser/model/template checks and final end-to-end acceptance remain open.


### REL-002 grouped PowerPoint source completeness: 2 November 2026

- Reproduced omission of nested grouped diagram labels and table cells during PowerPoint source ingestion. The upload succeeded with only top-level text, so reviewers could receive an incomplete source snapshot and grouped text escaped the attachment reference-size check.
- Extraction now traverses nested groups iteratively in drawing order, retaining text and table cells once. Non-text connectors remain ignored. Existing decompression, extraction and attachment limits still apply; over-budget grouped sources are rejected rather than silently omitted. No new dependencies or network calls.
- Validation: all three new synthetic regressions failed before the fix. All 367 tests now pass, alongside three JavaScript syntax checks and the 76-file package gate. Tests cover nested label/table order, authenticated attachment snapshot retention and rejection when grouped text exceeds the reference limit.
- Existing retained snapshots are not rewritten; re-upload is needed to extract previously omitted group content. Drawing order is not a claim about visual reading order, and this does not add OCR, SmartArt/chart interpretation or rendered validation. Section assembly, online research and final end-to-end acceptance remain open.


### EVD-001 explicit excerpt provenance: 3 November 2026

- Saved research excerpts now accept an optional source title and HTTPS URL. The UI shows the URL as plain text and labels it user-provided, page not fetched. Recorded time means local save time, not an asserted retrieval/publication date. Existing text-only requests remain compatible.
- Provenance accompanies the selected evidence into the immutable mission source register and reference snapshot. Existing local-only restrictions, exact-quotation checks and source revision validation remain in place. URL validation reuses the bounded HTTPS citation syntax policy; no resolver, fetch, search or model tool was added.
- Validation: 375 tests pass, three JavaScript syntax checks and the 76-file package gate pass. Eight new cases cover metadata retention into a mission, timezone-aware recording, no HTTP client creation, six unsafe URL forms rejected before storage and legacy requests. An isolated browser check saved synthetic provenance, displayed the unverified-source label and selected the excerpt for a local mission. The test server/tab were closed; no model mission or paid call ran in that browser.
- Remaining: automatic bounded online research and publisher/content verification, source URL inclusion in artifact citation rendering, section assembly, broader template/model validation and final end-to-end acceptance. A user-provided URL is not evidence that a page contains the excerpt. No acceptance gate was closed.


### EVD-001 citation provenance in composed artifacts: 3 November 2026

- Composed PPTX source labels now link to supplied HTTPS citation URLs. Cited-source titles, IDs, URLs, recorded timestamps and provenance labels are retained in speaker notes, making them available in the artifact-bound peer-review projection. Unused sources are not added to the slide notes.
- Composition revalidates URLs against the existing Office hyperlink policy before creating relationships. Missing URL/date/provenance remains explicitly not supplied/not recorded/unverified. Recorded time is labelled as distinct from retrieval/publication time. Full URLs stay in notes to avoid overflowing visible citation panels; multiline labels retain the correct link mapping. No URL is fetched.
- Validation: 380 tests pass, three JavaScript syntax checks and the 76-file package gate pass. Five new cases verify native-library hyperlink reopening, provenance in notes and reviewer projection, exclusion of unused source metadata, three unsafe URL forms and multiline link mapping. Existing composition/template/inspection/recovery tests also pass.
- Remaining: publisher/content verification, automated bounded research, rendered hyperlink styling and representative template/model checks, section assembly and final end-to-end acceptance. A clickable citation and exact quotation do not establish factual support. No private source artifacts were published and no acceptance gate was closed.
