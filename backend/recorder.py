import threading
import time
import wave
from math import gcd
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

import config as modulo_config
from config import DIRETORIO_AUDIOS, obter_configuracoes

TAXA_AMOSTRAGEM_PADRAO = 16000
CANAIS_PADRAO = 1
TIPO_AMOSTRA = "int16"
LIMIAR_FALA_SILENCIO = 400

_DIRETORIO_AUDIOS_INICIAL = DIRETORIO_AUDIOS

# Dispositivos virtuais conhecidos que não devem ser selecionados para captura de voz
_PISTAS_DISPOSITIVOS_VIRTUAIS = (
    "voicemod",
    "blackhole",
    "soundflower",
    "loopback",
    "virtual",
    "capture",
    "aggregate",
    "multi-output",
    "multi-output device",
    "teams audio",
    "zoomaudio",
)

# Pistas de nomes que indicam microfone físico real
_PISTAS_MICROFONE_REAL = (
    "microfone",
    "microphone",
    "mic",
    "built-in",
    "internal",
    "macbook",
    "usb audio",
    "headset",
    "airpods",
)


def _obter_diretorio_audios() -> Path:
    """Resolve dinamicamente o diretório de áudios respeitando redirecionamentos de testes."""
    if DIRETORIO_AUDIOS != _DIRETORIO_AUDIOS_INICIAL:
        return DIRETORIO_AUDIOS
    return modulo_config.DIRETORIO_AUDIOS


def obter_status_microfone_macos() -> str:
    """Verifica a permissão do microfone via AVFoundation no macOS sem bloquear a thread."""
    try:
        import objc
        from Foundation import NSBundle

        pacote = NSBundle.bundleWithPath_(
            "/System/Library/Frameworks/AVFoundation.framework"
        )
        if pacote:
            pacote.load()
            classe_dispositivo = objc.lookUpClass("AVCaptureDevice")
            if classe_dispositivo:
                codigo_status = classe_dispositivo.authorizationStatusForMediaType_("soun")
                mapeamento = {
                    0: "NotDetermined",
                    1: "Restricted",
                    2: "Denied",
                    3: "Authorized",
                }
                return mapeamento.get(codigo_status, "Unknown")
    except Exception:
        pass
    return "Authorized"


def solicitar_permissao_microfone_macos() -> None:
    """Solicita o diálogo nativo de permissão de microfone do macOS."""
    try:
        import objc
        from Foundation import NSBundle

        pacote = NSBundle.bundleWithPath_(
            "/System/Library/Frameworks/AVFoundation.framework"
        )
        if pacote:
            pacote.load()
            classe_dispositivo = objc.lookUpClass("AVCaptureDevice")
            if classe_dispositivo:

                def _ao_concluir(concedido: bool) -> None:
                    pass

                classe_dispositivo.requestAccessForMediaType_completionHandler_(
                    "soun", _ao_concluir
                )
    except Exception:
        pass


def selecionar_dispositivo_entrada(recarregar: bool = False) -> Optional[int]:
    """
    Seleciona o melhor dispositivo de entrada real, ignorando drivers virtuais e nomes corrompidos.
    Se `recarregar=True` e não houver gravação em andamento, reinicializa o PortAudio com segurança.
    """
    try:
        import sounddevice as sd

        if recarregar:
            gravando_agora = bool(
                "gravador" in globals()
                and gravador is not None
                and gravador.esta_gravando
            )
            if not gravando_agora:
                try:
                    if hasattr(sd, "_terminate") and hasattr(sd, "_initialize"):
                        sd._terminate()
                        sd._initialize()
                except Exception:
                    pass

        dispositivos = sd.query_devices()
    except Exception:
        return None

    candidatos: list[tuple[int, str]] = []
    for indice, dispositivo in enumerate(dispositivos):
        if dispositivo.get("max_input_channels", 0) <= 0:
            continue
        nome = (dispositivo.get("name") or "").lower()
        if not nome.strip("? "):
            continue
        if any(pista in nome for pista in _PISTAS_DISPOSITIVOS_VIRTUAIS):
            continue
        candidatos.append((indice, nome))

    if not candidatos:
        return None

    for indice, nome in candidatos:
        if any(pista in nome for pista in _PISTAS_MICROFONE_REAL):
            return indice

    return candidatos[0][0]


def _reamostrar_audio(
    dados_audio: np.ndarray,
    taxa_origem: int,
    taxa_destino: int = TAXA_AMOSTRAGEM_PADRAO,
) -> np.ndarray:
    """Reamostra o vetor de áudio para `taxa_destino` (16 kHz) preservando formato e amplitude."""
    if (
        taxa_origem <= 0
        or taxa_destino <= 0
        or int(taxa_origem) == int(taxa_destino)
        or len(dados_audio) == 0
    ):
        return dados_audio

    era_int16 = dados_audio.dtype == np.int16
    era_bidimensional = dados_audio.ndim == 2
    vetor_plano = dados_audio.reshape(-1).astype(np.float64)

    try:
        from scipy.signal import resample_poly

        divisor = gcd(int(taxa_origem), int(taxa_destino))
        fator_cima = int(taxa_destino) // divisor
        fator_baixo = int(taxa_origem) // divisor
        vetor_reamostrado = resample_poly(vetor_plano, fator_cima, fator_baixo)
    except Exception:
        novo_tamanho = max(1, int(round(len(vetor_plano) * taxa_destino / taxa_origem)))
        eixo_origem = np.linspace(0.0, 1.0, num=len(vetor_plano), endpoint=False)
        eixo_destino = np.linspace(0.0, 1.0, num=novo_tamanho, endpoint=False)
        vetor_reamostrado = np.interp(eixo_destino, eixo_origem, vetor_plano)

    if era_int16:
        resultado = np.clip(np.round(vetor_reamostrado), -32768, 32767).astype(np.int16)
    else:
        resultado = vetor_reamostrado.astype(dados_audio.dtype)

    if era_bidimensional:
        return resultado.reshape(-1, 1)
    return resultado


def salvar_arquivo_audio(
    dados_audio: np.ndarray,
    caminho_destino: Path,
    taxa_amostragem: int = TAXA_AMOSTRAGEM_PADRAO,
) -> Path:
    """
    Salva áudio em formato OGG Vorbis compacto via `soundfile`.
    Caso OGG não esteja disponível, realiza contingência segura para WAV PCM 16-bit.
    """
    caminho_destino = Path(caminho_destino)
    caminho_destino.parent.mkdir(parents=True, exist_ok=True)

    caminho_ogg = (
        caminho_destino.with_suffix(".ogg")
        if caminho_destino.suffix.lower() in (".wav", ".ogg", "")
        else caminho_destino
    )

    try:
        import soundfile as sf

        sf.write(
            str(caminho_ogg),
            dados_audio,
            int(taxa_amostragem),
            format="OGG",
            subtype="VORBIS",
        )
        return caminho_ogg
    except Exception:
        caminho_wav = caminho_destino.with_suffix(".wav")
        if dados_audio.dtype == np.int16:
            dados_pcm16 = dados_audio
        elif np.issubdtype(dados_audio.dtype, np.floating) and (
            len(dados_audio) == 0 or float(np.max(np.abs(dados_audio))) <= 1.05
        ):
            dados_pcm16 = (np.clip(dados_audio, -1.0, 1.0) * 32767.0).astype(np.int16)
        else:
            dados_pcm16 = np.clip(dados_audio, -32768, 32767).astype(np.int16)

        with wave.open(str(caminho_wav), "wb") as arquivo_wav:
            arquivo_wav.setnchannels(CANAIS_PADRAO)
            arquivo_wav.setsampwidth(2)
            arquivo_wav.setframerate(int(taxa_amostragem))
            arquivo_wav.writeframes(dados_pcm16.tobytes())
        return caminho_wav


class GravadorAudio:
    """Gerencia captura de microfone em tempo real, fatiamento anti-perda e envelope de voz."""

    def __init__(
        self,
        taxa_amostragem: int = TAXA_AMOSTRAGEM_PADRAO,
        canais: int = CANAIS_PADRAO,
    ) -> None:
        self.taxa_amostragem = taxa_amostragem
        self.canais = canais

        self._fluxo: Any = None
        self._quadros: list[np.ndarray] = []
        self._trava = threading.Lock()
        self._esta_gravando = False
        self._instante_inicio = 0.0
        self._taxa_captura_ativa = taxa_amostragem
        self._dispositivo_ativo_indice: Optional[int] = None
        self._dispositivo_ativo_nome: Optional[str] = None

        # Controle de fatias contínuas de segurança
        self._id_sessao: Optional[str] = None
        self._amostras_descarregadas: int = 0
        self._indice_fatia: int = 0
        self._arquivos_fatias: list[Path] = []
        self._thread_supervisora: Optional[threading.Thread] = None
        self._evento_parar_supervisor = threading.Event()

        # Envelope suave de nível acústico e detecção de silêncio
        self._ultimo_instante_fala: float = 0.0
        self.nivel_atual: float = 0.0
        self.ao_parar_automatico: Optional[Callable[[], None]] = None

    @property
    def esta_gravando(self) -> bool:
        return self._esta_gravando

    @property
    def arquivos_fatias(self) -> list[Path]:
        return list(self._arquivos_fatias)

    @property
    def duracao_silencio(self) -> float:
        """Segundos decorridos desde a última fala detectada (0.0 se inativo)."""
        if not self._esta_gravando:
            return 0.0
        return max(0.0, time.time() - self._ultimo_instante_fala)

    def _obter_info_dispositivo(self, indice_dispositivo: Optional[int]) -> tuple[Optional[str], int]:
        """Obtém nome e taxa de amostragem padrão do dispositivo selecionado."""
        try:
            import sounddevice as sd

            if indice_dispositivo is not None:
                info = sd.query_devices(indice_dispositivo)
            else:
                info = sd.query_devices(kind="input")
            if isinstance(info, dict):
                nome = str(info.get("name") or "Microfone Padrão")
                taxa_padrao = int(
                    float(info.get("default_samplerate") or self.taxa_amostragem)
                )
                return nome, max(8000, taxa_padrao)
        except Exception:
            pass
        return None, self.taxa_amostragem

    def recarregar_dispositivos(self) -> bool:
        """Reinicializa a listagem de dispositivos PortAudio caso não esteja em gravação."""
        with self._trava:
            if self._esta_gravando:
                return False
            try:
                import sounddevice as sd

                if hasattr(sd, "_terminate") and hasattr(sd, "_initialize"):
                    sd._terminate()
                    sd._initialize()
                return True
            except Exception:
                return False

    def sondar_microfone(self) -> dict:
        """Valida disponibilidade e abertura real do stream de entrada sem travar gravações ativas."""
        status_permissao = obter_status_microfone_macos()
        if status_permissao in ("Denied", "Restricted"):
            return {
                "ok": False,
                "dispositivo_indice": None,
                "dispositivo_nome": None,
                "taxa_amostragem": None,
                "detalhe": f"Permissão de microfone bloqueada no macOS ({status_permissao})",
            }

        with self._trava:
            if self._esta_gravando:
                return {
                    "ok": True,
                    "dispositivo_indice": self._dispositivo_ativo_indice,
                    "dispositivo_nome": self._dispositivo_ativo_nome or "Microfone Ativo",
                    "taxa_amostragem": self._taxa_captura_ativa,
                    "detalhe": "Microfone ativo em gravação",
                }

        try:
            import sounddevice as sd

            indice = selecionar_dispositivo_entrada(recarregar=False)
            nome_dispositivo, taxa_padrao = self._obter_info_dispositivo(indice)

            taxas_tentativa = [self.taxa_amostragem]
            if taxa_padrao != self.taxa_amostragem:
                taxas_tentativa.append(taxa_padrao)

            ultimo_erro: Optional[Exception] = None
            for taxa_teste in taxas_tentativa:
                try:
                    fluxo_teste = sd.InputStream(
                        samplerate=taxa_teste,
                        channels=self.canais,
                        dtype=TIPO_AMOSTRA,
                        device=indice,
                    )
                    fluxo_teste.start()
                    fluxo_teste.stop()
                    fluxo_teste.close()
                    detalhe = (
                        f"Microfone pronto ({nome_dispositivo or 'Padrão'} @ {taxa_teste} Hz)"
                        if taxa_teste == self.taxa_amostragem
                        else f"Microfone pronto ({nome_dispositivo or 'Padrão'} @ {taxa_teste} Hz -> {self.taxa_amostragem} Hz)"
                    )
                    return {
                        "ok": True,
                        "dispositivo_indice": indice,
                        "dispositivo_nome": nome_dispositivo or "Microfone Padrão",
                        "taxa_amostragem": taxa_teste,
                        "detalhe": detalhe,
                    }
                except Exception as erro_tentativa:
                    ultimo_erro = erro_tentativa

            return {
                "ok": False,
                "dispositivo_indice": indice,
                "dispositivo_nome": nome_dispositivo,
                "taxa_amostragem": None,
                "detalhe": f"Falha ao abrir stream de entrada: {ultimo_erro}",
            }
        except Exception as erro:
            return {
                "ok": False,
                "dispositivo_indice": None,
                "dispositivo_nome": None,
                "taxa_amostragem": None,
                "detalhe": f"Erro no subsistema de áudio: {erro}",
            }

    def _retorno_audio(self, dados_entrada, quadros, info_tempo, status_fluxo) -> None:
        if status_fluxo:
            pass
        if not self._esta_gravando:
            return

        with self._trava:
            if not self._esta_gravando:
                return
            self._quadros.append(dados_entrada.copy())
            try:
                pico = float(np.max(np.abs(dados_entrada)))
                nivel_bruto = min(1.0, max(0.0, (pico - 120.0) / 3200.0))

                # Envelope com ataque rápido e decaimento exponencial suave
                if nivel_bruto > self.nivel_atual:
                    self.nivel_atual = (self.nivel_atual * 0.22) + (nivel_bruto * 0.78)
                else:
                    novo_nivel = (self.nivel_atual * 0.80) + (nivel_bruto * 0.20)
                    self.nivel_atual = 0.0 if novo_nivel < 0.002 else novo_nivel

                if pico >= LIMIAR_FALA_SILENCIO:
                    self._ultimo_instante_fala = time.time()
            except Exception:
                pass

    def _laco_supervisor(self) -> None:
        """Monitora fatiamento contínuo em segundo plano e parada automática por silêncio."""
        while not self._evento_parar_supervisor.wait(timeout=1.0):
            if not self._esta_gravando:
                break
            self._verificar_gravacao_fatia()
            self._verificar_parada_automatica()

    def _verificar_parada_automatica(self) -> None:
        """Aciona a parada automática caso o silêncio contínuo ultrapasse o limite configurado."""
        configuracoes = obter_configuracoes()
        limite_segundos = configuracoes.parada_silencio_segundos
        if not limite_segundos or limite_segundos <= 0:
            return
        if not self._esta_gravando:
            return
        if self.duracao_silencio >= limite_segundos:
            retorno_parada = self.ao_parar_automatico
            if retorno_parada is not None:
                try:
                    retorno_parada()
                except Exception:
                    pass
            else:
                try:
                    self.parar()
                except Exception:
                    pass

    def _verificar_gravacao_fatia(self) -> None:
        """Salva fatias periódicas em disco quando a gravação ultrapassa o limiar configurado."""
        configuracoes = obter_configuracoes()
        if not configuracoes.backup_fatias_ativo:
            return

        segundos_inicio = max(1, configuracoes.inicio_fatias_segundos or 40)
        segundos_fatia = max(1, configuracoes.duracao_fatia_segundos or 30)

        with self._trava:
            if not self._esta_gravando or not self._quadros:
                return

            taxa_captura = self._taxa_captura_ativa or self.taxa_amostragem
            limiar_inicio_amostras = int(segundos_inicio * taxa_captura)
            limiar_fatia_amostras = int(segundos_fatia * taxa_captura)

            total_amostras = sum(len(quadro) for quadro in self._quadros)
            amostras_pendentes = total_amostras - self._amostras_descarregadas

            if (
                total_amostras >= limiar_inicio_amostras
                and amostras_pendentes >= limiar_fatia_amostras
            ):
                audio_completo = np.concatenate(self._quadros, axis=0)
                fatia_bruta = audio_completo[
                    self._amostras_descarregadas : self._amostras_descarregadas
                    + limiar_fatia_amostras
                ]
                self._amostras_descarregadas += limiar_fatia_amostras
                indice_atual = self._indice_fatia
                self._indice_fatia += 1
                id_sessao = self._id_sessao or f"sessao_{int(time.time())}"
            else:
                return

        fatia_final = _reamostrar_audio(fatia_bruta, taxa_captura, self.taxa_amostragem)
        destino_fatia = _obter_diretorio_audios() / f"{id_sessao}_chunk_{indice_atual}.ogg"
        caminho_salvo = salvar_arquivo_audio(
            fatia_final, destino_fatia, self.taxa_amostragem
        )
        with self._trava:
            self._arquivos_fatias.append(caminho_salvo)

    def iniciar(self, id_sessao: Optional[str] = None) -> tuple[bool, str]:
        """Inicia a captura do microfone com suporte a contingência de taxa de amostragem."""
        with self._trava:
            if self._esta_gravando:
                return False, "Já está gravando"

            status_permissao = obter_status_microfone_macos()
            if status_permissao == "Denied":
                return (
                    False,
                    "Permissão de microfone negada no macOS (Ajustes do Sistema > Privacidade e Segurança > Microfone)",
                )
            if status_permissao == "Restricted":
                return False, "Permissão de microfone restrita no macOS"
            if status_permissao == "NotDetermined":
                solicitar_permissao_microfone_macos()

            self._quadros = []
            self._esta_gravando = True
            self._instante_inicio = time.time()
            self._id_sessao = id_sessao or f"rec_{int(time.time() * 1000)}"
            self._amostras_descarregadas = 0
            self._indice_fatia = 0
            self._arquivos_fatias = []
            self._ultimo_instante_fala = time.time()
            self.nivel_atual = 0.0
            self._evento_parar_supervisor.clear()

            try:
                import sounddevice as sd

                indice_dispositivo = selecionar_dispositivo_entrada(recarregar=False)
                nome_dispositivo, taxa_padrao = self._obter_info_dispositivo(
                    indice_dispositivo
                )

                taxas_candidatas = [self.taxa_amostragem]
                if taxa_padrao != self.taxa_amostragem:
                    taxas_candidatas.append(taxa_padrao)

                erro_abertura: Optional[Exception] = None
                fluxo_aberto = None
                taxa_escolhida = self.taxa_amostragem

                for taxa_tentativa in taxas_candidatas:
                    try:
                        fluxo_candidato = sd.InputStream(
                            samplerate=taxa_tentativa,
                            channels=self.canais,
                            dtype=TIPO_AMOSTRA,
                            device=indice_dispositivo,
                            callback=self._retorno_audio,
                        )
                        fluxo_candidato.start()
                        fluxo_aberto = fluxo_candidato
                        taxa_escolhida = taxa_tentativa
                        break
                    except Exception as erro_taxa:
                        erro_abertura = erro_taxa

                if fluxo_aberto is None:
                    raise RuntimeError(
                        erro_abertura or "Não foi possível abrir o stream de áudio"
                    )

                self._fluxo = fluxo_aberto
                self._taxa_captura_ativa = taxa_escolhida
                self._dispositivo_ativo_indice = indice_dispositivo
                self._dispositivo_ativo_nome = nome_dispositivo

                self._thread_supervisora = threading.Thread(
                    target=self._laco_supervisor, daemon=True
                )
                self._thread_supervisora.start()
                return True, "Gravação iniciada"
            except Exception as erro:
                self._esta_gravando = False
                self.nivel_atual = 0.0
                self._fluxo = None
                return False, f"Falha ao abrir dispositivo de áudio: {erro}"

    def parar(
        self,
        caminho_destino: Optional[Path] = None,
        limpar_fatias: bool = True,
    ) -> dict:
        """Encerra a gravação, consolida e reamostra o áudio para 16 kHz e limpa fatias temporárias."""
        self._evento_parar_supervisor.set()

        with self._trava:
            if not self._esta_gravando:
                self.nivel_atual = 0.0
                return {"ok": False, "reason": "Não estava gravando"}

            self._esta_gravando = False
            self.nivel_atual = 0.0
            duracao_ms = int((time.time() - self._instante_inicio) * 1000)
            taxa_captura = self._taxa_captura_ativa or self.taxa_amostragem
            id_sessao = self._id_sessao or f"rec_{int(time.time() * 1000)}"

            if self._fluxo is not None:
                try:
                    self._fluxo.stop()
                    self._fluxo.close()
                except Exception:
                    pass
                self._fluxo = None

            if not self._quadros:
                return {
                    "ok": False,
                    "duration_ms": duracao_ms,
                    "reason": "Nenhum quadro de áudio capturado",
                }

            dados_brutos = np.concatenate(self._quadros, axis=0)
            self._quadros = []
            fatias_gravadas = list(self._arquivos_fatias)

        dados_audio = _reamostrar_audio(dados_brutos, taxa_captura, self.taxa_amostragem)

        diretorio_audios = _obter_diretorio_audios()
        if caminho_destino is None:
            diretorio_audios.mkdir(parents=True, exist_ok=True)
            caminho_destino = diretorio_audios / f"{id_sessao}.ogg"
        else:
            caminho_destino = Path(caminho_destino)
            caminho_destino.parent.mkdir(parents=True, exist_ok=True)

        caminho_final = salvar_arquivo_audio(
            dados_audio, caminho_destino, self.taxa_amostragem
        )

        if (
            limpar_fatias
            and caminho_final.exists()
            and caminho_final.stat().st_size > 0
        ):
            for arquivo_fatia in fatias_gravadas:
                try:
                    arquivo_fatia.unlink(missing_ok=True)
                except Exception:
                    pass

        amplitude_maxima = (
            int(np.max(np.abs(dados_audio))) if len(dados_audio) > 0 else 0
        )
        amplitude_media = (
            float(np.mean(np.abs(dados_audio))) if len(dados_audio) > 0 else 0.0
        )

        return {
            "ok": True,
            "path": str(caminho_final),
            "duration_ms": duracao_ms,
            "samples": len(dados_audio),
            "max_amplitude": amplitude_maxima,
            "mean_amplitude": amplitude_media,
            "is_silent": amplitude_maxima < 150,
            "chunks_count": len(fatias_gravadas),
        }

    def cancelar(self, caminho_destino: Optional[Path] = None) -> dict:
        """
        Cancela a gravação em andamento preservando o áudio capturado em formato OGG
        para que permaneça acessível no menu de recuperação.
        """
        self._evento_parar_supervisor.set()

        with self._trava:
            if not self._esta_gravando:
                self.nivel_atual = 0.0
                return {
                    "ok": False,
                    "path": None,
                    "duration_ms": 0,
                    "samples": 0,
                    "reason": "Não estava gravando",
                }

            self._esta_gravando = False
            self.nivel_atual = 0.0
            duracao_ms = int((time.time() - self._instante_inicio) * 1000)
            taxa_captura = self._taxa_captura_ativa or self.taxa_amostragem
            id_sessao = self._id_sessao or f"cancelado_{int(time.time() * 1000)}"

            if self._fluxo is not None:
                try:
                    self._fluxo.stop()
                    self._fluxo.close()
                except Exception:
                    pass
                self._fluxo = None

            if not self._quadros:
                return {
                    "ok": False,
                    "path": None,
                    "duration_ms": 0,
                    "samples": 0,
                }

            dados_brutos = np.concatenate(self._quadros, axis=0)
            self._quadros = []
            fatias_gravadas = list(self._arquivos_fatias)

        dados_audio = _reamostrar_audio(dados_brutos, taxa_captura, self.taxa_amostragem)

        diretorio_audios = _obter_diretorio_audios()
        if caminho_destino is None:
            diretorio_audios.mkdir(parents=True, exist_ok=True)
            caminho_destino = diretorio_audios / f"{id_sessao}.ogg"
        else:
            caminho_destino = Path(caminho_destino)
            caminho_destino.parent.mkdir(parents=True, exist_ok=True)

        caminho_salvo = salvar_arquivo_audio(
            dados_audio, caminho_destino, self.taxa_amostragem
        )

        for arquivo_fatia in fatias_gravadas:
            try:
                arquivo_fatia.unlink(missing_ok=True)
            except Exception:
                pass

        return {
            "ok": True,
            "path": str(caminho_salvo),
            "duration_ms": duracao_ms,
            "samples": len(dados_audio),
        }

    def injetar_audio_sintetico(
        self, dados_audio: np.ndarray, caminho_destino: Path
    ) -> dict:
        """Persiste um vetor de áudio sintético em disco para validação e testes sem hardware."""
        caminho_salvo = salvar_arquivo_audio(
            dados_audio, Path(caminho_destino), self.taxa_amostragem
        )
        duracao_ms = int((len(dados_audio) / self.taxa_amostragem) * 1000)
        amplitude_maxima = (
            int(np.max(np.abs(dados_audio))) if len(dados_audio) > 0 else 0
        )
        amplitude_media = (
            float(np.mean(np.abs(dados_audio))) if len(dados_audio) > 0 else 0.0
        )

        return {
            "ok": True,
            "path": str(caminho_salvo),
            "duration_ms": duracao_ms,
            "samples": len(dados_audio),
            "max_amplitude": amplitude_maxima,
            "mean_amplitude": amplitude_media,
            "is_silent": amplitude_maxima < 150,
        }


gravador = GravadorAudio()
