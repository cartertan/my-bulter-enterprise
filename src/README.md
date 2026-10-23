## My Bulter Enterprise

A local-first, single-user AI team dashboard built with Codex. Each **Bulter** has a name, specialty, instructions, provider, model and explicit memory access. A **mission** passes one brief through one to four Bulters in the order you choose.

### Start from a cloned or extracted repository

1. Open Terminal.
2. Open the repository root in Terminal (the folder containing `src/` and `scripts/`). For first-time installation, follow [the portable setup guide](docs/SETUP.md).

3. Start Ollama using its installed application. If it is not running, use `ollama serve` in a separate Terminal window. If it reports that the address is already in use, a server is already listening; check Models & connections in the dashboard.
4. Start the dashboard:

   ```zsh
   zsh scripts/run.sh
   ```

5. Open [My Bulter Enterprise](http://127.0.0.1:8765) in your browser.
6. Keep the Terminal window open. Press Control-C there to stop the dashboard. Your saved Bulters, memories and mission outputs remain on disk.

The initial build reuses Python 3.12 and packages already installed on this Mac. No model downloads, package installs or paid generation calls were performed to create the application. The server must run as one process/worker on loopback.

### First mission

1. Select **Create Bulter**. Give it a name, specialty and working instructions.
2. Choose **Ollama** and select an installed chat model from the Model ID field. The initial live test used `gemma4:e4b`; model choices are discovered from your running server.
3. Enable shared memory only if this Bulter should use workspace notes.
4. Repeat for a second Bulter with a different specialty. Bulters may use the same model or different models.
5. Under **Memory**, add a note. Choose a private owner or shared workspace, and leave cloud permission off unless you intend to send it outside this Mac.
6. Under **Missions**, enter a brief and click your Bulters in execution order. Click again to remove one; reselect to change its position.
7. Start the mission. Each Bulter receives the original brief, its permitted notes and the outputs of preceding Bulters. Watch results appear, stop the run if needed, or export its JSON record.

Two starter Bulters, Atlas and Scribe, and a clearly labelled demo memory were created on the original development machine during UI verification. Their test mission used synthetic, non-confidential content. That runtime data is excluded from Git and the source ZIP. A new clone starts empty; create your own Bulters using the available starter templates.

### Providers

| Provider | Endpoint | Setup | Verification status |
| --- | --- | --- | --- |
| Ollama | `http://127.0.0.1:11434` | Run Ollama and choose an installed chat model | Local discovery and generation tested |
| LM Studio | `http://127.0.0.1:1234` | Developer tab → start local server; load a chat model | Adapter implemented; not live tested |
| OpenAI | `https://api.openai.com/v1/responses` | Server environment `OPENAI_API_KEY`; exact model ID | Payload/parser tests; paid call not tested |
| Claude | `https://api.anthropic.com/v1/messages` | Server environment `ANTHROPIC_API_KEY`; exact model ID | Payload/parser tests; paid call not tested |
| OpenRouter | `https://openrouter.ai/api/v1/chat/completions` | Server environment `OPENROUTER_API_KEY`; exact model ID | Payload/parser tests; paid call not tested |

- The provider picker is API-based. Do not assume a consumer ChatGPT or Claude subscription grants these API calls; confirm API credentials, model access and billing with the provider.
- Supply keys through the server's process environment using your existing secure workflow, then restart the dashboard. The app does not read or modify existing credential or `.env` files.
- Never paste keys into prompts, memories, the model ID field or this chat. There is intentionally no browser key-entry form in this version.
- The dashboard reports key presence only, not validity. It makes no cloud discovery request and no automatic paid retry.
- The launcher uses fixed documented provider endpoints. Arbitrary remote hosts and custom gateways are intentionally unsupported in this phase.

### Optional isolated setup

For a dedicated environment, these commands create files only under `src/` and install the four pinned dependencies. Review before running; this setup is optional on the current Mac.

```zsh
python3 -m venv src/.venv
source src/.venv/bin/activate
python3 -m pip install -r src/requirements.txt
zsh scripts/run.sh
```

### Memory rules

| Note policy | Effect |
| --- | --- |
| Private | Retrieved only by its owner Bulter |
| Shared | Retrieved only by Bulters with shared memory enabled |
| Local only | Excluded from every step of any mission containing a cloud provider |
| Cloud-approved | Eligible for a cloud mission, still subject to private/shared scope |
| Inactive | Excluded from future missions |

- Notes are explicitly entered and edited by you. No automatic memory extraction or embeddings are used.
- Bulters do not share their entire histories. A new mission has fresh task context, plus permitted memories.
- Previous outputs in the current mission are intentionally handed forward. A private note can influence its owner's output, so private retrieval is **not** a guarantee that the resulting answer remains private from teammates.
- Disabling a note does not redact old outputs or cancel a mission already using a memory snapshot.
- A mixed local/cloud mission excludes local-only notes before the first step, closing the indirect local-to-cloud handoff path. The user-entered brief itself is still transmitted if cloud is approved.

### Architecture and limits

- Browser: buildless HTML/CSS/JavaScript, served from the same FastAPI process. All user and model text uses safe DOM text nodes, not HTML.
- Backend: FastAPI, HTTPX provider adapters and SQLite persistence. SQLite statements are parameterized; files are private to the current OS account.
- Execution: one active mission; at most four sequential calls; no autonomous delegation, tools or external actions.
- Generation: 2,048 output tokens per call where supported; 16,000-character response cap; ten-minute mission timeout. Provider idle timeout is 180 seconds.
- Context: rejects constructed context over 24,000 characters. This is a conservative application limit, not exact model token accounting; some models may reject or truncate smaller inputs. Model-specific tokenizer budgeting remains future work.
- Streaming: provider text is saved incrementally; the browser refreshes active mission results every 1.2 seconds.
- Persistence: `src/.runtime/bulter.sqlite3`. Set the process variable `BULTER_DATA_DIR` to an approved location to change it. No backups run automatically; stop the app before copying the database.
- History: saves mission brief, Bulter configuration snapshots, output, status and memory IDs used. It does not retain immutable memory revision content, so this is an activity log, not a compliance-grade audit trail.
- Reliability: failed calls stop the chain. Partial outputs remain. Restarted missions are marked interrupted and are not automatically rerun.

### Implementation scope

| Delivered in this iteration | Next iteration, subject to approval |
| --- | --- |
| Original responsive dashboard | UI refinements and expanded personalisation |
| Create/edit Bulters and choose local/cloud model IDs | Cloud model catalogue and account validation |
| Explicit private/shared memories | Searchable memory with source provenance and revisions |
| Sequential multi-Bulter handoffs | Branching tasks, reviewer loops and approval checkpoints |
| Durable mission history and JSON export | Continuing conversations and mission follow-up |
| Local streaming and Stop | Markdown/code formatting and richer artifacts |
| Cloud policy and provider adapters | Live paid-provider validation and usage budgets |

### Verification

Run from the project directory:

```zsh
python3 -m pytest src/tests -q -p no:cacheprovider
node --check src/static/app.js
```

Tests cover memory isolation and egress, explicit cloud approval, credential absence, ordered handoffs, cancellation, concurrent mission rejection, failures, restart recovery, context bounds, provider parsing, invalid input and cross-origin access. Mocked tests do not establish real paid-provider compatibility.

### Reference basis

- [Grok Bot public introduction](https://x.ai/news/introducing-grok-bot): workflow inspiration only. No proprietary implementation was inspected or copied.
- [Ollama chat API](https://docs.ollama.com/api/chat).
- [LM Studio local server](https://lmstudio.ai/docs/developer/core/server).
- [OpenAI text generation](https://developers.openai.com/api/docs/guides/text).
- [Claude Messages API](https://platform.claude.com/docs/en/api/messages/create).
- [OpenRouter chat completions](https://openrouter.ai/docs/api/api-reference/chat/create-a-chat-completion).

## Warnings

- This is a local single-user prototype, despite the Enterprise product name. It has no multi-user login, RBAC, tenant isolation or enterprise certification.
- Keep it on loopback. The request token and origin/host checks defend against browser-origin attacks, not malicious processes running as your macOS account.
- SQLite, exported mission records and backups contain readable content. Use FileVault and protect backups appropriately.
- Stopping closes the upstream stream and blocks subsequent steps. A remote provider may already have processed or charged for generated tokens.
- Model responses and teammate outputs are untrusted. Prompt instructions reduce accidental confusion but do not establish a hard prompt-injection security boundary. No shell, browser, email or filesystem tools are exposed to models.
- Privacy controls apply to explicit notes. They cannot identify confidential data you type into a cloud-approved brief or prevent a model from restating data already in that brief.
- Local applications and model runtimes may have their own networking/logging behaviour. The dashboard adds no analytics, external fonts or tracking.
