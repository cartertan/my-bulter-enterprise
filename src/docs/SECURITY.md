## Security model and publication boundaries

### Intended deployment

- One trusted macOS user, one server worker, `127.0.0.1:8765` only.
- Local inference by default; paid-provider calls only after mission-level consent.
- No model-controlled browser, shell, email, filesystem or external-action tools.

### Implemented controls

| Control | Scope |
| --- | --- |
| Host, Origin and Fetch Metadata checks | Reduce cross-origin browser access and DNS rebinding exposure |
| Process-generated API request token | Required for API reads/writes; rotates on restart |
| CSP and safe DOM text nodes | Prevent model/user content from being interpreted as HTML or scripts |
| Request and prompt bounds | Limit accepted request bodies, fields, context and output |
| Fixed provider registry | No arbitrary endpoint URLs submitted by users |
| Server-side secrets | Instance-scoped macOS Keychain entries; SQLite contains only an instance UUID and status metadata. Write-only key entry; no secret-read API, environment fallback or memory integration |
| Memory scope and egress filtering | Enforced before model invocation, including across mixed-provider missions |
| Sanitized provider failures | Avoid displaying remote response bodies or exception text that may contain sensitive data |
| Parameterized SQL and private file permissions | Protect local persistence from common application mistakes |
| No automatic paid retries or fallback | Avoid unintended cloud routing and repeated paid execution |

### Important limitations

- The local request token is visible to anyone who can read the served page. It is not user authentication.
- Loopback restrictions do not protect against malware or another process operating as the same OS user.
- Keychain uses the Python application's OS access rights. Instance namespaces prevent accidental cross-instance lookup; they do not isolate malicious code running as the same user. Database copies on the same Mac retain the same instance UUID and references. See [credential setup and threat boundaries](CREDENTIALS_AND_VISUALS.md).
- SQLite and exports contain plaintext. Disk encryption and OS access control remain operational responsibilities.
- Private notes may influence outputs intentionally forwarded to other Bulters. This is retrieval isolation, not information-flow enforcement on generated language.
- Consent applies to the submitted brief, eligible notes and handoff outputs; the system does not detect all confidential content.
- Current context limits are character-based, not model-specific token limits.
- The application trusts each local model runtime; endpoint locality alone does not establish that every configured runtime performs only local inference.
- Stopping a cloud request cannot guarantee that the provider stops billing immediately.
- Deactivated notes may remain in historical outputs; no automatic retrospective redaction occurs.
- Whole-state API polling and frequent output writes are suitable for a small prototype, not an established scaling design.

### Local image engine

- Image models run in an optional isolated MFLUX environment, not the web server process or a cloud API.
- Setup downloads pinned public snapshots with implicit Hugging Face authentication and telemetry disabled. Generation sets offline modes and loads explicit local paths.
- The worker inherits only selected OS environment variables; provider API keys and tokens are not passed to it. Prompts travel on standard input, not process arguments.
- Output PNGs omit prompt/EXIF metadata. Runtime folders are excluded from publication, and image jobs do not retrieve Obsidian notes.
- A process lock serializes image jobs and a timeout bounds each worker. These are resource safeguards, not an OS sandbox. The application trusts MFLUX, MLX and the installed model data.

### What must stay out of GitHub

- `.env` and other credential files, private keys and certificates with private key material.
- SQLite databases, notes, mission exports and screenshots of personal work.
- Model weights, virtual environments, caches, logs and release ZIPs.
- Existing local Git history or unreviewed artifacts from other projects.

The source packager reads only a fixed allowlist and refuses selected suspicious patterns, symlinks and unexpected files. This is a focused accidental-disclosure check, not a comprehensive secret scanner or security audit. Manual review of the staged diff remains required.

### Reporting an issue

Do not post credentials, prompts, customer data or database files in a public issue. Provide a minimal synthetic reproduction, affected version and redacted error description. No private vulnerability contact has been configured in this initial repository; use a private maintainer channel or GitHub private vulnerability reporting if the maintainer enables it.

## Warnings

- Do not publish this app behind a public URL or with `--host 0.0.0.0` without a separate authentication and deployment design.
- No external penetration test, compliance assessment or third-party dependency vulnerability audit has been performed for this release preparation.
