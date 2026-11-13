## Interim automated functional review — 13 November 2026

### Outcome

- Core workflow mechanisms work in the tested scenarios. Reliable authoring and semantic review are not yet demonstrated across the configured model pair. Overall functional acceptance remains open.
- Carter accepted mission setup before this run. That acceptance does not cover model outputs or final presentation quality.
- Checks used isolated databases and synthetic content. No existing missions, bot configurations, personal notes or customer templates were changed. No paid model calls were made.

### Current test results

| Function | Result | Evidence and limit |
| --- | --- | --- |
| Regression/release checks | PASS | 712 tests, three JavaScript syntax checks, 78-file source gate. Existing Starlette/httpx deprecation warning. |
| Author-to-reviewer handoff and structured review | PASS on Gemma fixture | Two real gemma4:e4b calls; 91-word draft, valid hash-bound review, exact quotations and passing criteria. Acceptance stayed not_assessed. |
| Explicit retained-word limit guard | PASS in regression/API checks | False passing reviews above an explicitly configured limit are rejected. Free-form prose is not automatically converted into this contract. |
| Qwen author / Granite reviewer model pair | FAIL task fulfillment | Fresh isolated roles using qwen3.8:27b and granite4.1:30b, the same model IDs configured for the wallet team. The author generated a rejection/review object instead of a draft. Reviewer returned unknown; app correctly marked completed_with_issues. This did not reproduce the saved bots' complete instructions. |
| Adversarial semantic review | FAIL | Gemma reviewer approved a 243-word retained draft against an under-150 prose requirement and omitted the prohibition on simulated review/approval claims. This single-reviewer attachment challenge did not specify the explicit deterministic criterion. |
| Section picture/flow generation | PASS on synthetic fixture | Four real local calls; two completed sections; picture, timing and layout checks passed; inspection PPTX returned 200. |
| Rendered picture and editable flow layout | PASS with extraction warning | Both pages inspected: picture/caption on page one, two-step graphical flow on page two, no observed clipping. Primary PDF extraction flagged flow-body text; independent extraction and visual inspection found it. Original report warning retained. |
| Dual artifact text review and final export | PASS on synthetic fixture | Two additional local reviews passed; final export returned 200 and matched the reviewed/inspected bytes exactly. |
| Full 30-minute researched wallet deck and real Obsidian personalization | NOT VERIFIED | This run used small synthetic fixtures, not the full original acceptance brief. |

### Interpretation and next priorities

- Model agreement is not a reliable substitute for requirement validation. The application correctly preserves the distinction between execution, criterion assessments and user acceptance, but semantic false positives remain.
- Prioritize explicit execution-stage assignment for the configured author/reviewer pair and repeat both valid and deliberately failing cases. Do not treat another successful Gemma example as proof that Qwen/Granite works.
- Retain deterministic checks for count/timing/layout and verify representative content independently. Synthetic pictures demonstrate embedding, not image relevance or suitability for the wallet presentation.
- No source behavior was changed during this review. No merge or release was performed.

## Warnings

### Follow-up fixes and retests

- Explicit execution-stage instructions corrected the observed author-as-reviewer behavior in subsequent isolated Qwen/Granite runs.
- Bounded literal quotation choices fixed the next observed escaping mismatch without relaxing exact-evidence validation.
- One live run produced 172 words despite a claimed 135; the app rejected the review's false pass against the maximum-150 contract. A final run on the finished source produced 56 retained words and a valid passing review. The reviewer still echoed the author's inaccurate 48-word claim, so semantic reliability remains unresolved.
- Release checks after these changes: 714 tests, three JavaScript checks and 79 allowlisted files pass. The report is now explicitly included in the package allowlist; its earlier omission was detected and corrected.

- Do not rely on model PASS results alone to approve a deliverable.
- The app is suitable for further supervised functional testing; it is not yet established as a dependable autonomous presentation workflow.
