## Prerequisites and Mac setup

### Required components

| Component | Requirement and purpose |
| --- | --- |
| macOS | A supported Mac installation; current Ollama documentation lists macOS 14 or newer |
| Python | 3.11+ required by `asyncio.timeout`; initial build tested with Python 3.12.4 |
| zsh | Runs the supplied Mac launcher |
| Browser | A current browser supporting native dialogs and fetch |
| Ollama | Required for the demonstrated local path; server at `127.0.0.1:11434` |
| Chat model | A downloaded, chat-capable model compatible with the selected runtime |
| Disk and RAM | Sufficient for the chosen weights, context and runtime; no universal minimum benchmark established |
| Git / GitHub account | Required to version and publish source, not to run an extracted ZIP |

The design brief described an Apple Silicon MacBook with 64 GB memory. That was a design assumption, not a verified minimum specification or performance certification. Start with a modest model and observe memory pressure before trying larger models.

### Optional components

- **LM Studio:** alternative local server at `127.0.0.1:1234`; live compatibility not verified in this build.
- **Cloud API accounts:** needed only for the cloud providers you choose; credentials, model permissions and billing are account-specific.
- **Node.js:** needed only for `node --check`, not for the buildless frontend at runtime.
- **GitHub CLI (`gh`):** simplifies repository creation and authentication. A browser-and-Git alternative is in the publishing guide.
- **Codex:** used to develop this project; not a runtime dependency for the app.

### 1. Install or verify tools

```zsh
python3 --version
git --version
ollama --version
```

If missing, use the official installers: [Python for macOS](https://www.python.org/downloads/macos/), [Ollama for macOS](https://docs.ollama.com/macos), and [GitHub CLI](https://cli.github.com/). Follow installer prompts yourself. Model downloads and package installation require internet access; subsequent local generation uses the local model server.

### 2. Open the repository folder

- Clone your published repository using its actual GitHub URL, or extract the supplied source ZIP.
- Open Terminal in that folder. The root contains `README.md`, `src/` and `scripts/`.
- Do not run setup from inside `src/`; imports use the repository root.

### 3. Create a dedicated Python environment

```zsh
python3 -m venv src/.venv
source src/.venv/bin/activate
python3 -m pip install -r src/requirements.txt
```

| Direct dependency | Recorded version | Purpose |
| --- | --- | --- |
| FastAPI | 0.137.1 | Local API, validation integration and static file serving |
| Uvicorn | 0.49.0 | ASGI application server |
| HTTPX | 0.28.1 | Async provider connections and tests |
| pytest | 9.0.3 | Automated verification |
| PyYAML | 6.0.3 | Safely parse approved Obsidian note properties |

SQLite is included with Python. Pydantic and Starlette arrive through FastAPI. These are pinned direct dependencies, not a hash-locked complete dependency graph. The initial build reused installed packages; a fresh internet-based dependency installation has not been separately certified.

### 4. Start your local model runtime

Open Ollama and check installed models:

```zsh
ollama list
```

If no server is running, use a separate Terminal:

```zsh
ollama serve
```

Choose a chat-capable model you already have. If you need to download one, review its model card, license and memory requirements, then use Ollama's documented download flow. This repository does not automatically download weights. The original demonstration used `gemma4:e4b`; it is an example, not a guaranteed model availability or performance commitment.

### 5. Start My Bulter Enterprise

In the project Terminal, with the environment active:

```zsh
zsh scripts/run.sh
```

Visit [http://127.0.0.1:8765](http://127.0.0.1:8765). Keep this Terminal running. Use Control-C to stop it. On later starts, activate `src/.venv` again before running the launcher.

### 6. Configure your first team

1. Select **Create Bulter**, or use a starter template.
2. Enter its role and instructions, choose Ollama, and select an installed model ID.
3. Decide whether shared memory should be enabled.
4. Create a second Bulter, optionally with another model.
5. Add an explicit note under **Memory**. New notes default to local-only.
6. Open **Missions**, write a brief and select Bulters in execution order.
7. Run the mission and inspect each contribution. Use **Stop mission** to cancel or **Export JSON** to save the record.

Starter templates are UI suggestions, not preinstalled bot records. New clones do not include the author's demo database.

### 7. Optional cloud configuration

| Dashboard provider | Process environment variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Claude | `ANTHROPIC_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |

Supply the chosen variable using your existing secure local environment workflow, then start/restart the app from that environment. Never put actual values in Git, documentation, prompts or memory. The app does not automatically read `.env` files and does not provide a key-entry UI. No credential files are created by these instructions.

Enter an exact provider model ID on the Bulter. Key presence only means a variable exists; it does not validate access. Before a mission with any cloud step, the UI asks for explicit approval to transmit the brief, cloud-approved notes and previous Bulter outputs. All local-only notes are excluded from the entire mixed mission. Verify account billing and limits before use.

### Troubleshooting

| Symptom | Action |
| --- | --- |
| Module not found | Activate the environment, install requirements and run from the repository root |
| Port 8765 in use | Reuse or stop your existing dashboard process; do not kill unrelated processes blindly |
| Ollama port already in use | A server may already be running; inspect Models & connections |
| Provider says Not running | Start the server at the documented local port; current diagnostic also covers invalid discovery responses |
| No chat models shown | Install/load a chat model; embedding/cloud-named models are filtered from discovery |
| Refresh to reconnect | Reload after an app restart; the browser session token rotates |
| Model timeout or memory pressure | Use a smaller model or shorter brief and fewer active notes |
| Context too large | Shorten the task, deactivate notes or use fewer Bulters; context is not silently trimmed by the app |

## Warnings

- No Docker, PostgreSQL, vector database, hosted service or paid subscription is required for the demonstrated local path.
- Never expose either the dashboard or an unauthenticated local model server to the public internet.
- Database backups and exports contain readable text. Stop the app before copying its SQLite database.
