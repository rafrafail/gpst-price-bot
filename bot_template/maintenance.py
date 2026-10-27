"""Maintenance utilities: verified SQLite backup and safe restore."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def backup_database(source_path: Path, backup_dir: Path) -> Path:
    """
    Create a verified SQLite backup using the backup API.
    
    Args:
        source_path: Path to the source database file
        backup_dir: Directory to store the backup (created with 0700)
        
    Returns:
        Path to the backup file (0600)
        
    Raises:
        ValueError: If source doesn't exist, backup_dir is same as source, or DB is locked
    """
    source_path = Path(source_path).resolve()
    backup_dir = Path(backup_dir).resolve()
    
    if not source_path.exists():
        raise ValueError(f"Source database not found: {source_path}")
    
    if source_path.parent == backup_dir or source_path == backup_dir:
        raise ValueError("Backup directory cannot be the same as source")
    
    # Check for symlinks
    if source_path.is_symlink() or any(p.is_symlink() for p in backup_dir.parents):
        raise ValueError("Symlinks not allowed in backup path")
    
    # Create backup directory with restricted permissions
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    
    # Generate backup filename with timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_name = f"backup-{source_path.stem}-{timestamp}.sqlite3"
    backup_path = backup_dir / backup_name
    
    # Check if database is accessible (not locked by another process)
    try:
        test_conn = sqlite3.connect(str(source_path), timeout=1.0)
        test_conn.execute("PRAGMA busy_timeout = 1000")
        test_conn.execute("SELECT 1")
        test_conn.close()
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower() or "busy" in str(e).lower():
            raise ValueError(f"Database is locked by another process: {e}")
        raise
    
    # Use SQLite backup API - this correctly handles WAL mode
    src_conn = sqlite3.connect(str(source_path))
    try:
        src_conn.execute("PRAGMA busy_timeout = 5000")
        dst_conn = sqlite3.connect(str(backup_path))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    
    # Verify backup integrity (checks must actually pass, not just run)
    verify_conn = sqlite3.connect(str(backup_path))
    try:
        integrity = verify_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Backup integrity check failed: {integrity}")
        fk_violations = verify_conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            raise ValueError(f"Backup foreign key check failed: {len(fk_violations)} violations")
        # Verify schema version
        version = verify_conn.execute("PRAGMA user_version").fetchone()[0]
        if version != 1:
            raise ValueError(f"Backup has unexpected schema version: {version}")
    finally:
        verify_conn.close()
    
    # Set restrictive permissions
    backup_path.chmod(0o600)
    
    return backup_path


def restore_database(backup_path: Path, target_path: Path) -> None:
    """
    Restore database from backup to a NEW target path.
    
    Args:
        backup_path: Path to the backup file
        target_path: NEW database path (must not exist)
        
    Raises:
        ValueError: If backup invalid, target exists, or schema mismatch
    """
    backup_path = Path(backup_path).resolve()
    target_path = Path(target_path).resolve()
    
    if not backup_path.exists():
        raise ValueError(f"Backup file not found: {backup_path}")
    
    if target_path.exists():
        raise ValueError(f"Target path already exists: {target_path}")
    
    # Check for symlinks
    if backup_path.is_symlink() or target_path.is_symlink():
        raise ValueError("Symlinks not allowed")
    
    # Verify backup first (results must actually pass)
    verify_conn = sqlite3.connect(str(backup_path))
    try:
        integrity = verify_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"Backup integrity check failed: {integrity}")
        fk_violations = verify_conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            raise ValueError(f"Backup foreign key check failed: {len(fk_violations)} violations")
        version = verify_conn.execute("PRAGMA user_version").fetchone()[0]
        if version != 1:
            raise ValueError(f"Backup has unsupported schema version: {version}")
    finally:
        verify_conn.close()
    
    # Copy backup to target (atomic-ish via temp file)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(".tmp")
    try:
        shutil.copy2(backup_path, temp_path)
        temp_path.chmod(0o600)
        
        # Verify the copy (results must actually pass)
        verify_conn = sqlite3.connect(str(temp_path))
        try:
            integrity = verify_conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ValueError(f"Restored copy integrity check failed: {integrity}")
            fk_violations = verify_conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_violations:
                raise ValueError(f"Restored copy foreign key check failed: {len(fk_violations)} violations")
        finally:
            verify_conn.close()
        
        # Atomic rename
        temp_path.replace(target_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise


def prepare_restored_for_resume(restored_path: Path) -> dict:
    """
    Prepare a restored database for safe resume.
    
    Translates potentially-repeatable delivery states to safe states:
    - pending/sending/failed -> unknown
    - scheduled/running/paused -> attention (campaign level)
    - completed/sent -> unchanged
    
    Also clears UI states, confirmations, and navigation bindings.
    Preserves drafts, content, and notes.
    
    Returns:
        Dict with counts of changes made
    """
    conn = sqlite3.connect(str(restored_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        changes = {
            "deliveries_to_unknown": 0,
            "campaigns_to_attention": 0,
            "ui_states_cleared": 0,
            "confirmations_cleared": 0,
            "subscriptions_reset": 0,
        }

        # Potentially repeatable deliveries may exist in ANY campaign state:
        # a partial/failed campaign restored from an older snapshot can still
        # contain 'failed' rows that control_campaign(retry) would re-send.
        result = conn.execute("""
            UPDATE deliveries
            SET status = 'unknown', claim_token = NULL, retry_at = NULL,
                error = 'restored from backup; outcome unknown'
            WHERE status IN ('pending', 'sending', 'failed')
        """)
        changes["deliveries_to_unknown"] = result.rowcount

        # Campaigns that were mid-flight at snapshot time must not auto-resume.
        cursor = conn.execute("""
            SELECT id FROM campaigns
            WHERE status IN ('running', 'scheduled', 'paused')
        """)
        campaign_ids = [row[0] for row in cursor.fetchall()]
        for camp_id in campaign_ids:
            conn.execute("""
                UPDATE campaigns SET status = 'attention', revision = revision + 1
                WHERE id = ?
            """, (camp_id,))
            changes["campaigns_to_attention"] += 1

        # Unsubscriptions after the backup cannot be recovered from the snapshot.
        # Conservative plan (D3): restore everyone with broadcasts OFF; users opt in.
        result = conn.execute("UPDATE users SET subscribed = 0 WHERE subscribed = 1")
        changes["subscriptions_reset"] = result.rowcount
        
        # Clear UI states (panel_id, input, confirmation, history)
        result = conn.execute("""
            UPDATE ui_state SET data = json_set(
                COALESCE(data, '{}'),
                '$.panel_id', NULL,
                '$.input', NULL,
                '$.confirmation', NULL,
                '$.history', json('[]')
            )
        """)
        changes["ui_states_cleared"] = result.rowcount
        
        # Clear media_groups to prevent conflicts
        conn.execute("DELETE FROM media_groups")
        
        conn.commit()
        return changes
        
    finally:
        conn.close()


def verify_backup(backup_path: Path) -> dict:
    """
    Verify a backup file and return metadata.
    
    Returns:
        Dict with: valid (bool), version, tables, counts, error (if any)
    """
    result = {"valid": False}
    try:
        conn = sqlite3.connect(str(backup_path))
        try:
            conn.execute("PRAGMA integrity_check")
            conn.execute("PRAGMA foreign_key_check")
            result["version"] = conn.execute("PRAGMA user_version").fetchone()[0]
            
            # Count records
            tables = ["users", "campaigns", "deliveries", "ui_state", "media_groups"]
            for table in tables:
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    result[f"{table}_count"] = count
                except sqlite3.OperationalError:
                    result[f"{table}_count"] = 0
            
            # Check campaign statuses
            statuses = conn.execute("""
                SELECT status, COUNT(*) FROM campaigns GROUP BY status
            """).fetchall()
            result["campaign_statuses"] = dict(statuses)
            
            # Check delivery statuses
            d_statuses = conn.execute("""
                SELECT status, COUNT(*) FROM deliveries GROUP BY status
            """).fetchall()
            result["delivery_statuses"] = dict(d_statuses)
            
            result["valid"] = True
        finally:
            conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result