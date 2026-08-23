import sqlite3
from enum import IntEnum
from pathlib import Path
from typing import Any
import uuid

class DocState(IntEnum):
    PLANNED = 0
    PARSED = 1
    ANALYZED = 2
    GRAPH_WRITTEN = 3
    COPIED = 4
    VERIFIED = 5
    ARTIFACTS_WRITTEN = 6
    COMPLETED = 7

class OperationJournal:
    """Manages the idempotent state machine for crash recovery during runs."""
    
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # timeout=10 allows threads to wait up to 10 seconds for a lock before failing
        return sqlite3.connect(self.db_path, timeout=10)

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Enable Write-Ahead Logging for better concurrency
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                source_dir TEXT NOT NULL,
                target_dir TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS document_states (
                run_id TEXT NOT NULL,
                source_path TEXT NOT NULL,
                content_hash TEXT,
                state INTEGER NOT NULL DEFAULT 0,
                target_path TEXT,
                error_message TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (run_id, source_path)
            );
            """)
            conn.commit()

    def start_or_resume_run(self, source_dir: str, target_dir: str) -> str:
        """Finds an incomplete run for these directories, or starts a new one."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Look for an interrupted run
            cursor.execute(
                "SELECT run_id FROM runs WHERE source_dir = ? AND target_dir = ? AND status = 'IN_PROGRESS' ORDER BY created_at DESC LIMIT 1",
                (source_dir, target_dir)
            )
            row = cursor.fetchone()
            if row:
                return row[0]
                
            # Create a new run
            run_id = str(uuid.uuid4())
            cursor.execute(
                "INSERT INTO runs (run_id, source_dir, target_dir, status) VALUES (?, ?, ?, 'IN_PROGRESS')",
                (run_id, source_dir, target_dir)
            )
            conn.commit()
            return run_id

    def mark_run_completed(self, run_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE runs SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP WHERE run_id = ?", (run_id,))
            conn.commit()

    def get_document_state(self, run_id: str, source_path: str) -> tuple[int, str | None]:
        """Returns the state int and the final target_path if known, or PLANNED (0)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT state, target_path FROM document_states WHERE run_id = ? AND source_path = ?",
                (run_id, source_path)
            )
            row = cursor.fetchone()
            if row:
                return row[0], row[1]
        return DocState.PLANNED.value, None

    def update_document_state(self, run_id: str, source_path: str, state: int, content_hash: str | None = None, target_path: str | None = None, error: str | None = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if exists
            cursor.execute("SELECT 1 FROM document_states WHERE run_id = ? AND source_path = ?", (run_id, source_path))
            exists = cursor.fetchone()
            
            if exists:
                updates = ["state = ?", "updated_at = CURRENT_TIMESTAMP"]
                params = [state]
                if content_hash is not None:
                    updates.append("content_hash = ?")
                    params.append(content_hash)
                if target_path is not None:
                    updates.append("target_path = ?")
                    params.append(target_path)
                if error is not None:
                    updates.append("error_message = ?")
                    params.append(error)
                    
                params.extend([run_id, source_path])
                query = f"UPDATE document_states SET {', '.join(updates)} WHERE run_id = ? AND source_path = ?"
                cursor.execute(query, params)
            else:
                cursor.execute(
                    """
                    INSERT INTO document_states (run_id, source_path, state, content_hash, target_path, error_message)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, source_path, state, content_hash, target_path, error)
                )
            conn.commit()
