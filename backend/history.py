import sqlite3
import datetime
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any
from config import HISTORY_DB_FILE

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(HISTORY_DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcriptions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                duration_ms INTEGER DEFAULT 0,
                provider TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL, -- 'success', 'error', 'empty', 'cancelled'
                text_raw TEXT,
                text_final TEXT,
                tone TEXT DEFAULT 'verbatim',
                grammar_fixed INTEGER DEFAULT 0,
                error_message TEXT,
                audio_path TEXT NOT NULL,
                active_app TEXT,
                focused_element TEXT,
                mode TEXT DEFAULT 'push_and_hold',
                retry_of TEXT,
                FOREIGN KEY(retry_of) REFERENCES transcriptions(id)
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transcriptions_created ON transcriptions(created_at DESC);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transcriptions_status ON transcriptions(status);")
        conn.commit()

class HistoryManager:
    def __init__(self):
        init_db()

    def create_pending_entry(
        self,
        audio_path: str,
        entry_id: Optional[str] = None,
        active_app: Optional[str] = None,
        focused_element: Optional[str] = None,
        mode: str = "push_and_hold",
        language: str = "pt",
        provider: str = "groq",
        tone: str = "verbatim",
        retry_of: Optional[str] = None
    ) -> str:
        """Cria imediatamente o registro antes de transcrever. Garante persistência do áudio bruto."""
        eid = entry_id or str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO transcriptions (
                    id, created_at, duration_ms, provider, language,
                    status, audio_path, active_app, focused_element,
                    mode, tone, retry_of
                ) VALUES (?, ?, 0, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                """,
                (eid, now, provider, language, str(audio_path), active_app, focused_element, mode, tone, retry_of)
            )
            conn.commit()
        return eid

    def mark_success(
        self,
        entry_id: str,
        duration_ms: int,
        text_raw: str,
        text_final: str,
        tone: str = "verbatim",
        grammar_fixed: bool = False,
        provider: Optional[str] = None
    ):
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcriptions
                SET status = 'success',
                    duration_ms = ?,
                    text_raw = ?,
                    text_final = ?,
                    tone = ?,
                    grammar_fixed = ?,
                    provider = COALESCE(?, provider),
                    error_message = NULL
                WHERE id = ?
                """,
                (duration_ms, text_raw, text_final, tone, 1 if grammar_fixed else 0, provider, entry_id)
            )
            conn.commit()

    def mark_error(
        self,
        entry_id: str,
        duration_ms: int,
        error_message: str,
        provider: Optional[str] = None
    ):
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcriptions
                SET status = 'error',
                    duration_ms = ?,
                    error_message = ?,
                    provider = COALESCE(?, provider)
                WHERE id = ?
                """,
                (duration_ms, error_message, provider, entry_id)
            )
            conn.commit()

    def mark_empty(self, entry_id: str, duration_ms: int):
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcriptions
                SET status = 'empty',
                    duration_ms = ?,
                    error_message = 'Nenhuma fala detectada no áudio'
                WHERE id = ?
                """,
                (duration_ms, entry_id)
            )
            conn.commit()

    def mark_cancelled(self, entry_id: str, duration_ms: int = 0):
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcriptions
                SET status = 'cancelled',
                    duration_ms = ?,
                    error_message = 'Cancelado pelo usuário (Esc)'
                WHERE id = ?
                """,
                (duration_ms, entry_id)
            )
            conn.commit()

    def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM transcriptions WHERE id = ?", (entry_id,)).fetchone()
            if row:
                return dict(row)
            return None

    def list_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM transcriptions WHERE 1=1"
        params = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if query:
            sql += " AND (text_final LIKE ? OR text_raw LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def delete_entry(self, entry_id: str) -> bool:
        with get_connection() as conn:
            cur = conn.execute("DELETE FROM transcriptions WHERE id = ?", (entry_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_stats(self) -> Dict[str, Any]:
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM transcriptions WHERE status = 'success'").fetchone()[0]
            errors = conn.execute("SELECT COUNT(*) FROM transcriptions WHERE status = 'error'").fetchone()[0]
            avg_duration = conn.execute("SELECT AVG(duration_ms) FROM transcriptions WHERE duration_ms > 0").fetchone()[0]
            return {
                "total": total,
                "success": success,
                "errors": errors,
                "avg_duration_ms": round(avg_duration or 0, 1)
            }

history_manager = HistoryManager()
