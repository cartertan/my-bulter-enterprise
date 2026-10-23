## My Bulter Memory — Obsidian integration

### What is implemented

- A dedicated vault under `src/.runtime/My Bulter Memory`, excluded from Git and source ZIPs.
- Read-only ingestion of approved Markdown notes into the existing Bulter memory store.
- A **Sync approved notes** button on the dashboard's **Memory** page.
- Revalidation before every mission; withdrawn, archived or removed approved notes are deactivated for subsequent missions.
- Stable note IDs, relative source paths, source labels and SHA-256 revision hashes on imported records.
- Existing private/shared and cloud-approval policy remains enforced.

Obsidian is the authoring source for imported notes. The application never writes back to the vault, and its UI/API prevents editing imported records independently. Existing manually entered dashboard notes remain separate; they are not migrated or deleted automatically.

### Create and open the vault

From the repository root, after installing updated requirements:

```zsh
python3 -m pip install -r src/requirements.txt
python3 -m scripts.init_vault
```

Open Obsidian, choose **Open folder as vault**, and select `src/.runtime/My Bulter Memory` within your project. It may be easier to paste the full path shown on the dashboard's Memory page into the macOS folder picker with Command-Shift-G. Runtime folders beginning with a dot are normally hidden in Finder.

No community plugin, Obsidian Sync subscription or REST API service is required. Obsidian stores Markdown locally and notices external file changes. [Official storage documentation](https://obsidian.md/help/data-storage)

### Vault organization

| Folder | Purpose | Used by Bulters? |
| --- | --- | --- |
| `00 Inbox` | Separate ChatGPT and Claude inventories and raw exports | Never |
| `10 Profile` | Stable professional context | Approved notes only |
| `20 Preferences` | Communication, evidence and formatting preferences | Approved notes only |
| `30 Workflows` | Reusable ways of working | Approved notes only |
| `40 Projects` | Project-specific context and boundaries | Approved notes only; use private scope where appropriate |
| `50 Shared Knowledge` | Reviewed cross-Bulter knowledge | Approved notes only |
| `60 Bulters` | Notes owned by particular Bulters | Approved notes only |
| `90 Archive` | Retired or superseded material | Never |
| `99 Templates` | Blank note template | Never |

Folder names organize notes; they do not grant permissions. A note in Projects is still shared if its scope says shared. Access is controlled by its properties and the Bulter's shared-memory setting.

### Export ChatGPT and Claude context

1. Use `Export Prompt.md` in the inbox (or the published `MEMORY_EXPORT_PROMPT.md`) in each platform separately.
2. Save each response separately, for example `ChatGPT inventory 2026-10-23.md` and `Claude inventory 2026-10-23.md`, in `00 Inbox`.
3. Review the platforms' memory controls too. ChatGPT memory is managed under Settings → Personalization; local Codex memories are a separate store. [Official memory documentation](https://learn.chatgpt.com/docs/customization/memories)
4. Claude documents memory review/export through its memory controls or a chat request; its current UI has new and legacy settings layouts. Follow the instructions matching your account. [Claude memory export](https://support.claude.com/en/articles/12123587-import-and-export-your-memory-from-claude)
5. If you need a deeper historical audit, obtain account exports separately. Claude's documented route is Settings → Privacy → Export data, subject to account/workspace permissions. [Claude data export](https://support.claude.com/en/articles/9450526-export-your-claude-data)

The app does not log into either platform or automatically extract their memory. API provider credentials do not connect this integration to the consumer accounts' stored memories. Full-history ZIP parsing is not implemented in this iteration; raw exports remain review material in the excluded inbox.

### Review and promote notes

1. Compare the two inventories, keeping their sources separate.
2. Identify stable preferences versus one-off tasks, inference and stale information.
3. Resolve conflicts explicitly. A newer statement supersedes an older one only when its meaning and scope justify that decision.
4. Copy the template from `99 Templates` to a managed folder. Give each note a unique stable `id` and descriptive title.
5. Keep `status: draft` until reviewed. Then change it to `approved`.
6. Use `scope: shared` for opted-in Bulters, or `scope: private` with the existing owner's Bulter ID. Obtain the ID from a mission JSON export's team record; a friendly owner selector in Obsidian is not yet provided.
7. Keep `cloud_allowed: false` unless this specific note is suitable for paid-provider missions.
8. Click **Sync approved notes**. The dashboard shows imported notes and their source paths. Edit those notes in Obsidian, not the dashboard.

Obsidian properties are YAML fields at the start of a note. The template works with the built-in Properties editor; use actual booleans for cloud permission. [Obsidian properties](https://obsidian.md/help/properties)

### Runtime behaviour

- Approved note bodies are limited to 3,000 characters; titles to 100. The import checks at most 500 Markdown files, each at most 16 KB, across the six managed folders.
- Missing/invalid properties, duplicate approved IDs, symlinks or invalid private owners stop the sync. No partial snapshot is committed on validation failure.
- Before each mission, the vault is checked again. A validation failure blocks a new mission rather than silently using stale approvals.
- Changing status to draft/archived, moving a note out of managed folders, or removing it deactivates its imported memory record on sync. The app never deletes the file.
- A running mission uses its existing memory snapshot. Later edits do not retroactively change its outputs or context.
- Scope and cloud policy are applied before retrieval. Local keyword ranking selects complete notes within the 24,000-character context bound, accounting for the task and prior Bulter outputs. Response-preference notes receive a small baseline priority. The mission records selected IDs and eligible counts; the dashboard shows the counts.
- This is lexical retrieval, not semantic search or exhaustive evidence review. Name the customer, project or topic in the task. Synonyms and related qualifications may be missed. No new dependencies or embedding services are required.
- Sources and hashes identify revisions but do not retain all prior note versions. Use your own private backups if historical restoration is required.

### Dependency and testing

PyYAML 6.0.3 is the one added direct dependency. It reads Obsidian YAML properties using `safe_load`; no custom YAML constructors are executed. The package was already present on the development Mac. Existing requirements are otherwise unchanged.

Tests exercise approval, private owners, cloud flags, inbox exclusion, duplicate IDs, revocation, missing vaults, malformed data, symlinks and atomic import. The application still does not perform autonomous writes or cloud extraction.

## Warnings

- Keep this vault private and excluded from public GitHub repositories. A private vault can still sync externally if you separately configure a sync service or plugin.
- Do not approve raw chat archives as memories. Exported text is untrusted reference material until reviewed.
- Shared/private retrieval and local/cloud permissions are separate controls. A model may restate a private note in its handoff output; only reviewed notes should be made available.
- This import does not synchronize ChatGPT's or Claude's own memory stores. It supplies approved Obsidian context to Bulters within this application.
