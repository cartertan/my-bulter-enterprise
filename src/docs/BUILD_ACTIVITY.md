## Build activity and implementation record

### Summary

On 23 October 2026, My Bulter Enterprise was designed and implemented through an interactive Codex workflow. The objective evolved from a Grok-style chat application into an original dashboard for named bots, independent model assignments, explicit shared memory and visible collaboration.

This is an engineering activity record based on the development conversation, repository and recorded test results. It is not a raw chat transcript, a claim of independent certification or a reconstruction of Grok's private architecture.

### Requirements established

- Product name: **My Bulter Enterprise**; individual bots are **Bulters**.
- Build and operate on the user's MacBook using Codex as the development assistant.
- Provide a usable dashboard for bot configuration and provider/model selection.
- Integrate installed Ollama models, with optional LM Studio and paid providers.
- Allow Claude, OpenAI and OpenRouter as explicit model providers.
- Support deliberate sharing of context and cooperation between bots.
- Use an original dashboard; the user explicitly selected this over providing a reference UI.
- Advance through reviewable iterations; leave account-specific cloud testing for a later step.

### Activity sequence

| Stage | Work performed | Result / evidence boundary |
| --- | --- | --- |
| 1. Recover intent | Read the referenced chat and current request | Earlier architecture response was unavailable; no unseen design was assumed |
| 2. Define architecture | Proposed Python/FastAPI, buildless UI, SQLite and provider adapters | Single-user, local-first design chosen |
| 3. Inspect environment | Checked workspace, Python, packages and installed model manifests | Empty source workspace; Python 3.12.4 and required packages available |
| 4. Research interfaces | Consulted public Grok description and official provider APIs | Used workflow inspiration and documented protocols, not proprietary reverse engineering |
| 5. Establish scope | Defined Bulters, Missions, Memory and Models views | Original dashboard and explicit memory permissions |
| 6. Build backend | Implemented validation, persistence, discovery and request protection | `app.py`, `storage.py`, `providers.py` |
| 7. Build orchestration | Added ordered handoffs, snapshots, output persistence, timeouts and Stop | One active mission, at most four steps, no autonomous tools |
| 8. Build UI | Created responsive layout, forms, model selection, activity and export | Buildless HTML/CSS/JavaScript |
| 9. Test policy | Tested isolation, egress, consent, failures, cancellation and restart | Initial 17 tests passed; expanded suite reached 22 |
| 10. Validate in browser | Created Atlas and Scribe, assigned `gemma4:e4b`, added a synthetic local-only shared note | Forms and local persistence exercised through UI |
| 11. Run real inference | Sent a synthetic document-review collaboration brief through Atlas → Scribe | Both steps completed; Scribe used Atlas's output; one permitted note per step |
| 12. Restart and verify | Restarted local dashboard and reloaded it | Two Bulters, one note and completed mission persisted |
| 13. Prepare publication | Added portable setup, architecture, activity, security and publishing docs; source-only packaging | Personal runtime state excluded; no GitHub upload performed by preparation |

### Design tasks and rationale

- **Translate product language into objects:** map a Bulter to reusable instructions/model configuration, a memory to a scoped explicit note, and a mission to a bounded execution record.
- **Separate inference from identity:** bot names and specialties are independent of model choice; two specialists can use one model or different models.
- **Make collaboration visible:** show the chosen sequence and persist every contribution instead of implying an unseen autonomous swarm.
- **Specify memory access before prompting:** compute eligible notes server-side rather than trusting the model to enforce access rules.
- **Account for mixed teams:** exclude local-only notes from the entire cloud-containing workflow, avoiding a deliberate indirect handoff path.
- **Preserve reviewability:** save partial outputs, configuration snapshots, statuses and memory IDs, and keep cloud use explicit.
- **Keep the prototype maintainable:** use standard-library SQLite, small provider adapters and an unbundled frontend rather than adding a framework or vector database prematurely.

### Problems encountered and resolutions

- An initial local connection check ran inside a restricted execution environment and could not reach the model server. That check did not prove Ollama was absent. With local execution permitted, the app discovered four chat models.
- Attempts to bind the dashboard from the restricted environment were denied. The localhost launch was subsequently allowed and verified in the browser.
- A server-start attempt reported that Ollama's port was already in use; the existing server was reused rather than replaced.
- Stream and lifecycle handling was strengthened to detect incomplete/limited output and queued cancellation, and to mark interrupted steps after restart.
- Tests reported a Starlette TestClient deprecation warning about HTTPX compatibility. The tests passed; the warning is documented, not hidden, and dependency migration remains separate work.

### Validation matrix

| Area | Validation performed | What this does not prove |
| --- | --- | --- |
| Local Ollama | Real discovery and two-step generation | All installed models, model performance or future runtime versions |
| UI | Browser form creation, shared-note entry, mission execution and restart | Exhaustive browser/accessibility testing |
| Memory policy | Automated private/shared, active/inactive and mixed-cloud tests | Model-level confidentiality or malicious-runtime isolation |
| Execution | Automated order, cancellation, busy guard and failure tests | Durable job scheduling or multi-worker correctness |
| Cloud adapters | Mocked payload, parsing and egress tests | Account access, billing, live compatibility or cost ceilings |
| Persistence | Restart and record persistence checks | Backup/restore certification, migrations or at-rest encryption |

### Publication preparation

- Added a repository landing page and documentation suitable for GitHub Markdown, including Mermaid diagrams.
- Replaced workstation-specific startup paths in the operator guide with repository-relative instructions.
- Made the workspace label neutral for new users; retained author attribution in source documentation.
- Added repository-wide ignore rules and an explicit packaging allowlist.
- Added packaging tests and checks for accidental local state and selected common credential patterns.
- Provided reviewable commit/push commands, without modifying GitHub account state or choosing a public license on the maintainer's behalf.

Publication preparation validation on 23 October 2026: **29 tests passed** (22 application tests plus seven packaging cases); JavaScript syntax check passed; 21 allowlisted source files passed the focused credential/path checks. The existing Starlette TestClient deprecation warning remains. No source upload, repository creation or commit was performed by this preparation step.

### Remaining scope

- Live validation for LM Studio and paid providers; model availability and billing verification.
- Persistent conversational follow-up, memory revisions/search and source citations.
- Rich Markdown/code display, document ingestion, artifact handling and review loops.
- Robust production authentication, role-based access, tenant separation, encrypted storage, job queues and operational monitoring before shared deployment.

## Warnings

- Demo content, local screenshots, model weights and databases are not included in the published source package.
- No performance benchmark, enterprise certification, external penetration test or cloud account validation is claimed.
