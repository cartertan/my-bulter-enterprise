"""Create an empty, private Obsidian memory vault without overwriting notes.

Inputs: Bundled setup guide, export prompt and note template.
Outputs: New folders and starter files in the Git-ignored runtime directory.
Assumptions: Run as python3 -m scripts.init_vault from the repository root.
Author: Carter Tan.
"""

import logging

from src.obsidian import DEFAULT_VAULT, FOLDERS


def main() -> None:
    """Create only missing starter files; preserve existing user content."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if DEFAULT_VAULT.is_symlink():
            raise ValueError("Vault must not be a symbolic link.")
        DEFAULT_VAULT.mkdir(parents=True, exist_ok=True, mode=0o700)
        for folder in ("00 Inbox", *FOLDERS, "90 Archive", "99 Templates"):
            path = DEFAULT_VAULT / folder
            if path.is_symlink():
                raise ValueError("Vault subfolders must not be symbolic links.")
            path.mkdir(exist_ok=True, mode=0o700)
        docs = DEFAULT_VAULT.parents[1] / "docs"
        for source, target in (("OBSIDIAN.md", "Start Here.md"),
                               ("MEMORY_EXPORT_PROMPT.md", "00 Inbox/Export Prompt.md"),
                               ("MEMORY_NOTE_TEMPLATE.md", "99 Templates/Memory Note.md")):
            destination = DEFAULT_VAULT / target
            if not destination.exists():
                with destination.open("x", encoding="utf-8") as handle:
                    handle.write((docs / source).read_text(encoding="utf-8"))
                destination.chmod(0o600)
        logging.info("Vault ready: %s", DEFAULT_VAULT)
    except (OSError, ValueError) as exc:
        logging.error("Vault setup stopped: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
