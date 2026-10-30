## Mission reliability and artifact delivery remediation

### Objective and release policy

Deliver a trustworthy local author/reviewer workflow that can eventually create and validate a template-based presentation. A successful model call, model agreement and a user-accepted deliverable are different outcomes. Keep them separate in storage, UI and release claims.

The initial acceptance exercise failed despite passing unit tests. Failures included unsupported team/template combinations, output exhaustion before review, incorrect arithmetic, unsupported citations, irrelevant demo memory and missing rendered artifacts. Reproduce these with synthetic fixtures; never publish the original customer template, personal notes or mission database.

Assumptions: one local user, one worker, explicit cloud consent, no automatic paid retries. Enterprise hosting, tenant isolation and authentication are separate workstreams and are not implied by this roadmap.

### Prioritized delivery pipeline

| Order / issue | Priority | Work package and dependencies | Acceptance gate | Status |
| --- | --- | --- | --- | --- |
| REL-001 | P0 | Classify output exhaustion; explicit incomplete-draft handoff; preserve partial evidence; distinguish execution from acceptance | Opt-in reviewer receives flagged partial output; default still stops; interrupted runs never become accepted artifacts; provider budgets honoured | Implemented in working tree, automated regression verified |
| REL-002 | P0 | Context budgeting and resumable per-section generation, after REL-001 | Large synthetic template + draft reaches review without dropping evidence; bounded continuation, cancellation and restart recovery; no automatic paid retry | Next |
| REV-001 | P0 | Structured per-agent review records and acceptance criteria, after REL-001 | Store agent identity independently of generated headings; parse criterion result/evidence; invalid or missing fields cannot pass; `completed` never implies `accepted` | Planned |
| REV-002 | P0 | Deterministic checks and bounded author/reviewer revision rounds, after REL-002 and REV-001 | Code totals slide durations and checks artifact existence; two-agent loop stops on acceptance, limits or unresolved disagreement; 27 + 5 fails a 30-minute budget | Planned |
| MEM-001 | P0 | Explicit mission memory selection and visible provenance | Users can select approved preference notes within existing access policy; demo notes do not silently become personal requirements; selected hashes preserved; oversized selections rejected clearly | Planned, can precede REV-002 |
| EVD-001 | P1 | Source register and bounded research evidence | Every factual claim links to retained source ID, retrieval date and scope; invented source IDs rejected; missing support remains unverified; browsing assistance identified honestly | Planned |
| ART-001 | P1 | Office capability preflight and safe relationship handling | Unsupported edits rejected before inference; allow only validated citation hyperlink relationships while rejecting external templates/objects and unsafe targets; template fidelity tests pass | Planned |
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

### Next package: REL-002 design and test contract

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

- Partial review improves recovery, not factual correctness. It does not repair missing content or guarantee that the next step fits the context limit.
- Existing Office template restrictions and lack of autonomous visual composition remain. The original end-to-end presentation scenario is still not ready to pass.
- Automated secret-pattern checks are a limited guard, not proof that all source or screenshots are safe to publish. Human review remains required.
