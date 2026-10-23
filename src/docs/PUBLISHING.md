## Publish My Bulter Enterprise to GitHub

### What is prepared

- Source, tests and portable documentation in this repository.
- Root ignore rules for credentials, local databases, virtual environments and generated archives.
- A source-only ZIP builder with an explicit allowlist, common credential-pattern checks and SHA-256 manifest.
- No commit, GitHub repository creation or push is performed by the packaging command.

### Before the first commit

Open Terminal in the repository root. Activate your Python environment if using one, then run:

```zsh
python3 -m pytest src/tests -q -p no:cacheprovider
node --check src/static/app.js
python3 scripts/package_release.py --check
git status --short
git remote -v
```

Stop if tests/checks fail. The original workspace already has an empty Git repository on `main` and no remote. If working from an extracted ZIP, initialize Git first:

```zsh
git init -b main
```

Inspect existing remotes before adding one; do not replace a remote or force-push over existing history. The commands below are for a new repository, not a repository with unrelated contents.

### Stage and review

```zsh
git add README.md .gitignore scripts src
git diff --cached --check
git diff --cached --stat
git diff --cached
```

Review the entire staged diff. Confirm that only source and documentation are staged. Specifically, no `.runtime`, `.release`, `.venv`, `.env`, SQLite databases, keys, logs or personal screenshots should appear.

The packager checks Git's tracked/unignored candidate list as well as its own allowlist. Ignore rules do not remove previously tracked files from history. If you have already committed sensitive files, stop and resolve that separately before publishing; do not rely on a new `.gitignore` alone.

Commit the reviewed snapshot:

```zsh
git commit -m "feat: add My Bulter Enterprise local AI team dashboard"
```

If Git requests your author identity, configure the name/email you intend to make part of commit history, then retry. This guide does not set your identity automatically.

### Create a new repository using GitHub CLI

Install [GitHub CLI](https://cli.github.com/) if missing. Authenticate in your own browser and confirm the destination account:

```zsh
gh auth login --hostname github.com --git-protocol https --web
gh auth status
```

For a **public** repository, run the following only after reviewing the staged/committed content and deciding that the source should be publicly visible:

```zsh
gh repo create my-bulter-enterprise \
  --public \
  --source=. \
  --remote=origin \
  --description "Local-first AI team dashboard with per-bot model selection, scoped memory and sequential collaboration" \
  --push
```

For a private repository, replace `--public` with `--private`. Do not run both creation commands. The bare repository name uses your authenticated personal account; to target an organization, replace it with `YOUR_ORG/my-bulter-enterprise` and verify you have access.

The command creates the repository, adds `origin` and pushes the current branch. It publishes source code, not a running web application. GitHub Pages cannot run the Python/Ollama backend.

Verify the result:

```zsh
git status --short
git remote -v
gh repo view --web
```

Reference: [official `gh repo create` documentation](https://cli.github.com/manual/gh_repo_create), [official authentication documentation](https://cli.github.com/manual/gh_auth_login).

### Browser-and-Git alternative

1. In GitHub, create an empty repository named `my-bulter-enterprise` under the intended account.
2. Choose public or private. Do not initialize another README, `.gitignore` or license in that new repository; the local repository supplies its files.
3. After the local commit above, use the actual repository URL in place of the example below:

```zsh
git remote add origin https://github.com/YOUR_USERNAME/my-bulter-enterprise.git
git push -u origin main
```

If `origin` already exists, inspect its URL instead of running `remote add` again. Do not include a token in the URL.

### Build a downloadable source ZIP

```zsh
python3 scripts/package_release.py --check
python3 scripts/package_release.py
```

The second command creates a timestamped ZIP under `src/.release/`. It contains the reviewed source files plus `SOURCE_MANIFEST.json`, which records file sizes and SHA-256 hashes. The directory and ZIP are ignored by Git. Every filename in the ZIP is under `my-bulter-enterprise/`.

The manifest supports integrity inspection; it is not a cryptographic signature or an independent security attestation. The archive includes the packaging tool but no Git metadata, runtime data, screenshots, environments or model weights.

To rebuild later, rerun the command; it refuses to overwrite an existing archive name. New source files must be explicitly added to the allowlist before packaging. You may attach the resulting ZIP to a GitHub Release after reviewing the repository and choosing a release tag.

### Future changes

Use a new branch for substantive work. After tests and the source review pass, commit only the intended files and push that branch. Review changes before merging into `main`. Do not use force-push or broad history rewriting as a routine update procedure.

### License decision

No license has been selected for this initial package. Public repository visibility and licensing are separate choices. Choose and add the license you intend before calling the project an open-source release; do not assume the source's visibility is a substitute for that decision.

## Warnings

- `--public` makes the committed source available to others. Review before running that command.
- The automated pattern scan is a limited accidental-disclosure check. It cannot establish absence of all secrets or confidential material.
- Do not publish local mission records, customer documents, API keys or screenshots showing private data.
