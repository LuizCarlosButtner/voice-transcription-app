"""Gerenciamento do histórico local de transcrições em SQLite e recuperação de fatias órfãs."""

import datetime
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Optional

import config

_bancos_inicializados: set[str] = set()


def _garantir_esquema_conexao(conexao: sqlite3.Connection) -> None:
    """Cria a tabela de transcrições, aplica migrações seguras e garante os índices."""
    conexao.execute(
        """
        CREATE TABLE IF NOT EXISTS transcriptions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            duration_ms INTEGER DEFAULT 0,
            provider TEXT NOT NULL,
            language TEXT NOT NULL,
            status TEXT NOT NULL,
            text_raw TEXT,
            text_final TEXT,
            tone TEXT DEFAULT 'verbatim',
            grammar_fixed INTEGER DEFAULT 0,
            error_message TEXT,
            audio_path TEXT NOT NULL,
            chunk_files_json TEXT,
            active_app TEXT,
            focused_element TEXT,
            mode TEXT DEFAULT 'segurar',
            retry_of TEXT,
            FOREIGN KEY(retry_of) REFERENCES transcriptions(id)
        );
        """
    )

    cursor = conexao.execute("PRAGMA table_info(transcriptions);")
    colunas = [linha[1] for linha in cursor.fetchall()]
    if "chunk_files_json" not in colunas:
        conexao.execute("ALTER TABLE transcriptions ADD COLUMN chunk_files_json TEXT;")

    conexao.execute("UPDATE transcriptions SET status = 'sent' WHERE status = 'success';")
    conexao.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcriptions_created ON transcriptions(created_at DESC);"
    )
    conexao.execute(
        "CREATE INDEX IF NOT EXISTS idx_transcriptions_status ON transcriptions(status);"
    )
    conexao.commit()


def obter_conexao() -> sqlite3.Connection:
    """Abre conexão SQLite lendo dinamicamente config.ARQUIVO_BANCO_HISTORICO."""
    caminho_banco = Path(config.ARQUIVO_BANCO_HISTORICO)
    caminho_banco.parent.mkdir(parents=True, exist_ok=True)
    ja_existia = caminho_banco.exists() and caminho_banco.stat().st_size > 0

    conexao = sqlite3.connect(str(caminho_banco))
    conexao.row_factory = sqlite3.Row

    chave_banco = str(caminho_banco.resolve())
    if not ja_existia or chave_banco not in _bancos_inicializados:
        _garantir_esquema_conexao(conexao)
        _bancos_inicializados.add(chave_banco)

    return conexao


def inicializar_banco() -> None:
    """Inicializa explicitamente o esquema do banco configurado em config.ARQUIVO_BANCO_HISTORICO."""
    caminho_banco = Path(config.ARQUIVO_BANCO_HISTORICO)
    caminho_banco.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(caminho_banco)) as conexao:
        conexao.row_factory = sqlite3.Row
        _garantir_esquema_conexao(conexao)
    _bancos_inicializados.add(str(caminho_banco.resolve()))


def _extrair_sessao_e_indice_fatia(arquivo: Path) -> Optional[tuple[str, int]]:
    """Extrai o identificador de sessão e o índice numérico de um arquivo de fatia."""
    nome_base = arquivo.stem
    for separador in ("_chunk_", "_fatia_"):
        if separador in nome_base:
            partes = nome_base.rsplit(separador, 1)
            if len(partes) == 2 and partes[0]:
                try:
                    indice = int(partes[1])
                except ValueError:
                    indice = 0
                return partes[0], indice
    return None


class GerenciadorHistorico:
    """Controla o ciclo de vida dos registros de transcrição e a recuperação anti-perda."""

    def __init__(self, inicializar_imediatamente: bool = True) -> None:
        if inicializar_imediatamente:
            inicializar_banco()

    def verificar_integridade(self) -> tuple[bool, str]:
        """Executa PRAGMA quick_check para validar a integridade do banco SQLite."""
        try:
            with obter_conexao() as conexao:
                linhas = conexao.execute("PRAGMA quick_check;").fetchall()
            if not linhas:
                return False, "PRAGMA quick_check retornou resposta vazia"
            mensagens = [str(linha[0]) for linha in linhas]
            integro = all(msg.lower() == "ok" for msg in mensagens)
            return integro, ("ok" if integro else "; ".join(mensagens))
        except Exception as erro:
            return False, f"Falha na verificação de integridade SQLite: {erro}"

    def criar_registro_pendente(
        self,
        caminho_audio: str,
        id_registro: Optional[str] = None,
        aplicativo_ativo: Optional[str] = None,
        elemento_focado: Optional[str] = None,
        modo: str = "segurar",
        idioma: str = "pt",
        provedor: str = "groq",
        tom: str = "verbatim",
        retentativa_de: Optional[str] = None,
    ) -> str:
        """Cria um registro com status pendente antes de iniciar a captura ou transcrição."""
        identificador = id_registro or str(uuid.uuid4())
        agora_iso = datetime.datetime.now().astimezone().isoformat()
        with obter_conexao() as conexao:
            conexao.execute(
                """
                INSERT INTO transcriptions (
                    id, created_at, duration_ms, provider, language,
                    status, audio_path, active_app, focused_element,
                    mode, tone, retry_of
                ) VALUES (?, ?, 0, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                """,
                (
                    identificador,
                    agora_iso,
                    provedor,
                    idioma,
                    str(caminho_audio),
                    aplicativo_ativo,
                    elemento_focado,
                    modo,
                    tom,
                    retentativa_de,
                ),
            )
            conexao.commit()
        return identificador

    def marcar_enviado(
        self,
        id_registro: str,
        duracao_ms: int,
        texto_bruto: str,
        texto_final: str,
        tom: str = "verbatim",
        gramatica_corrigida: bool = False,
        provedor: Optional[str] = None,
        caminho_audio: Optional[str] = None,
        arquivos_fatias: Optional[list[str]] = None,
    ) -> None:
        """Marca o registro como transcrito e inserido com sucesso."""
        fatias_json = (
            json.dumps([str(caminho) for caminho in arquivos_fatias])
            if arquivos_fatias
            else None
        )
        caminho_str = str(caminho_audio) if caminho_audio is not None else None
        with obter_conexao() as conexao:
            conexao.execute(
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
                (
                    duracao_ms,
                    texto_bruto,
                    texto_final,
                    tom,
                    1 if gramatica_corrigida else 0,
                    provedor,
                    caminho_str,
                    fatias_json,
                    id_registro,
                ),
            )
            conexao.commit()

    def marcar_escrito_nao_enviado(
        self,
        id_registro: str,
        duracao_ms: int,
        texto_bruto: str,
        texto_final: str,
        tom: str = "verbatim",
        gramatica_corrigida: bool = False,
        provedor: Optional[str] = None,
        caminho_audio: Optional[str] = None,
        motivo: str = "Transcrito, mas inserção no cursor não confirmada",
    ) -> None:
        """Marca o registro como transcrito, porém aguardando recuperação/colagem manual."""
        caminho_str = str(caminho_audio) if caminho_audio is not None else None
        with obter_conexao() as conexao:
            conexao.execute(
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
                (
                    duracao_ms,
                    texto_bruto,
                    texto_final,
                    tom,
                    1 if gramatica_corrigida else 0,
                    provedor,
                    caminho_str,
                    motivo,
                    id_registro,
                ),
            )
            conexao.commit()

    def marcar_parcial(
        self,
        id_registro: str,
        duracao_ms: int,
        caminho_audio: str,
        arquivos_fatias: list[str],
        aplicativo_ativo: Optional[str] = "Recuperado após reinício",
        provedor: str = "groq",
        idioma: str = "pt",
    ) -> None:
        """Registra áudio recuperado a partir de fatias órfãs encontradas em disco."""
        fatias_json = json.dumps([str(caminho) for caminho in arquivos_fatias])
        agora_iso = datetime.datetime.now().astimezone().isoformat()
        with obter_conexao() as conexao:
            conexao.execute(
                """
                INSERT OR REPLACE INTO transcriptions (
                    id, created_at, duration_ms, provider, language,
                    status, audio_path, chunk_files_json, active_app,
                    error_message, mode
                ) VALUES (?, ?, ?, ?, ?, 'partial', ?, ?, ?, 'Áudio fatiado recuperado de sessão interrompida', 'recuperacao_fatias')
                """,
                (
                    id_registro,
                    agora_iso,
                    duracao_ms,
                    provedor,
                    idioma,
                    str(caminho_audio),
                    fatias_json,
                    aplicativo_ativo,
                ),
            )
            conexao.commit()

    def marcar_erro(
        self,
        id_registro: str,
        duracao_ms: int,
        mensagem_erro: str,
        provedor: Optional[str] = None,
        caminho_audio: Optional[str] = None,
    ) -> None:
        """Marca o registro com falha de captura ou de transcrição."""
        caminho_str = str(caminho_audio) if caminho_audio is not None else None
        with obter_conexao() as conexao:
            conexao.execute(
                """
                UPDATE transcriptions
                SET status = 'error',
                    duration_ms = ?,
                    error_message = ?,
                    provider = COALESCE(?, provider),
                    audio_path = COALESCE(?, audio_path)
                WHERE id = ?
                """,
                (duracao_ms, mensagem_erro, provedor, caminho_str, id_registro),
            )
            conexao.commit()

    def marcar_vazio(
        self,
        id_registro: str,
        duracao_ms: int,
        caminho_audio: Optional[str] = None,
    ) -> None:
        """Marca o registro como vazio quando nenhuma fala é detectada."""
        caminho_str = str(caminho_audio) if caminho_audio is not None else None
        with obter_conexao() as conexao:
            conexao.execute(
                """
                UPDATE transcriptions
                SET status = 'empty',
                    duration_ms = ?,
                    error_message = 'Nenhuma fala detectada no áudio',
                    audio_path = COALESCE(?, audio_path)
                WHERE id = ?
                """,
                (duracao_ms, caminho_str, id_registro),
            )
            conexao.commit()

    def marcar_cancelado(
        self,
        id_registro: str,
        duracao_ms: int = 0,
        caminho_audio: Optional[str] = None,
    ) -> None:
        """Marca a gravação como cancelada pelo usuário mantendo o áudio para recuperação."""
        caminho_str = str(caminho_audio) if caminho_audio is not None else None
        with obter_conexao() as conexao:
            conexao.execute(
                """
                UPDATE transcriptions
                SET status = 'cancelled',
                    duration_ms = ?,
                    error_message = 'Cancelado pelo usuário (Esc) — Áudio preservado para recuperação',
                    audio_path = COALESCE(?, audio_path)
                WHERE id = ?
                """,
                (duracao_ms, caminho_str, id_registro),
            )
            conexao.commit()

    def listar_recuperaveis(self, limite: int = 10) -> list[dict[str, Any]]:
        """Lista os registros elegíveis para recuperação rápida no menu."""
        consulta_sql = """
            SELECT * FROM transcriptions
            WHERE status IN ('partial', 'written_not_sent', 'cancelled', 'error')
            ORDER BY created_at DESC
            LIMIT ?
        """
        with obter_conexao() as conexao:
            linhas = conexao.execute(consulta_sql, (limite,)).fetchall()
            return [dict(linha) for linha in linhas]

    def obter_registro(self, id_registro: str) -> Optional[dict[str, Any]]:
        """Busca um registro específico pelo identificador único."""
        with obter_conexao() as conexao:
            linha = conexao.execute(
                "SELECT * FROM transcriptions WHERE id = ?",
                (id_registro,),
            ).fetchone()
            return dict(linha) if linha else None

    def listar_registros(
        self,
        limite: int = 50,
        deslocamento: int = 0,
        status: Optional[str] = None,
        busca: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Retorna registros paginados com filtros opcionais de status e texto."""
        consulta_sql = "SELECT * FROM transcriptions WHERE 1=1"
        parametros: list[Any] = []

        if status:
            if status in ("success", "sent"):
                consulta_sql += " AND status IN ('sent', 'success')"
            else:
                consulta_sql += " AND status = ?"
                parametros.append(status)

        if busca:
            termo = f"%{busca}%"
            consulta_sql += (
                " AND (COALESCE(text_final, '') LIKE ?"
                " OR COALESCE(text_raw, '') LIKE ?"
                " OR COALESCE(active_app, '') LIKE ?)"
            )
            parametros.extend([termo, termo, termo])

        consulta_sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        parametros.extend([limite, deslocamento])

        with obter_conexao() as conexao:
            linhas = conexao.execute(consulta_sql, parametros).fetchall()
            return [dict(linha) for linha in linhas]

    def excluir_registro(self, id_registro: str, remover_audio: bool = False) -> bool:
        """Exclui um registro do histórico e, opcionalmente, remove seus arquivos de áudio."""
        registro = self.obter_registro(id_registro) if remover_audio else None

        with obter_conexao() as conexao:
            cursor = conexao.execute(
                "DELETE FROM transcriptions WHERE id = ?",
                (id_registro,),
            )
            conexao.commit()
            excluiu = cursor.rowcount > 0

        if excluiu and remover_audio and registro:
            caminhos_remover: list[str] = []
            if registro.get("audio_path"):
                caminhos_remover.append(str(registro["audio_path"]))
            if registro.get("chunk_files_json"):
                try:
                    fatias = json.loads(registro["chunk_files_json"])
                    if isinstance(fatias, list):
                        caminhos_remover.extend(str(item) for item in fatias if item)
                except Exception:
                    pass
            for caminho_str in caminhos_remover:
                try:
                    Path(caminho_str).unlink(missing_ok=True)
                except Exception:
                    pass

        return excluiu

    def recuperar_fatias_orfas(self) -> int:
        """Varre dinamicamente config.DIRETORIO_AUDIOS e recupera sessões interrompidas."""
        diretorio_audios = Path(config.DIRETORIO_AUDIOS)
        if not diretorio_audios.exists():
            return 0

        fatias_por_sessao: dict[str, list[tuple[int, Path]]] = {}
        for arquivo in diretorio_audios.iterdir():
            if not arquivo.is_file():
                continue
            if arquivo.suffix.lower() not in (".ogg", ".wav", ".webm", ".m4a"):
                continue
            extraido = _extrair_sessao_e_indice_fatia(arquivo)
            if extraido is not None:
                id_sessao, indice = extraido
                fatias_por_sessao.setdefault(id_sessao, []).append((indice, arquivo))

        if not fatias_por_sessao:
            return 0

        total_recuperadas = 0
        for id_sessao, itens_ordenaveis in fatias_por_sessao.items():
            itens_ordenaveis.sort(key=lambda par: par[0])
            arquivos_ordenados = [par[1] for par in itens_ordenaveis]

            existente = self.obter_registro(id_sessao)
            if existente and existente.get("status") in (
                "sent",
                "success",
                "written_not_sent",
                "partial",
                "cancelled",
            ):
                continue

            candidatos_finais = [
                candidato
                for candidato in diretorio_audios.glob(f"{id_sessao}.*")
                if "_chunk_" not in candidato.name and "_fatia_" not in candidato.name
            ]
            if candidatos_finais and existente and existente.get("status") != "pending":
                continue

            duracao_total_ms = 0
            for arquivo_fatia in arquivos_ordenados:
                try:
                    import soundfile

                    informacao = soundfile.info(str(arquivo_fatia))
                    duracao_total_ms += max(1, int(informacao.duration * 1000))
                except Exception:
                    duracao_total_ms += 30000

            audio_principal = (
                str(candidatos_finais[0])
                if candidatos_finais
                else str(arquivos_ordenados[0])
            )
            lista_caminhos = [str(caminho) for caminho in arquivos_ordenados]

            self.marcar_parcial(
                id_registro=id_sessao,
                duracao_ms=duracao_total_ms,
                caminho_audio=audio_principal,
                arquivos_fatias=lista_caminhos,
                aplicativo_ativo="Recuperado após reinício",
            )
            total_recuperadas += 1

        return total_recuperadas

    def obter_estatisticas(self) -> dict[str, Any]:
        """Calcula estatísticas consolidadas das transcrições armazenadas."""
        with obter_conexao() as conexao:
            total = conexao.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0]
            enviados = conexao.execute(
                "SELECT COUNT(*) FROM transcriptions WHERE status IN ('sent', 'success')"
            ).fetchone()[0]
            nao_enviados = conexao.execute(
                "SELECT COUNT(*) FROM transcriptions WHERE status = 'written_not_sent'"
            ).fetchone()[0]
            cancelados = conexao.execute(
                "SELECT COUNT(*) FROM transcriptions WHERE status = 'cancelled'"
            ).fetchone()[0]
            erros = conexao.execute(
                "SELECT COUNT(*) FROM transcriptions WHERE status = 'error'"
            ).fetchone()[0]
            parciais = conexao.execute(
                "SELECT COUNT(*) FROM transcriptions WHERE status = 'partial'"
            ).fetchone()[0]
            media_duracao = conexao.execute(
                "SELECT AVG(duration_ms) FROM transcriptions WHERE duration_ms > 0"
            ).fetchone()[0]

            return {
                "total": total,
                "sent": enviados,
                "success": enviados,
                "written_not_sent": nao_enviados,
                "cancelled": cancelados,
                "partial": parciais,
                "errors": erros,
                "avg_duration_ms": round(media_duracao or 0, 1),
            }


gerenciador_historico = GerenciadorHistorico(inicializar_imediatamente=False)
