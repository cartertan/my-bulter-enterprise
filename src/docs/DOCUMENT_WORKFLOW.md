## Document memory and editable exports

### Use document memory

1. Open **Memory → Upload document**.
2. Choose TXT, Markdown, text PDF, DOCX or PPTX, up to 10 MB.
3. Choose **Extract for review** and read every part.
4. Choose **Approve all parts as local shared memory**.
5. Enable shared memory on the Bulters that should retrieve this information.

Extraction runs locally in a child process with a 30-second wall timeout and a CPU limit. Draft text is persisted in private SQLite storage, with filename and source SHA-256. Original binaries are not retained. Approval writes bounded Markdown notes under `50 Shared Knowledge` in the configured Obsidian vault. Import is deduplicated by source bytes. Uploaded text is reference material, not authority to execute instructions. Retrieval is keyword-based and selects matching notes; it does not train a model or insert the entire vault into every prompt.

Imported notes are shared and local-only. Edit or revoke them in Obsidian and sync. Upload approval status is an import receipt; it does not override later Obsidian revocation. Documents are limited to 120,000 extracted characters, PDFs to 200 pages, decompressed Office content to 40 MB, and the managed vault to 500 notes. Headers, footers, images, charts, slide speaker notes, and scanned images are not extracted. PDF reading order and table fidelity require review. Password-protected or malformed documents may be rejected. TXT and Markdown require UTF-8.

### Download results

Complete a mission, open its workspace, then choose **Download Word** or **Download PowerPoint**. Downloads contain the final Bulter response only, with model/date provenance. Word includes the original request. PowerPoint keeps it in speaker notes. The application preserves response wording; it does not invent graphics, rewrite findings or apply a corporate template. Basic Markdown headings become Word headings; other Markdown remains visible text. JSON export retains the full mission audit.

The PPTX uses a warm dark theme, editable text and bounded continuation slides. This is a text-based presentation export, not an automatic presentation designer. Review generated claims and layout before sharing.

### Current local model choices

Verified against the official Ollama catalog on 26 October 2026:

| Role | Model | Approximate download |
| --- | --- | --- |
| Main technical and writing model | `qwen3.8:27b` | 18 GB |
| Optional document reviewer | `granite4.2:30b` | 18 GB |
| Lightweight fallback | Existing `gemma4:e4b` | Already installed on this workstation |

Sources: [Qwen3.8](https://ollama.com/library/qwen3.8), [Granite4.2](https://ollama.com/library/granite4.2).

Install explicitly, then use **Models & connections → Check connections** and edit each Bulter's model ID:

```zsh
ollama pull qwen3.8:27b
# Optional second model
ollama pull granite4.2:30b
```

Use explicit tags instead of `latest` for predictable model family and size. Model downloads do not change existing assignments. New Bulters offer a 4,096-token output budget and 16,384-token context; existing saved settings are preserved. Local inference settings apply to Ollama only. Start with thinking off for direct writing; use on only with a supporting reasoning model. The app still bounds retrieved context to 24,000 characters, individual output to 16,000 characters and mission duration to 10 minutes. Larger provider settings do not remove these application limits.

### Dependencies and verification

Added pinned runtime dependencies: `python-docx`, `python-pptx`, `pdfplumber`. Install all app dependencies before restarting:

```zsh
python3 -m pip install -r src/requirements.txt
python3 -m pytest -q -p no:cacheprovider src/tests
node --check src/static/app.js
python3 scripts/package_release.py --check
zsh scripts/run.sh
```

Stop the currently running server with Control-C before restarting. This change does not publish anything to GitHub.

### Validation on 26 October 2026

- 60 automated tests passed, including Office worker extraction, upload size and filename limits, approval, duplicate imports, revocation, local-only egress, symlink rejection, editable exports and inference settings.
- JavaScript syntax, whitespace and the 39-file release allowlist checks passed.
- Synthetic Word and PowerPoint exports were rendered and visually inspected.
- A real local Gemma mission retrieved one synthetic Obsidian note, completed, and returned both export formats through HTTP.
- Browser approval flow passed. Browser download-event automation timed out; direct HTTP downloads passed.
- One existing Starlette TestClient deprecation warning remains.

## Warnings

- Local storage is not encrypted by this application. Keep vaults, uploads and mission outputs out of public repositories.
- Uploads are untrusted. No parser can guarantee faithful interpretation of every document; review extracted text before approval.
- Downloads can contain confidential information and model errors. Review before distributing.
- macOS does not provide a reliable address-space limit here; extraction uses input/decompression limits, CPU limits and a subprocess timeout instead.
