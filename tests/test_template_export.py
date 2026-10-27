"""Tests for clean template export functionality."""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from scripts.export_template import (
    TEMPLATE_FILES,
    TEST_FILES,
    export_template,
    file_sha256,
    get_commit_sha,
    get_repo_root,
    verify_export,
)


def _in_git_checkout() -> bool:
    """Gate sandboxes run tests from a .git-less copy; exporter needs real git."""
    try:
        return (get_repo_root() / ".git").exists()
    except Exception:
        return False


requires_git_checkout = pytest.mark.skipif(
    not _in_git_checkout(), reason="exporter tests need a real git checkout (with .git)"
)


@requires_git_checkout
def test_get_repo_root() -> None:
    """get_repo_root returns the git repository root."""
    root = get_repo_root()
    assert root.exists()
    assert (root / ".git").exists()


@requires_git_checkout
def test_get_commit_sha() -> None:
    """get_commit_sha returns a valid 40-hex SHA."""
    root = get_repo_root()
    sha = get_commit_sha(root)
    assert len(sha) == 40
    assert all(c in "0123456789abcdef" for c in sha)


def test_file_sha256() -> None:
    """file_sha256 computes correct hash."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"test content")
        path = Path(f.name)
    try:
        h = file_sha256(path)
        assert len(h) == 64
        # Verify against known hash
        expected = hashlib.sha256(b"test content").hexdigest()
        assert h == expected
    finally:
        path.unlink()


@requires_git_checkout
def test_template_files_exist() -> None:
    """All TEMPLATE_FILES exist in the repository."""
    root = get_repo_root()
    for rel_path in TEMPLATE_FILES:
        full = root / rel_path
        assert full.exists(), f"Required template file missing: {rel_path}"
        assert full.is_file(), f"Not a file: {rel_path}"


@requires_git_checkout
def test_test_files_exist() -> None:
    """All TEST_FILES exist in the repository."""
    root = get_repo_root()
    for rel_path in TEST_FILES:
        full = root / rel_path
        assert full.exists(), f"Required test file missing: {rel_path}"
        assert full.is_file(), f"Not a file: {rel_path}"


@requires_git_checkout
def test_export_creates_valid_manifest(tmp_path) -> None:
    """Export creates valid manifest with correct hashes."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    # Manifest exists
    manifest_path = export_path / "TEMPLATE-MANIFEST.json"
    assert manifest_path.exists()

    with manifest_path.open() as f:
        manifest = json.load(f)

    assert manifest["commit_sha"] == commit_sha
    assert "exported_at" in manifest
    assert "files" in manifest
    assert len(manifest["files"]) == len(TEMPLATE_FILES) + len(TEST_FILES)

    # Each file in manifest matches actual file
    for file_info in manifest["files"]:
        file_path = export_path / file_info["path"]
        assert file_path.exists(), f"Missing file: {file_info['path']}"
        actual_hash = file_sha256(file_path)
        assert actual_hash == file_info["sha256"], f"Hash mismatch for {file_info['path']}"


@requires_git_checkout
def test_export_excludes_git_and_data(tmp_path) -> None:
    """Export does not include .git, .env, databases, or working directories."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    # These should NOT be in export
    assert not (export_path / ".git").exists()
    assert not (export_path / ".env").exists()
    # .env.example IS created fresh for the export
    assert (export_path / ".env.example").exists()
    assert not (export_path / "data").exists()
    assert not (export_path / "_work").exists()
    assert not (export_path / "__pycache__").exists()
    assert not (export_path / ".pytest_cache").exists()
    assert not (export_path / ".ruff_cache").exists()


@requires_git_checkout
def test_export_includes_env_example(tmp_path) -> None:
    """Export includes a fresh .env.example without credentials."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    env_example = export_path / ".env.example"
    assert env_example.exists()
    content = env_example.read_text()
    assert "BOT_TOKEN=" in content
    assert "ADMIN_IDS=" in content
    # Should not have real values - BOT_TOKEN= should be followed by newline or end
    bot_token_line = [line for line in content.split("\n") if line.startswith("BOT_TOKEN=")][0]
    assert bot_token_line == "BOT_TOKEN="
    admin_ids_line = [line for line in content.split("\n") if line.startswith("ADMIN_IDS=")][0]
    assert admin_ids_line == "ADMIN_IDS="
    assert "BOT_PROFILE_PATH" in content


@requires_git_checkout
def test_verify_export_passes(tmp_path) -> None:
    """verify_export returns True for valid export."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)
    assert verify_export(export_path) is True


@requires_git_checkout
def test_verify_export_fails_on_missing_file(tmp_path) -> None:
    """verify_export fails when a manifest file is missing."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    # Remove a file
    (export_path / "README.md").unlink()

    with pytest.raises(FileNotFoundError, match="Manifest file missing"):
        verify_export(export_path)


@requires_git_checkout
def test_verify_export_fails_on_hash_mismatch(tmp_path) -> None:
    """verify_export fails when file content doesn't match manifest."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    # Modify a file
    readme = export_path / "README.md"
    readme.write_text(readme.read_text() + "\nMODIFIED")

    with pytest.raises(ValueError, match="Hash mismatch"):
        verify_export(export_path)


@requires_git_checkout
def test_export_script_cli(tmp_path) -> None:
    """export_template.py CLI works correctly."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    # Run as module
    result = subprocess.run([
        sys.executable, "-m", "scripts.export_template",
        str(tmp_path), commit_sha
    ], capture_output=True, text=True, cwd=root)

    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert "Exported to:" in result.stdout
    assert "Export verified successfully!" in result.stdout


@requires_git_checkout
def test_export_without_commit_sha_uses_head(tmp_path) -> None:
    """Export without explicit commit SHA uses current HEAD."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    # Run without commit SHA argument
    result = subprocess.run([
        sys.executable, "-m", "scripts.export_template",
        str(tmp_path)
    ], capture_output=True, text=True, cwd=root)

    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert f"Exporting template from commit {commit_sha}" in result.stdout


@requires_git_checkout
def test_manifest_contains_all_required_files(tmp_path) -> None:
    """Manifest contains all files from TEMPLATE_FILES and TEST_FILES."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    manifest_path = export_path / "TEMPLATE-MANIFEST.json"
    with manifest_path.open() as f:
        manifest = json.load(f)

    manifest_paths = {f["path"] for f in manifest["files"]}
    expected_paths = set(TEMPLATE_FILES + TEST_FILES)

    assert manifest_paths == expected_paths, f"Missing or extra files. Diff: {manifest_paths ^ expected_paths}"


@requires_git_checkout
def test_exports_to_new_directory_not_overwriting(tmp_path) -> None:
    """Multiple exports create separate directories, don't overwrite."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path1 = export_template(root, commit_sha, tmp_path)
    # Sleep to ensure different timestamp
    import time
    time.sleep(1.1)
    export_path2 = export_template(root, commit_sha, tmp_path)

    assert export_path1 != export_path2
    assert export_path1.exists()
    assert export_path2.exists()
    assert export_path1.name != export_path2.name


@requires_git_checkout
def test_export_includes_infra_telegram_bot_api(tmp_path) -> None:
    """Export includes infra/telegram-bot-api files."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    assert (export_path / "infra" / "telegram-bot-api" / "README.md").exists()
    assert (export_path / "infra" / "telegram-bot-api" / "docker-compose.yml").exists()
    assert (export_path / "infra" / "telegram-bot-api" / ".env.example").exists()


@requires_git_checkout
def test_export_includes_docs(tmp_path) -> None:
    """Export includes all docs files."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    assert (export_path / "docs" / "UI-CONVENTIONS.md").exists()
    assert (export_path / "docs" / "V2-ACCEPTANCE.md").exists()
    assert (export_path / "docs" / "OPERATIONS.md").exists()
    assert (export_path / "docs" / "GETTING-STARTED.md").exists()


@requires_git_checkout
def test_export_includes_profile_config(tmp_path) -> None:
    """Export includes bot profile example and code."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    assert (export_path / "config" / "bot-profile.example.toml").exists()
    assert (export_path / "bot_template" / "profile.py").exists()


@requires_git_checkout
def test_no_legacy_code_in_export(tmp_path) -> None:
    """Export does not include legacy core/, features/, prompts/ directories."""
    root = get_repo_root()
    commit_sha = get_commit_sha(root)

    export_path = export_template(root, commit_sha, tmp_path)

    assert not (export_path / "core").exists()
    assert not (export_path / "features").exists()
    assert not (export_path / "prompts").exists()
    assert not (export_path / "config.py").exists()  # root config.py is legacy
    assert not (export_path / "prompts").exists()