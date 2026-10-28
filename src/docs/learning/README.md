## Learning Lab: Building My Bulter Enterprise with Codex

A practical guide to taking a personal AI application from an idea to a tested, reviewable release using Codex and GitHub.

**Audience:** Product owners and individual builders who want to direct AI-assisted development without managing every line of code.

**Naming:** The repository and application use **My Bulter Enterprise** and **Bulters**. This guide retains that spelling. “Enterprise” is the product name, not a claim of enterprise readiness.

### Start here

| Read | Purpose | Output for your own project |
| --- | --- | --- |
| [End-to-end case study](BUTLER_CASE_STUDY.md) | Product discovery, prioritization, architecture, delivery, validation and lessons | A small, evidence-based product development process |
| [Reusable work templates](WORKFLOW_TEMPLATES.md) | Copyable brief, issue, Codex prompt, review and handover templates | Your next clearly scoped development task |
| [Application guide](../../README.md) | Operate the actual implementation | A running local dashboard |
| [Architecture](../ARCHITECTURE.md) | Understand implementation boundaries | A map of components and data flow |
| [Mission attachments](../MISSION_ATTACHMENTS.md) | Study one complete feature increment | Inputs, behaviour, tests and limitations |

### How to use this learning section

1. Read the case study before asking Codex to build a new application.
2. Fill in the product brief template with your own requirements and synthetic examples.
3. Create a small backlog in GitHub Issues. Use one coherent outcome per issue.
4. Start a focused Codex chat for each implementation issue, pointing to the repository and specification.
5. Review evidence, merge deliberately, and save a short handover before the next task.

The case study separates **observed project history**, **current evidence** and **recommended practice**. It does not claim the original build followed a formal product process from the beginning.

### Publish this subsection

These are ordinary Markdown files. Once committed and pushed, GitHub displays this folder's README as the learning-section landing page. No website hosting or additional project-management software is required.

From the repository root, a documentation-only branch can be prepared with:

```zsh
git status --short
git switch -c codex/learning-case-study
git add src/docs/learning/README.md src/docs/learning/BUTLER_CASE_STUDY.md src/docs/learning/WORKFLOW_TEMPLATES.md
git diff --cached --check
git diff --cached --stat
git diff --cached
# Confirm that the staged changes contain only the three intended learning files.
git commit -m "docs: add Butler product development learning case study"
git push -u origin codex/learning-case-study
```

Open a pull request on GitHub, review the rendered Markdown and merge when ready. If that branch already exists, switch to it rather than attempting to create it again. If unrelated changes are already staged, isolate them before committing; the commands above do not unstage anything automatically.

The project documentation link and source-package allowlist are also updated locally. They share files with the pending attachment feature, so review those changes separately or include them in the combined feature release. Do not stage every working-tree change merely to publish this learning section. The three Markdown files can also be uploaded together using GitHub's file-upload interface under `src/docs/learning/`.

### Evidence date

Prepared on **28 October 2026** from the repository documentation, implementation and development verification records. This is a learning checkpoint, not a continuously updated feature-status dashboard.

## Warnings

- Do not publish personal memory exports, credentials, runtime databases or private screenshots as learning examples.
- A prepared file or source ZIP is not proof that a commit, push, merge or GitHub release occurred.
- Adapt the workflow to task risk; avoid turning a small change into unnecessary paperwork.
