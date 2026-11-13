import datetime
import time
from typing import Optional

import active_app as modulo_app_ativo
import config
import history as modulo_historico
import providers.sensevoice as modulo_sensevoice
import recorder as modulo_gravador
from active_app import acessibilidade_ativa, monitoramento_entrada_ativo
from config import obter_chave_groq, obter_configuracoes
from history import gerenciador_historico
from providers.sensevoice import ProvedorSenseVoice
from recorder import gravador, obter_status_microfone_macos

_REF_INICIAL_CHAVE_GROQ = obter_chave_groq
_REF_INICIAL_OBTER_CONFIGURACOES = obter_configuracoes
_REF_INICIAL_STATUS_MIC = obter_status_microfone_macos
_REF_INICIAL_ACESSIBILIDADE = acessibilidade_ativa
_REF_INICIAL_MONITORAMENTO = monitoramento_entrada_ativo
_REF_INICIAL_SENSEVOICE = ProvedorSenseVoice
_REF_INICIAL_GRAVADOR = gravador
_REF_INICIAL_HISTORICO = gerenciador_historico


class ProtocoloInicializacao:
    """
    Executa o protocolo estruturado de diagnóstico e autoteste na inicialização
    validando armazenamento, provedores, permissões do macOS, áudio e escutador global.
    """

    def __init__(self) -> None:
        self._ultimo_relatorio: Optional[dict] = None

    def _verificar_armazenamento_banco(self) -> dict:
        try:
            config.DIRETORIO_BASE_APP.mkdir(parents=True, exist_ok=True)
            config.DIRETORIO_AUDIOS.mkdir(parents=True, exist_ok=True)

            instancia_historico = (
                gerenciador_historico
                if gerenciador_historico is not _REF_INICIAL_HISTORICO
                else modulo_historico.gerenciador_historico
            )

            integridade_ok, mensagem_integridade = (
                instancia_historico.verificar_integridade()
            )
            sessoes_recuperadas = int(instancia_historico.recuperar_fatias_orfas() or 0)

            detalhe = (
                f"SQLite íntegro ({mensagem_integridade}); {sessoes_recuperadas} sessão(ões) órfã(s) recuperada(s)"
                if integridade_ok
                else f"Falha na integridade do banco: {mensagem_integridade}"
            )
            return {
                "ok": bool(integridade_ok),
                "diretorio_base": str(config.DIRETORIO_BASE_APP),
                "diretorio_audios": str(config.DIRETORIO_AUDIOS),
                "banco_historico": str(config.ARQUIVO_BANCO_HISTORICO),
                "integridade_banco": mensagem_integridade,
                "sessoes_orfas_recuperadas": sessoes_recuperadas,
                "detalhe": detalhe,
            }
        except Exception as erro:
            return {
                "ok": False,
                "sessoes_orfas_recuperadas": 0,
                "detalhe": f"Erro ao validar armazenamento e banco: {erro}",
            }

    def _verificar_chaves_provedores(self) -> dict:
        try:
            funcao_config = (
                obter_configuracoes
                if obter_configuracoes is not _REF_INICIAL_OBTER_CONFIGURACOES
                else config.obter_configuracoes
            )
            funcao_chave = (
                obter_chave_groq
                if obter_chave_groq is not _REF_INICIAL_CHAVE_GROQ
                else config.obter_chave_groq
            )
            classe_sensevoice = (
                ProvedorSenseVoice
                if ProvedorSenseVoice is not _REF_INICIAL_SENSEVOICE
                else modulo_sensevoice.ProvedorSenseVoice
            )

            configuracoes = funcao_config()
            chave_groq_presente = bool(funcao_chave())

            ogg_disponivel = False
            try:
                import soundfile as sf

                formatos = sf.available_formats()
                ogg_disponivel = "OGG" in formatos if isinstance(formatos, dict) else True
            except Exception:
                ogg_disponivel = False

            sensevoice_disponivel = False
            try:
                sensevoice_disponivel = bool(classe_sensevoice().esta_disponivel())
            except Exception:
                sensevoice_disponivel = False

            if configuracoes.provedor == "sensevoice":
                provedor_ok = sensevoice_disponivel
            else:
                provedor_ok = chave_groq_presente

            partes_detalhe = [
                f"Groq={'OK' if chave_groq_presente else 'Ausente'}",
                f"OGG={'OK' if ogg_disponivel else 'Fallback WAV'}",
                f"SenseVoice={'OK' if sensevoice_disponivel else 'Indisponível'}",
            ]
            return {
                "ok": bool(provedor_ok),
                "provedor_primario": configuracoes.provedor,
                "groq_configurado": chave_groq_presente,
                "ogg_disponivel": ogg_disponivel,
                "sensevoice_disponivel": sensevoice_disponivel,
                "detalhe": " | ".join(partes_detalhe),
            }
        except Exception as erro:
            return {
                "ok": False,
                "groq_configurado": False,
                "ogg_disponivel": False,
                "sensevoice_disponivel": False,
                "detalhe": f"Erro ao verificar chaves e provedores: {erro}",
            }

    def _verificar_permissoes_macos(self) -> dict:
        try:
            funcao_mic = (
                obter_status_microfone_macos
                if obter_status_microfone_macos is not _REF_INICIAL_STATUS_MIC
                else modulo_gravador.obter_status_microfone_macos
            )
            funcao_acessibilidade = (
                acessibilidade_ativa
                if acessibilidade_ativa is not _REF_INICIAL_ACESSIBILIDADE
                else modulo_app_ativo.acessibilidade_ativa
            )
            funcao_monitoramento = (
                monitoramento_entrada_ativo
                if monitoramento_entrada_ativo is not _REF_INICIAL_MONITORAMENTO
                else modulo_app_ativo.monitoramento_entrada_ativo
            )

            status_microfone = str(funcao_mic())
            acessibilidade_ok = bool(funcao_acessibilidade(exibir_prompt=False))
            monitoramento_ok = bool(funcao_monitoramento())
            microfone_ok = status_microfone not in ("Denied", "Restricted")

            tudo_ok = microfone_ok and acessibilidade_ok and monitoramento_ok
            detalhe = (
                f"Microfone={status_microfone} | "
                f"Acessibilidade={'OK' if acessibilidade_ok else 'Pendente'} | "
                f"Monitoramento de Entrada={'OK' if monitoramento_ok else 'Pendente'}"
            )
            return {
                "ok": bool(tudo_ok),
                "microfone_status": status_microfone,
                "microfone_ok": microfone_ok,
                "acessibilidade_ativa": acessibilidade_ok,
                "monitoramento_entrada_ativo": monitoramento_ok,
                "detalhe": detalhe,
            }
        except Exception as erro:
            return {
                "ok": False,
                "microfone_status": "Unknown",
                "microfone_ok": False,
                "acessibilidade_ativa": False,
                "monitoramento_entrada_ativo": False,
                "detalhe": f"Erro ao consultar permissões do macOS: {erro}",
            }

    def _verificar_subsistema_audio(self, recarregar_audio: bool) -> dict:
        try:
            instancia_gravador = (
                gravador
                if gravador is not _REF_INICIAL_GRAVADOR
                else modulo_gravador.gravador
            )

            dispositivos_recarregados = False
            if recarregar_audio and not bool(instancia_gravador.esta_gravando):
                dispositivos_recarregados = bool(
                    instancia_gravador.recarregar_dispositivos()
                )

            resultado_sondagem = instancia_gravador.sondar_microfone() or {}
            audio_ok = bool(resultado_sondagem.get("ok", False))

            return {
                "ok": audio_ok,
                "dispositivos_recarregados": dispositivos_recarregados,
                "dispositivo_indice": resultado_sondagem.get("dispositivo_indice"),
                "dispositivo_nome": resultado_sondagem.get("dispositivo_nome"),
                "taxa_amostragem": resultado_sondagem.get("taxa_amostragem"),
                "detalhe": resultado_sondagem.get("detalhe", ""),
            }
        except Exception as erro:
            return {
                "ok": False,
                "dispositivos_recarregados": False,
                "dispositivo_indice": None,
                "dispositivo_nome": None,
                "taxa_amostragem": None,
                "detalhe": f"Erro ao sondar subsistema de áudio: {erro}",
            }

    def _verificar_escutador_atalho(self, servico_voz_ref=None) -> dict:
        try:
            funcao_config = (
                obter_configuracoes
                if obter_configuracoes is not _REF_INICIAL_OBTER_CONFIGURACOES
                else config.obter_configuracoes
            )
            configuracoes = funcao_config()

            if servico_voz_ref is None:
                return {
                    "ok": True,
                    "escuta_ativa": False,
                    "atalho": configuracoes.atalho,
                    "modo_acionamento": configuracoes.modo_acionamento,
                    "detalhe": "Serviço de voz não informado na verificação isolada",
                }

            if not bool(servico_voz_ref.escuta_ativa):
                servico_voz_ref.iniciar_escuta()

            ativa = bool(servico_voz_ref.escuta_ativa)
            detalhe = (
                f"Escutador global ativo ({configuracoes.atalho} / {configuracoes.modo_acionamento})"
                if ativa
                else f"Escutador global inativo ({configuracoes.atalho} / {configuracoes.modo_acionamento})"
            )
            return {
                "ok": ativa,
                "escuta_ativa": ativa,
                "atalho": configuracoes.atalho,
                "modo_acionamento": configuracoes.modo_acionamento,
                "detalhe": detalhe,
            }
        except Exception as erro:
            return {
                "ok": False,
                "escuta_ativa": False,
                "atalho": "Alt",
                "modo_acionamento": "hibrido",
                "detalhe": f"Erro ao validar escutador de atalho: {erro}",
            }

    def executar_autoteste(
        self, servico_voz_ref=None, recarregar_audio: bool = True
    ) -> dict:
        """Executa as 5 etapas de diagnóstico de inicialização sem propagar exceções."""
        inicio = time.perf_counter()

        etapas = {
            "armazenamento_banco": self._verificar_armazenamento_banco(),
            "chaves_provedores": self._verificar_chaves_provedores(),
            "permissoes_macos": self._verificar_permissoes_macos(),
            "subsistema_audio": self._verificar_subsistema_audio(recarregar_audio),
            "escutador_atalho": self._verificar_escutador_atalho(servico_voz_ref),
        }

        duracao_ms = max(0, int((time.perf_counter() - inicio) * 1000))
        ok_geral = all(bool(dados_etapa.get("ok", False)) for dados_etapa in etapas.values())

        relatorio = {
            "ok": ok_geral,
            "executado_em": datetime.datetime.now().astimezone().isoformat(),
            "duracao_ms": duracao_ms,
            "etapas": etapas,
        }
        self._ultimo_relatorio = relatorio
        return relatorio

    def obter_ultimo_relatorio(self) -> Optional[dict]:
        """Retorna o relatório do último autoteste executado, ou `None` se ainda não rodou."""
        return self._ultimo_relatorio


protocolo_inicializacao = ProtocoloInicializacao()
