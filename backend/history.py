import sqlite3
import datetime
import uuid
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from config import HISTORY_DB_FILE, AUDIO_STORAGE_DIR

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
                status TEXT NOT NULL, -- 'sent', 'written_not_sent', 'cancelled', 'error', 'empty', 'partial'
                text_raw TEXT,
                text_final TEXT,
                tone TEXT DEFAULT 'verbatim',
                grammar_fixed INTEGER DEFAULT 0,
                error_message TEXT,
                audio_path TEXT NOT NULL,
                chunk_files_json TEXT, -- lista JSON de caminhos dos chunks gravados
                active_app TEXT,
                focused_element TEXT,
                mode TEXT DEFAULT 'push_and_hold',
                retry_of TEXT,
                FOREIGN KEY(retry_of) REFERENCES transcriptions(id)
            );
        """)
        
        # Migração segura da coluna chunk_files_json se a tabela já existir de versões anteriores
        cursor = conn.execute("PRAGMA table_info(transcriptions);")
        columns = [row[1] for row in cursor.fetchall()]
        if "chunk_files_json" not in columns:
            conn.execute("ALTER TABLE transcriptions ADD COLUMN chunk_files_json TEXT;")

        # Migração de status legado 'success' -> 'sent'
        conn.execute("UPDATE transcriptions SET status = 'sent' WHERE status = 'success';")

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

    def mark_sent(
        self,
        entry_id: str,
        duration_ms: int,
        text_raw: str,
        text_final: str,
        tone: str = "verbatim",
        grammar_fixed: bool = False,
        provider: Optional[str] = None,
        audio_path: Optional[str] = None,
        chunk_files: Optional[List[str]] = None
    ):
        """Marca como áudio enviado e colado com sucesso no cursor."""
        chunks_json = json.dumps(chunk_files) if chunk_files else None
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcriptions
                SET status = 'sent',
                    duration_ms = ?,
                    text_raw = ?,
                    text_final = ?,
                    tone = ?,
                    grammar_fixed = ?,
                    provider = COALESCE(?, provider),
                    audio_path = COALESCE(?, audio_path),
                    chunk_files_json = COALESCE(?, chunk_files_json),
                    error_message = NULL
                WHERE id = ?
                """,
                (duration_ms, text_raw, text_final, tone, 1 if grammar_fixed else 0, provider, audio_path, chunks_json, entry_id)
            )
            conn.commit()

    # Alias de compatibilidade com código existente
    def mark_success(self, *args, **kwargs):
        self.mark_sent(*args, **kwargs)

    def mark_written_not_sent(
        self,
        entry_id: str,
        duration_ms: int,
        text_raw: str,
        text_final: str,
        tone: str = "verbatim",
        grammar_fixed: bool = False,
        provider: Optional[str] = None,
        audio_path: Optional[str] = None,
        reason: str = "Transcrito com sucesso, mas a inserção no cursor não pôde ser confirmada"
    ):
        """Marca como áudio transcrito, mas não enviado ao input."""
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcriptions
                SET status = 'written_not_sent',
                    duration_ms = ?,
                    text_raw = ?,
                    text_final = ?,
                    tone = ?,
                    grammar_fixed = ?,
                    provider = COALESCE(?, provider),
                    audio_path = COALESCE(?, audio_path),
                    error_message = ?
                WHERE id = ?
                """,
                (duration_ms, text_raw, text_final, tone, 1 if grammar_fixed else 0, provider, audio_path, reason, entry_id)
            )
            conn.commit()

    def mark_partial(
        self,
        entry_id: str,
        duration_ms: int,
        audio_path: str,
        chunk_files: List[str],
        active_app: Optional[str] = "Recuperado após reinício",
        provider: str = "groq",
        language: str = "pt"
    ):
        """Registra áudio recuperado de chunks órfãos gerados antes de um crash ou desligamento."""
        chunks_json = json.dumps(chunk_files)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO transcriptions (
                    id, created_at, duration_ms, provider, language,
                    status, audio_path, chunk_files_json, active_app,
                    error_message, mode
                ) VALUES (?, ?, ?, ?, ?, 'partial', ?, ?, ?, 'Áudio fatiado recuperado de sessão interrompida', 'chunk_recovery')
                """,
                (entry_id, now, duration_ms, provider, language, str(audio_path), chunks_json, active_app)
            )
            conn.commit()

    def mark_error(
        self,
        entry_id: str,
        duration_ms: int,
        error_message: str,
        provider: Optional[str] = None,
        audio_path: Optional[str] = None
    ):
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcriptions
                SET status = 'error',
                    duration_ms = ?,
                    error_message = ?,
                    provider = COALESCE(?, provider),
                    audio_path = COALESCE(?, audio_path)
                WHERE id = ?
                """,
                (duration_ms, error_message, provider, audio_path, entry_id)
            )
            conn.commit()

    def mark_empty(self, entry_id: str, duration_ms: int, audio_path: Optional[str] = None):
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcriptions
                SET status = 'empty',
                    duration_ms = ?,
                    error_message = 'Nenhuma fala detectada no áudio',
                    audio_path = COALESCE(?, audio_path)
                WHERE id = ?
                """,
                (duration_ms, audio_path, entry_id)
            )
            conn.commit()

    def mark_cancelled(self, entry_id: str, duration_ms: int = 0, audio_path: Optional[str] = None):
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE transcriptions
                SET status = 'cancelled',
                    duration_ms = ?,
                    error_message = 'Cancelado pelo usuário (Esc) — Áudio preservado para recuperação',
                    audio_path = COALESCE(?, audio_path)
                WHERE id = ?
                """,
                (duration_ms, audio_path, entry_id)
            )
            conn.commit()

    def list_recoverable(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retorna as gravações que não foram enviadas com sucesso ao input:
        (partial, written_not_sent, cancelled, error), prontas para serem recuperadas.
        """
        sql = """
            SELECT * FROM transcriptions 
            WHERE status IN ('partial', 'written_not_sent', 'cancelled', 'error')
            ORDER BY created_at DESC 
            LIMIT ?
        """
        with get_connection() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
            return [dict(r) for r in rows]

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
            if status == "success":
                sql += " AND status IN ('sent', 'success')"
            else:
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

    def recover_orphaned_chunks(self) -> int:
        """
        Varre o diretório de áudio por chunks órfãos (*_chunk_*.ogg / *.wav)
        decorrentes de um crash ou desligamento do computador.
        Para cada sessão que não possua gravação finalizada, consolida os chunks
        e gera uma entrada 'partial' pronta para recuperação no menu.
        É 100% idempotente (não gera duplicidades se executado repetidamente).
        """
        if not AUDIO_STORAGE_DIR.exists():
            return 0

        # Mapeia chunks agrupados por session_id
        session_chunks: Dict[str, List[Path]] = {}
        for f in AUDIO_STORAGE_DIR.glob("*_chunk_*.*"):
            if f.suffix.lower() in (".ogg", ".wav"):
                # Padrão: {session_id}_chunk_{index}.{ext}
                parts = f.stem.split("_chunk_")
                if len(parts) == 2:
                    sid = parts[0]
                    session_chunks.setdefault(sid, []).append(f)

        if not session_chunks:
            return 0

        recovered_count = 0
        with get_connection() as conn:
            for sid, chunks in session_chunks.items():
                # Ordena os chunks pelo índice
                def get_chunk_idx(p: Path):
                    try:
                        return int(p.stem.split("_chunk_")[1])
                    except Exception:
                        return 0
                chunks.sort(key=get_chunk_idx)

                # Verifica se a sessão já foi finalizada ou já está registrada no banco
                existing = conn.execute("SELECT id, status FROM transcriptions WHERE id = ?", (sid,)).fetchone()
                if existing and existing["status"] in ("sent", "written_not_sent", "partial"):
                    continue

                # Calcula duração estimada total somando os arquivos de áudio
                total_duration_ms = 0
                for ch in chunks:
                    try:
                        import soundfile as sf
                        info = sf.info(str(ch))
                        total_duration_ms += int(info.duration * 1000)
                    except Exception:
                        total_duration_ms += 30000 # estimativa padrão 30s por chunk

                # Se já havia um arquivo consolidado final correspondente, não é órfão
                final_candidates = list(AUDIO_STORAGE_DIR.glob(f"{sid}.*"))
                final_candidates = [fc for fc in final_candidates if "_chunk_" not in fc.name]
                if final_candidates and existing and existing["status"] != "pending":
                    continue

                # Usa o primeiro chunk ou o arquivo consolidado como referência de áudio
                primary_audio = str(final_candidates[0]) if final_candidates else str(chunks[0])
                chunk_paths_str = [str(c) for c in chunks]

                self.mark_partial(
                    entry_id=sid,
                    duration_ms=total_duration_ms,
                    audio_path=primary_audio,
                    chunk_files=chunk_paths_str,
                    active_app="Recuperado (Sessão Interrompida)"
                )
                recovered_count += 1

        return recovered_count

    def get_stats(self) -> Dict[str, Any]:
        with get_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0]
            sent = conn.execute("SELECT COUNT(*) FROM transcriptions WHERE status IN ('sent', 'success')").fetchone()[0]
            written_not_sent = conn.execute("SELECT COUNT(*) FROM transcriptions WHERE status = 'written_not_sent'").fetchone()[0]
            cancelled = conn.execute("SELECT COUNT(*) FROM transcriptions WHERE status = 'cancelled'").fetchone()[0]
            errors = conn.execute("SELECT COUNT(*) FROM transcriptions WHERE status = 'error'").fetchone()[0]
            partial = conn.execute("SELECT COUNT(*) FROM transcriptions WHERE status = 'partial'").fetchone()[0]
            avg_duration = conn.execute("SELECT AVG(duration_ms) FROM transcriptions WHERE duration_ms > 0").fetchone()[0]
            return {
                "total": total,
                "sent": sent,
                "success": sent,  # compatibilidade com UI
                "written_not_sent": written_not_sent,
                "cancelled": cancelled,
                "partial": partial,
                "errors": errors,
                "avg_duration_ms": round(avg_duration or 0, 1)
            }

history_manager = HistoryManager()
