"""Source packaging boundary tests.

Inputs: Synthetic source trees and fake credential patterns.
Outputs: Assertions about exclusions, path safety and archive hashes.
Assumptions: No real credentials, Git changes or network calls. Author: Carter Tan.
"""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.package_release import FILES, collect, create_archive, validate_candidates, validate_text


def test_candidate_exclusion() -> None:
    """Tracked runtime data cannot silently pass the source-only review."""
    validate_candidates(list(FILES))
    with pytest.raises(ValueError, match="outside the reviewed allowlist"):
        validate_candidates([*FILES, "src/.runtime/bulter.sqlite3"])


@pytest.mark.parametrize("text", ["sk-" + "A" * 30, "ghp_" + "B" * 30,
                                 "-----BEGIN " + "PRIVATE KEY-----", "/Users/" + "example/private.txt"])
def test_sensitive_pattern_detection(text: str) -> None:
    """Common leaked credentials/paths are rejected without echoing their contents."""
    with pytest.raises(ValueError) as result:
        validate_text("sample.txt", text.encode())
    assert text not in str(result.value)


def test_allowlist_excludes_runtime_and_verifies_manifest(tmp_path: Path) -> None:
    """Only enumerated source files enter the ZIP; manifest matches exact bytes."""
    for name in FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Synthetic source\n")
    private = tmp_path / "src" / ".runtime"
    private.mkdir()
    (private / "private.txt").write_text("not for publication")
    payload = collect(tmp_path)
    archive = create_archive(tmp_path, payload)
    with zipfile.ZipFile(archive) as bundle:
        assert len(bundle.namelist()) == len(FILES) + 1
        assert all(".runtime" not in n for n in bundle.namelist())
        manifest = json.loads(bundle.read("my-bulter-enterprise/SOURCE_MANIFEST.json"))
        for name, item in manifest["files"].items():
            content = bundle.read("my-bulter-enterprise/" + name)
            assert hashlib.sha256(content).hexdigest() == item["sha256"]
            assert len(content) == item["bytes"]


def test_symlink_rejected(tmp_path: Path) -> None:
    """Source symlinks cannot import files from outside the reviewed paths."""
    destination = tmp_path / "other.txt"
    destination.write_text("synthetic")
    (tmp_path / FILES[0]).symlink_to(destination)
    with pytest.raises(ValueError, match="Symlink"):
        collect(tmp_path)
