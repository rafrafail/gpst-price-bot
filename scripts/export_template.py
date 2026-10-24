"""Export a clean starter kit from an exact Git commit."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

TEMPLATE_FILES = [
    "main.py",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "README.md",
    "AGENTS.md",
    "config/template-v2.example",
    "config/bot-profile.example.toml",
    "docs/UI-CONVENTIONS.md",
    "docs/V2-ACCEPTANCE.md",
    "docs/OPERATIONS.md",
    "docs/GETTING-STARTED.md",
    "bot_template/__init__.py",
    "bot_template/config.py",
    "bot_template/models.py",
    "bot_template/storage.py",
    "bot_template/storage_contract.md",
    "bot_template/navigation.py",
    "bot_template/app.py",
    "bot_template/content.py",
    "bot_template/delivery.py",
    "bot_template/runtime.py",
    "bot_template/profile.py",
    "bot_template/scheduling.py",
    "infra/telegram-bot-api/README.md",
    "infra/telegram-bot-api/docker-compose.yml",
    "infra/telegram-bot-api/.env.example",
    "scripts/__init__.py",
    "scripts/export_template.py",
]


# Files that should exist in tests/
TEST_FILES = [
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/helpers.py",
    "tests/test_app.py",
    "tests/test_config.py",
    "tests/test_content.py",
    "tests/test_delivery.py",
    "tests/test_integrated_delivery.py",
    "tests/test_regressions.py",
    "tests/test_runtime.py",
    "tests/test_storage.py",
    "tests/test_profile.py",
    "tests/test_profile_journey.py",
    "tests/test_template_export.py",
]


@dataclass
class FileEntry:
    path: str
    sha256: str
    size: int


@dataclass
class Manifest:
    commit_sha: str
    exported_at: str
    files: list[FileEntry] = field(default_factory=list)


def run_cmd(cmd: list[str], cwd: Path | None = None) -> str:
    """Run command and return stdout."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def get_commit_sha(repo_root: Path) -> str:
    """Get full 40-hex commit SHA."""
    return run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_root)


def get_repo_root() -> Path:
    """Find git repository root."""
    return Path(run_cmd(["git", "rev-parse", "--show-toplevel"]))


def file_sha256(path: Path) -> str:
    """Compute SHA256 of file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def read_file_content(path: Path) -> str:
    """Read file content."""
    return path.read_text(encoding="utf-8")


def write_file_content(path: Path, content: str) -> None:
    """Write file content, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def collect_files(repo_root: Path, commit_sha: str) -> list[FileEntry]:
    """Collect files at exact commit, returning list with hashes."""
    entries = []

    # Core template files
    for rel_path in TEMPLATE_FILES:
        full = repo_root / rel_path
        if not full.exists():
            raise FileNotFoundError(f"Required template file missing: {rel_path}")
        if full.is_file():
            entries.append(FileEntry(
                path=rel_path,
                sha256=file_sha256(full),
                size=full.stat().st_size,
            ))

    # Test files
    for rel_path in TEST_FILES:
        full = repo_root / rel_path
        if not full.exists():
            raise FileNotFoundError(f"Required test file missing: {rel_path}")
        if full.is_file():
            entries.append(FileEntry(
                path=rel_path,
                sha256=file_sha256(full),
                size=full.stat().st_size,
            ))

    return entries


def verify_whitelist(entries: list[FileEntry]) -> None:
    """Verify no unexpected files in the list (for future-proofing)."""
    known_paths = {f.path for f in entries}
    expected_paths = set(TEMPLATE_FILES + TEST_FILES)
    # All entries must be in expected
    unexpected = known_paths - expected_paths
    if unexpected:
        raise ValueError(f"Unexpected files in export (not in whitelist): {sorted(unexpected)}")


def export_template(
    repo_root: Path,
    commit_sha: str,
    output_dir: Path,
) -> Path:
    """Export clean template from exact commit SHA."""
    # Create timestamped export directory
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    export_path = output_dir / f"tg-bot-template-{commit_sha[:8]}-{timestamp}"
    export_path.mkdir(parents=True, exist_ok=False)

    # Collect files at exact commit
    entries = collect_files(repo_root, commit_sha)
    verify_whitelist(entries)

    # Copy files to export directory
    for entry in entries:
        src = repo_root / entry.path
        dst = export_path / entry.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    # Create manifest
    from datetime import datetime, timezone
    manifest = Manifest(
        commit_sha=commit_sha,
        exported_at=datetime.now(timezone.utc).isoformat(),
        files=entries,
    )
    manifest_path = export_path / "TEMPLATE-MANIFEST.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump({
            "commit_sha": manifest.commit_sha,
            "exported_at": manifest.exported_at,
            "files": [
                {"path": e.path, "sha256": e.sha256, "size": e.size}
                for e in manifest.files
            ],
        }, f, ensure_ascii=False, indent=2)

    # Create safe .env.example for the export
    env_example = export_path / ".env.example"
    write_file_content(env_example, """# Example only. Create your private .env manually; never commit real secrets.
BOT_TOKEN=
ADMIN_IDS=
BOT_TITLE=Мой бот
BOT_TIMEZONE=Europe/Moscow
DATABASE_PATH=data/template-v2.sqlite3
BROADCAST_ENABLED=1
BOT_MODE=polling

# Public bot profile (optional). Point to a TOML file with title, welcome, help,
# support URL, menu order, sections, and example section toggle.
# BOT_PROFILE_PATH=config/bot-profile.toml

# Telegram Bot API transport. Default cloud mode needs no api_id/api_hash.
TELEGRAM_TRANSPORT=cloud
# For the optional self-hosted mode only:
# TELEGRAM_TRANSPORT=self_hosted
# LOCAL_BOT_API_URL=http://127.0.0.1:8081

# Webhook only, behind your HTTPS reverse proxy:
# WEBHOOK_URL=https://your-domain.example/telegram
# WEBHOOK_SECRET=replace-with-a-random-secret
# WEBHOOK_HOST=127.0.0.1
# WEBHOOK_PORT=8080
""")

    return export_path


def verify_export(export_path: Path) -> bool:
    """Verify exported template against manifest."""
    manifest_path = export_path / "TEMPLATE-MANIFEST.json"
    if not manifest_path.exists():
        raise FileNotFoundError("TEMPLATE-MANIFEST.json not found in export")

    with manifest_path.open(encoding="utf-8") as f:
        manifest = json.load(f)

    for file_info in manifest["files"]:
        file_path = export_path / file_info["path"]
        if not file_path.exists():
            raise FileNotFoundError(f"Manifest file missing in export: {file_info['path']}")
        actual_hash = file_sha256(file_path)
        if actual_hash != file_info["sha256"]:
            raise ValueError(f"Hash mismatch for {file_info['path']}: expected {file_info['sha256']}, got {actual_hash}")

    return True


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: export_template.py <output_dir> [commit_sha]")
        print("  If commit_sha not provided, uses current HEAD")
        return 1

    output_dir = Path(sys.argv[1])
    commit_sha = sys.argv[2] if len(sys.argv) > 2 else None

    repo_root = get_repo_root()

    if commit_sha is None:
        commit_sha = get_commit_sha(repo_root)
    else:
        # Verify the commit exists
        run_cmd(["git", "cat-file", "-t", commit_sha], cwd=repo_root)

    print(f"Exporting template from commit {commit_sha}")
    print(f"Repository: {repo_root}")
    print(f"Output directory: {output_dir}")

    try:
        export_path = export_template(repo_root, commit_sha, output_dir)
        print(f"Exported to: {export_path}")
        print("Verifying export...")
        verify_export(export_path)
        print("Export verified successfully!")
        return 0
    except Exception as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())