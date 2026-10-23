## Checkpoint: Evening Service and Obsidian memory

### What changed

- Warm dark interface: charcoal surfaces, ivory typography, brass accents, a local SVG butler portrait and bow-tie emblem. No remote fonts, images, tracking or new UI dependencies.
- Dark styling across cards, dialogs, forms, missions, memory and provider connections; visible keyboard focus, reduced-motion support and accessible filter state.
- Approved Obsidian memory ingestion with explicit local/cloud and shared/private scope, source hashes, atomic sync and revocation before each mission.
- Local keyword retrieval fits complete notes within the context limit and records selected note IDs and eligible counts per mission step.
- New workflow scenarios use synthetic fixtures and disposable databases. Personal vault contents, original exports, mission history and credentials are excluded from the source checkpoint.

### Test results — 23 October 2026

| Scenario | Evidence | Result |
| --- | --- | --- |
| 140-note vault, two-Bulter handoff | SC01: actual API orchestration with synthetic provider; selected IDs match prompt context; both contexts within 24,000 characters | Pass |
| Withdraw a note between missions | SC02: archived note excluded from the next mission automatically | Pass |
| Invalid teams | SC03: empty, unknown, duplicate and more than four Bulters rejected before inference | Pass |
| Restart persistence | SC04: edited model assignment and private/local note policy survive application recreation | Pass |
| Static app and session isolation | SC05: UI assets served; another application session's token rejected | Pass |
| Scope and cloud egress | Existing tests cover private ownership, inactive notes, cloud consent, credentials and mixed local/cloud missions | Pass |
| Import validation | Existing tests cover malformed YAML, duplicate IDs, linked notes, missing vaults and atomic updates | Pass |
| Provider failures and cancellation | Existing tests cover partial outputs, interrupted streams, cancellation and stopping subsequent handoffs | Pass |
| Live local inference | Two temporary Bulters using Ollama gemma4:e4b, synthetic certificate brief, no memory; both steps completed with nonempty output | Pass |
| Browser checks | Creation dialog, paid-provider selection without saving, cancellation, ordered team selection, provider connection display | Pass |
| Responsive layout | DOM overflow check at 1440px desktop and 390px mobile; default-width visual inspection | Pass with capture limitation below |
| JavaScript syntax | `node --check src/static/app.js` | Pass |

Automated suite: **46 passed**. Run from the repository root:

```zsh
python3 -m pytest -q -p no:cacheprovider src/tests
node --check src/static/app.js
python3 scripts/package_release.py --check
```

The live smoke test used a disposable database outside the workspace; it did not modify existing Bulters, memories or mission history. No paid provider was called.

### Checkpoint and recovery

- Source checkpoint tag: `checkpoint-2026-10-23-evening-service`.
- The commit includes the preceding Obsidian integration and the current UI/testing changes, which were not yet in the initial repository commit.
- Generate a reviewed source archive with `python3 scripts/package_release.py`; it includes a SHA-256 manifest and uses an explicit file allowlist.
- Runtime backups and vault originals remain local. Git recovery restores application source only, not private data. Keep separate private vault/database backups.
- Application start command remains `zsh scripts/run.sh`; open the localhost address printed by the server.

## Warnings

- Paid OpenAI, Claude and OpenRouter adapters were tested with synthetic transport/policy tests only, not real accounts. LM Studio was not running during browser checks.
- Keyword retrieval can miss synonyms, related caveats or conflicts; it is not semantic search or exhaustive evidence validation.
- TestClient emits an upstream Starlette/httpx deprecation warning. All tests pass; no dependency upgrade was made solely to suppress it.
- The in-app browser's viewport override produced clipped/scaled screenshots; desktop/mobile dimensions were checked through rendered DOM measurements. Default-width screenshots rendered correctly. This is not a full cross-browser or accessibility certification.
- Source export scans detect selected secret/path patterns, not every possible secret. The private runtime directory is explicitly excluded from Git and packaging.
