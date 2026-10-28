## Reusable Product and Codex Workflow Templates

Copy these into project documentation and GitHub Issues as needed. Replace placeholders with verified information. These templates are proposed conventions, not mandatory Codex configuration files.

### 1. Product brief

```markdown
## Product and owner
Name:
Owner:
Primary user:

## Problem and outcome
Today the user struggles with:
The product will let them:
A successful first use looks like:

## Main workflow
1.
2.
3.

## First release
Must have:
Explicitly deferred:

## Environment and constraints
OS / hardware:
Existing services:
Local vs hosted:
Permitted dependencies:
Budget or usage constraints:

## Data boundaries
Sensitive inputs:
Storage and retention:
External transmission:
Credential handling:
Actions requiring confirmation:

## Examples and acceptance
Synthetic input:
Expected output:
Three observable acceptance checks:
Open questions:
```

### 2. GitHub issue — filled Butler example

```markdown
## Outcome
A user can upload a DOCX as reference material for one mission.

## Context
Read the applicable repository instructions and the mission attachment spec.
Inspect the current mission API, document extractor and UI before editing.

## Scope
Upload, extraction preview, selected attachment IDs, inference context,
mission history and negative tests.

## Not included
Photo analysis, persistent memory import, Office editing, new connectors.

## Acceptance criteria
- An authenticated user can upload a valid synthetic DOCX and preview text.
- Only selected references are supplied to that mission.
- No Obsidian note is created by uploading or running the mission.
- Missing IDs, oversized files and malformed content fail visibly.
- Cloud sharing requires the documented attachment and mission approvals.
- Existing mission behaviour remains covered by tests.

## Verification
Automated tests with temporary storage and mocked providers.
One browser upload check using a synthetic file.
No paid provider call or private document required.

## Deliverables
Implementation, tests, updated guide and a concise evidence summary.
```

### 3. Architecture decision

```markdown
## Decision: <short title>
Status: Proposed / Accepted / Superseded
Date:
Related issue:

## Context
What requirement or constraint forces a choice?

## Options
Brief alternatives and their relevant tradeoffs.

## Decision and consequences
Chosen approach and why:
Limitations accepted:
Security / operational implications:
Revisit when:
```

For example: keep provider credentials in macOS Keychain with instance-specific references in the database. Revisit the storage design if deployment moves away from a single-user Mac. Do not put real credentials in the decision record.

### 4. Start a planning task

```text
Use this repository as the source of truth.
Read the applicable AGENTS.md and the product brief.

For the feature described below, inspect relevant existing behaviour,
identify material ambiguities and propose the smallest testable increment.

Produce:
- User workflow and explicit exclusions
- Data and permission boundaries
- Acceptance criteria and failure cases
- Dependencies and a short ordered issue list

Do not implement application changes in this planning task.
Do not assume untested integrations work.
Feature: <description>
```

### 5. Start an implementation task

```text
Implement issue <number or pasted issue text> in this repository.
Read applicable instructions, current project state and the linked spec.
Inspect additional code as needed; do not load the whole project history.

Complete only this coherent outcome. Preserve unrelated local changes.
If a material ambiguity changes privacy, scope or output behaviour, ask
one focused question; continue independent work where useful.

Run relevant tests, inspect the final diff and verify the acceptance criteria.
For UI changes, check the rendered behaviour using synthetic data.
Update relevant documentation and the short handover.

Report changes, observed test results, untested areas and the next action.
Do not claim that mocked tests prove live provider access.
Do not push, publish or perform account writes unless authorized.
```

### 6. Review and acceptance checklist

```markdown
## Acceptance review
- [ ] Each acceptance criterion has evidence or an explicit gap.
- [ ] Success, invalid input and interruption/failure paths are covered.
- [ ] Sensitive data does not enter prompts, logs or releases unexpectedly.
- [ ] Tests run and their actual results are recorded.
- [ ] UI changes were inspected where applicable.
- [ ] New dependencies and setup changes are documented.
- [ ] Unrelated changes were preserved and excluded from this review.
- [ ] The owner can demonstrate the intended workflow.

## Decision
Accept / Request changes / Defer
Reason:
Follow-up issues:
```

### 7. Short handover

```markdown
## Current checkpoint
Date:
Issue / milestone:
Branch and commit (or uncommitted status):

## Verified
Completed behaviour:
Tests and exact outcomes:
Manual or live checks:

## Remaining
Known limitations:
Blocked work and prerequisite:
Next concrete action:

## Context for next chat
Relevant files:
Decisions to preserve:
Uncommitted work / running processes:
```

Aim for 200–400 words. Keep historical detail in issues, commits and decision notes. Update status when evidence changes; do not append a transcript to this file.

### 8. Pull request and release note

```markdown
## Problem and resulting behaviour
What was difficult or broken, and what now happens?

## Scope
Included changes:
Explicit exclusions:

## Validation
Automated:
Manual / live:
Not tested:

## Setup and compatibility
New dependencies:
Data migration or backup needs:
Known limitations:

## Review evidence
Related issue:
Synthetic screenshots or example outputs:
```

### 9. Context discipline checklist

- Keep durable rules in repository instructions and detailed behaviour in linked specifications.
- Start a fresh focused chat for the next independent outcome; supply the issue and short checkpoint.
- Request focused searches and bounded logs, not repeated dumps of whole files or histories.
- Use representative synthetic fixtures rather than loading large private source collections for development.
- Run relevant tests after changes; repeat broad checks when changes or failures justify them.
- Introduce automation only after the manual workflow is understood and repeatable.
- Treat account usage limits separately from the amount of context in a conversation.

## Warnings

- A template is not evidence. Replace suggested test results with actual observations.
- Do not include secrets or personal data in issues, handovers, prompts or screenshots.
- A fresh chat does not reset account limits, and additional agents do not guarantee lower total usage.
