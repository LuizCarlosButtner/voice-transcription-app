/**
 * Voice Transcription — Lógica do Painel de Controle Web
 * Código 100% em Português (PT-BR), integrado via eventos do servidor (/eventos) e API local.
 */

const BASE_API = "";

const MAPA_MODOS_ACIONAMENTO = {
  hibrido: {
    curto: "Híbrido",
    completo: "Híbrido (Segurar ou Toque Rápido)",
  },
  segurar: {
    curto: "Segurar",
    completo: "Segurar para Falar (Push-and-Hold)",
  },
  alternar: {
    curto: "Alternar",
    completo: "Toque para Alternar (Liga/Desliga)",
  },
};

const MAPA_SUBTITULOS_TOM = {
  verbatim: "Sem filtro, fiel às palavras originais",
  colloquial: "Natural, leve e fluido para conversas",
  semiformal: "Equilíbrio objetivo para o dia a dia",
  formal: "Registro culto, polido e executivo",
};

const ORDEM_ETAPAS_DIAGNOSTICO = [
  "armazenamento_banco",
  "chaves_provedores",
  "permissoes_macos",
  "subsistema_audio",
  "escutador_atalho",
];

// Estado centralizado do painel
const estadoPainel = {
  configuracoes: {},
  estatisticas: {},
  historico: [],
  filtroAtivo: "all",
  termoBusca: "",
  conectado: false,
  gravandoNoNavegador: false,
  processandoNoNavegador: false,
  estadoDaemon: {
    estado: "idle",
    detalhe: "",
    esta_gravando: false,
    esta_processando: false,
    modo_atual: "ocioso",
    nivel_voz: 0,
    escuta_ativa: false,
  },
  ultimaAssinaturaHistorico: "",
  renderizacaoHistoricoPendente: false,
};

// Captura de áudio no navegador
let gravadorMidia = null;
let pedacosAudio = [];
let tipoMimeGravado = "audio/webm";
let instanteInicioGravacao = 0;
let instanteInicioDaemon = 0;
let intervaloCronometro = null;
let contextoAudio = null;
let analisadorAudio = null;
let bufferDominioTempo = null;

// Eventos do servidor e motor gráfico 60fps do brilho difuso
let fonteEventosServidor = null;
let temporizadorReconexaoEventos = null;
let idQuadroAnimacao = null;
let nivelVisualSuavizado = 0;
let modoVisualCanvas = "idle";
let modoVisualAnteriorAtivo = "listening";
let instanteInicioDissolucao = 0;
let nivelCongeladoDissolucao = 0;
let estavaAtivoNoDaemon = false;

// Referências DOM — Cabeçalho e Métricas
const pilulaConexaoDaemon = document.getElementById("daemon-connection-pill");
const textoStatusDaemon = document.getElementById("daemon-status-text");
const pontoStatusDaemon = document.getElementById("daemon-status-dot");
const seloAtalhoAtivo = document.getElementById("active-hotkey-badge");
const rotuloModoCurtoTopo = document.getElementById("active-mode-short-label");
const botaoAtualizarTudo = document.getElementById("btn-refresh-all");

const metricaProvedor = document.getElementById("metric-provider");
const metricaProvedorSub = document.getElementById("metric-provider-sub");
const metricaTomAtivo = document.getElementById("metric-active-tone");
const metricaTomSub = document.getElementById("metric-tone-sub");
const seloPermissaoMic = document.getElementById("badge-perm-mic");
const seloPermissaoAx = document.getElementById("badge-perm-ax");
const seloPermissaoEntrada = document.getElementById("badge-perm-input");
const metricaAppFocado = document.getElementById("metric-front-app");
const metricaTotalSessoes = document.getElementById("metric-total-count");
const metricaDetalheSessoes = document.getElementById("metric-stats-detail");

// Referências DOM — Diagnóstico de Inicialização
const seloResumoDiagnostico = document.getElementById("diagnostico-resumo-badge");
const textoMetaDiagnostico = document.getElementById("diagnostico-meta-tempo");
const botaoExecutarAutoteste = document.getElementById("btn-executar-autoteste");

// Referências DOM — Estúdio e Gravação
const indicadorModoEstudio = document.getElementById("mode-indicator-badge");
const seletorModoEstudio = document.getElementById("seletor-modo-estudio");
const gradeTons = document.getElementById("tones-selector-grid");
const barraTraducao = document.getElementById("translation-feature-bar");
const alternadorTraducaoIngles = document.getElementById("toggle-translate-en");
const textoStatusTraducao = document.getElementById("translate-status-text");

const botaoMicrofonePrincipal = document.getElementById("btn-hero-mic");
const cronometroGravacao = document.getElementById("recording-timer");
const rotuloEstadoGravacao = document.getElementById("recording-state-label");
const canvasVisualizador = document.getElementById("visualizer-canvas");
const caixaResultadoAoVivo = document.getElementById("live-result-box");
const textoResultadoAoVivo = document.getElementById("live-result-text");
const conteinerAudioAoVivo = document.getElementById("live-result-audio-wrapper");
const botaoCopiarAoVivo = document.getElementById("btn-copy-live");
const botaoFecharAoVivo = document.getElementById("btn-close-live");

// Referências DOM — Abas e Histórico
const botoesAbas = document.querySelectorAll(".tab-btn");
const conteudosAbas = document.querySelectorAll(".tab-content");
const conteinerListaHistorico = document.getElementById("history-list-container");
const campoBuscaHistorico = document.getElementById("history-search-input");
const pilulasFiltro = document.querySelectorAll(".filter-pill");
const contadorAbaHistorico = document.getElementById("tab-history-count");

// Referências DOM — Formulário de Ajustes Completo
const formularioConfiguracoes = document.getElementById("form-configuracoes");
const radiosModoAcionamento = document.querySelectorAll('input[name="modo_acionamento"]');
const campoGramatica = document.getElementById("setting-grammar");
const campoAdicionarCursor = document.getElementById("setting-append");
const campoCacaCampo = document.getElementById("setting-auto-hunt");
const campoCliqueFoco = document.getElementById("setting-click-focus");
const campoMetodoInsercao = document.getElementById("setting-insertion-method");
const campoAutoinicio = document.getElementById("setting-autostart");
const campoBackupFatias = document.getElementById("setting-chunk-backup");
const campoInicioFatias = document.getElementById("setting-chunk-start");
const campoParadaSilencio = document.getElementById("setting-silence-stop");
const campoAtalho = document.getElementById("setting-hotkey");
const campoIdioma = document.getElementById("setting-language");
const campoModeloStt = document.getElementById("setting-stt-model");
const campoModeloLlm = document.getElementById("setting-llm-model");
const botaoSalvarAjustes = document.getElementById("btn-save-settings");
const botaoRestaurarAjustes = document.getElementById("btn-reset-settings");

const conteinerNotificacoes = document.getElementById("toast-container");

const suportaSeletorHas =
  typeof window.CSS !== "undefined" &&
  typeof window.CSS.supports === "function" &&
  window.CSS.supports("selector(:has(*))");

// ============================================================================
// Inicialização Principal
// ============================================================================
document.addEventListener("DOMContentLoaded", () => {
  configurarOuvintesEventos();
  redimensionarCanvasAltaDefinicao();
  iniciarMotorVisualizador60Fps();

  carregarStatus(false);
  carregarHistorico(false, true);
  conectarFluxoEventosTempoReal();

  window.addEventListener("resize", redimensionarCanvasAltaDefinicao);

  // Contingência de sincronização periódica suave caso o fluxo de eventos oscile ou novo histórico surja
  setInterval(() => {
    if (!estadoPainel.gravandoNoNavegador) {
      carregarStatus(true);
      carregarHistorico(true, false);
    }
  }, 4000);
});

function configurarOuvintesEventos() {
  if (botaoAtualizarTudo) {
    botaoAtualizarTudo.addEventListener("click", () => {
      carregarStatus(false);
      carregarHistorico(false, true);
      exibirNotificacao("Dados sincronizados com o serviço local.", "info");
    });
  }

  if (botaoExecutarAutoteste) {
    botaoExecutarAutoteste.addEventListener("click", executarAutotesteAgora);
  }

  // Navegação acessível entre abas (clique + setas do teclado)
  botoesAbas.forEach((botao, indice) => {
    botao.addEventListener("click", () => ativarAba(botao));
    botao.addEventListener("keydown", (evento) => {
      if (evento.key !== "ArrowRight" && evento.key !== "ArrowLeft") return;
      evento.preventDefault();
      const deslocamento = evento.key === "ArrowRight" ? 1 : -1;
      const proximoIndice = (indice + deslocamento + botoesAbas.length) % botoesAbas.length;
      const proximoBotao = botoesAbas[proximoIndice];
      ativarAba(proximoBotao);
      proximoBotao.focus();
    });
  });

  // Seletor rápido dos 3 modos de acionamento no Estúdio
  if (seletorModoEstudio) {
    seletorModoEstudio.addEventListener("click", (evento) => {
      const cartao = evento.target.closest(".cartao-modo-acionamento");
      if (!cartao) return;
      const modoEscolhido = cartao.dataset.modo;
      if (modoEscolhido) {
        atualizarModoAcionamentoRapido(modoEscolhido);
      }
    });
  }

  // Contingência de classe para rádios caso navegador antigo não suporte :has()
  radiosModoAcionamento.forEach((radio) => {
    radio.addEventListener("change", () => {
      sincronizarClassesContingenciaRadio();
    });
  });

  // Seletor de Tons
  if (gradeTons) {
    gradeTons.addEventListener("click", (evento) => {
      const cartaoTom = evento.target.closest(".tone-card");
      if (!cartaoTom) return;
      const tomEscolhido = cartaoTom.dataset.tone;
      if (tomEscolhido) {
        atualizarTomVoz(tomEscolhido);
      }
    });
  }

  // Alternador de Tradução PT -> EN
  if (alternadorTraducaoIngles) {
    alternadorTraducaoIngles.addEventListener("change", (evento) => {
      atualizarTraducaoIngles(Boolean(evento.target.checked));
    });
  }

  // Botão central do microfone (teste via navegador)
  if (botaoMicrofonePrincipal) {
    botaoMicrofonePrincipal.addEventListener("click", alternarGravacaoNavegador);
  }

  // Ações da caixa de resultado ao vivo
  if (botaoCopiarAoVivo) {
    botaoCopiarAoVivo.addEventListener("click", () => {
      const texto = textoResultadoAoVivo?.innerText?.trim();
      if (texto) {
        navigator.clipboard.writeText(texto);
        exibirNotificacao("Texto copiado para a área de transferência!", "sucesso");
      }
    });
  }

  if (botaoFecharAoVivo) {
    botaoFecharAoVivo.addEventListener("click", () => {
      if (caixaResultadoAoVivo) {
        caixaResultadoAoVivo.hidden = true;
      }
    });
  }

  // Busca no histórico com atraso de digitação
  let temporizadorBusca = null;
  if (campoBuscaHistorico) {
    campoBuscaHistorico.addEventListener("input", (evento) => {
      clearTimeout(temporizadorBusca);
      temporizadorBusca = setTimeout(() => {
        estadoPainel.termoBusca = evento.target.value.trim();
        renderizarListaHistorico(true);
      }, 220);
    });
  }

  // Pílulas de filtro do histórico
  pilulasFiltro.forEach((pilula) => {
    pilula.addEventListener("click", () => {
      pilulasFiltro.forEach((item) => item.classList.remove("active"));
      pilula.classList.add("active");
      estadoPainel.filtroAtivo = pilula.dataset.filter || "all";
      renderizarListaHistorico(true);
    });
  });

  // Delegação de eventos nos cartões do histórico (Copiar, Repetir, Excluir, Ver Bruto)
  if (conteinerListaHistorico) {
    conteinerListaHistorico.addEventListener("click", (evento) => {
      const botaoAcao = evento.target.closest("[data-acao]");
      if (!botaoAcao) return;
      const acao = botaoAcao.dataset.acao;
      const idRegistro = botaoAcao.dataset.id;

      if (acao === "recarregar-historico") {
        carregarHistorico(false, true);
        return;
      }
      if (!idRegistro) return;

      if (acao === "copiar") {
        copiarTextoCartao(idRegistro);
      } else if (acao === "repetir") {
        repetirTranscricao(idRegistro, botaoAcao);
      } else if (acao === "excluir") {
        excluirRegistroHistorico(idRegistro, botaoAcao);
      } else if (acao === "alternar-bruto") {
        alternarTextoBruto(idRegistro, botaoAcao);
      }
    });
  }

  // Formulário de Ajustes Completo
  if (formularioConfiguracoes) {
    formularioConfiguracoes.addEventListener("submit", salvarConfiguracoes);
  }
  if (botaoRestaurarAjustes) {
    botaoRestaurarAjustes.addEventListener("click", restaurarPadroes);
  }
}

function ativarAba(botaoSelecionado) {
  const idAlvo = botaoSelecionado.dataset.tab;
  botoesAbas.forEach((botao) => {
    const selecionado = botao === botaoSelecionado;
    botao.classList.toggle("active", selecionado);
    botao.setAttribute("aria-selected", selecionado ? "true" : "false");
    botao.tabIndex = selecionado ? 0 : -1;
  });

  conteudosAbas.forEach((painel) => {
    const ativo = painel.id === idAlvo;
    painel.classList.toggle("active", ativo);
    painel.hidden = !ativo;
  });
}

// ============================================================================
// Fluxo de Eventos do Servidor (/eventos) e Sincronização de Estado em Tempo Real
// ============================================================================
function conectarFluxoEventosTempoReal() {
  if (typeof window.EventSource === "undefined") return;

  if (fonteEventosServidor) {
    fonteEventosServidor.close();
    fonteEventosServidor = null;
  }

  try {
    fonteEventosServidor = new EventSource(`${BASE_API}/eventos`);

    fonteEventosServidor.onmessage = (evento) => {
      try {
        const dadosEvento = JSON.parse(evento.data);
        estadoPainel.conectado = true;
        aplicarEstadoTempoRealDaemon(dadosEvento);
      } catch {
        // Ignora pacotes parciais malformados
      }
    };

    fonteEventosServidor.onerror = () => {
      if (fonteEventosServidor) {
        fonteEventosServidor.close();
        fonteEventosServidor = null;
      }
      clearTimeout(temporizadorReconexaoEventos);
      temporizadorReconexaoEventos = setTimeout(conectarFluxoEventosTempoReal, 3500);
    };
  } catch {
    // Contingência em /status permanece ativa automaticamente
  }
}

function aplicarEstadoTempoRealDaemon(estadoRemoto) {
  if (!estadoRemoto || typeof estadoRemoto !== "object") return;

  estadoPainel.estadoDaemon = {
    ...estadoPainel.estadoDaemon,
    ...estadoRemoto,
  };

  // Se o usuário estiver gravando diretamente no navegador, prioriza a captura local
  if (estadoPainel.gravandoNoNavegador || estadoPainel.processandoNoNavegador) {
    return;
  }

  const gravandoMac = Boolean(
    estadoRemoto.esta_gravando || estadoRemoto.estado === "listening"
  );
  const processandoMac = Boolean(
    !gravandoMac &&
      (estadoRemoto.esta_processando || estadoRemoto.estado === "processing")
  );

  if (gravandoMac) {
    if (!estavaAtivoNoDaemon) {
      instanteInicioDaemon = Date.now();
      iniciarCronometroVisual(() => instanteInicioDaemon);
    }
    estavaAtivoNoDaemon = true;
    definirModoVisualizador("listening");

    botaoMicrofonePrincipal?.classList.add("recording");
    botaoMicrofonePrincipal?.classList.remove("processing");

    const descricaoModo =
      estadoRemoto.modo_atual === "alternado"
        ? "Modo Contínuo (Toque novamente para enviar)"
        : "Ouvindo pelo atalho do macOS...";
    atualizarRotuloEstadoGravacao(descricaoModo, "ouvindo");
    atualizarPilulaConexao("Ouvindo no macOS", "gravando");
  } else if (processandoMac) {
    estavaAtivoNoDaemon = true;
    pararCronometroVisual(false);
    definirModoVisualizador("processing");

    botaoMicrofonePrincipal?.classList.remove("recording");
    botaoMicrofonePrincipal?.classList.add("processing");
    atualizarRotuloEstadoGravacao("Transcrevendo e ajustando tom...", "processando");
    atualizarPilulaConexao("Processando...", "online");
  } else {
    if (estavaAtivoNoDaemon) {
      estavaAtivoNoDaemon = false;
      pararCronometroVisual(true);
      definirModoVisualizador("idle");
      botaoMicrofonePrincipal?.classList.remove("recording", "processing");
      atualizarRotuloEstadoGravacao("Pronto para ouvir", "ocioso");

      // Assim que uma gravação global pelo Option termina, atualiza histórico e métricas!
      carregarHistorico(true, false);
      carregarStatus(true);
    } else {
      definirModoVisualizador("idle");
      botaoMicrofonePrincipal?.classList.remove("recording", "processing");
    }

    const porta = estadoPainel.configuracoes.port || 8100;
    atualizarPilulaConexao(`Online (${porta})`, "online");
  }
}

function atualizarPilulaConexao(rotulo, estadoVisual) {
  if (textoStatusDaemon) {
    textoStatusDaemon.textContent = rotulo;
  }
  if (pontoStatusDaemon) {
    pontoStatusDaemon.className = "status-dot";
    if (estadoVisual === "gravando") {
      pontoStatusDaemon.classList.add("dot-recording");
    } else if (estadoVisual === "offline") {
      pontoStatusDaemon.classList.add("dot-offline");
    } else {
      pontoStatusDaemon.classList.add("dot-online");
    }
  }
}

function atualizarRotuloEstadoGravacao(mensagem, variante) {
  if (!rotuloEstadoGravacao) return;
  rotuloEstadoGravacao.textContent = mensagem;
  rotuloEstadoGravacao.className = "recording-state-label";
  if (variante === "ouvindo") {
    rotuloEstadoGravacao.classList.add("estado-ouvindo");
  } else if (variante === "processando") {
    rotuloEstadoGravacao.classList.add("estado-processando");
  }
}

// ============================================================================
// Chamadas REST à API Local
// ============================================================================
async function carregarStatus(emSegundoPlano = false) {
  try {
    const resposta = await fetch(`${BASE_API}/status`);
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const dados = await resposta.json();

    estadoPainel.configuracoes = dados;
    estadoPainel.estatisticas = dados.stats || {};
    estadoPainel.conectado = true;

    atualizarInterfaceStatus(dados);

    if (dados.daemon_state) {
      aplicarEstadoTempoRealDaemon(dados.daemon_state);
    }

    if (dados.startup_diagnostics) {
      renderizarPainelDiagnostico(dados.startup_diagnostics, dados.permissions);
    } else if (!emSegundoPlano) {
      carregarDiagnostico();
    }
  } catch (erro) {
    estadoPainel.conectado = false;
    atualizarPilulaConexao("Offline", "offline");
    if (!emSegundoPlano) {
      exibirNotificacao("Não foi possível conectar ao serviço local.", "erro");
    }
  }
}

async function carregarDiagnostico() {
  try {
    const resposta = await fetch(`${BASE_API}/diagnostico`);
    if (!resposta.ok) return;
    const relatorio = await resposta.json();
    renderizarPainelDiagnostico(relatorio, estadoPainel.configuracoes.permissions);
  } catch {
    // Silencioso caso servidor esteja reiniciando
  }
}

async function executarAutotesteAgora() {
  if (botaoExecutarAutoteste) {
    botaoExecutarAutoteste.disabled = true;
    botaoExecutarAutoteste.querySelector("span").textContent = "Executando autoteste...";
  }

  try {
    const resposta = await fetch(`${BASE_API}/diagnostico/executar`, {
      method: "POST",
    });
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const relatorio = await resposta.json();

    renderizarPainelDiagnostico(relatorio, estadoPainel.configuracoes.permissions);
    carregarStatus(true);
    carregarHistorico(true, false);

    if (relatorio.ok) {
      exibirNotificacao(
        `Autoteste concluído: todas as 5 etapas saudáveis (${relatorio.duracao_ms || 0}ms).`,
        "sucesso"
      );
    } else {
      exibirNotificacao(
        "Autoteste concluído com alertas. Verifique os cartões de saúde.",
        "alerta"
      );
    }
  } catch (erro) {
    exibirNotificacao(`Falha ao executar autoteste: ${erro.message}`, "erro");
  } finally {
    if (botaoExecutarAutoteste) {
      botaoExecutarAutoteste.disabled = false;
      botaoExecutarAutoteste.querySelector("span").textContent = "Executar Autoteste Agora";
    }
  }
}

async function carregarHistorico(emSegundoPlano = false, forcarRenderizacao = false) {
  try {
    const resposta = await fetch(`${BASE_API}/history?limit=100`);
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const dados = await resposta.json();

    estadoPainel.historico = dados.entries || [];
    if (contadorAbaHistorico) {
      contadorAbaHistorico.textContent = String(
        dados.count ?? estadoPainel.historico.length
      );
    }
    if (dados.stats) {
      estadoPainel.estatisticas = dados.stats;
      atualizarCartaoEstatisticas(dados.stats);
    }

    renderizarListaHistorico(forcarRenderizacao);
  } catch (erro) {
    if (!emSegundoPlano && conteinerListaHistorico) {
      conteinerListaHistorico.innerHTML = `
        <div class="empty-state">
          <p>Erro ao carregar histórico: ${escaparHtml(erro.message)}</p>
          <button type="button" class="btn btn-outline btn-sm" data-acao="recarregar-historico">Tentar Novamente</button>
        </div>
      `;
    }
  }
}

async function atualizarModoAcionamentoRapido(novoModo) {
  try {
    const resposta = await fetch(`${BASE_API}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modo_acionamento: novoModo }),
    });
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const atualizado = await resposta.json();

    estadoPainel.configuracoes = { ...estadoPainel.configuracoes, ...atualizado };
    sincronizarSeletoresModoAcionamento(atualizado.modo_acionamento || novoModo);

    const infoModo = MAPA_MODOS_ACIONAMENTO[atualizado.modo_acionamento || novoModo];
    exibirNotificacao(
      `Modo de acionamento alterado para: ${infoModo ? infoModo.completo : novoModo}`,
      "sucesso"
    );
  } catch (erro) {
    exibirNotificacao(`Falha ao atualizar modo: ${erro.message}`, "erro");
  }
}

async function atualizarTomVoz(chaveTom) {
  try {
    const resposta = await fetch(`${BASE_API}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tone: chaveTom }),
    });
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const atualizado = await resposta.json();

    const tomEfetivo = atualizado.tone || chaveTom;
    estadoPainel.configuracoes.tone = tomEfetivo;
    destacarCartaoTom(tomEfetivo);
    if (metricaTomAtivo) metricaTomAtivo.textContent = capitalizarTexto(tomEfetivo);
    if (metricaTomSub) {
      metricaTomSub.textContent = MAPA_SUBTITULOS_TOM[tomEfetivo] || "";
    }
    exibirNotificacao(`Tom ajustado para: ${capitalizarTexto(tomEfetivo)}`, "sucesso");
  } catch (erro) {
    exibirNotificacao(`Falha ao alterar tom: ${erro.message}`, "erro");
  }
}

async function atualizarTraducaoIngles(ativado) {
  try {
    const resposta = await fetch(`${BASE_API}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ translate_to_english: ativado }),
    });
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const atualizado = await resposta.json();

    const traducaoAtiva = Boolean(atualizado.translate_to_english);
    estadoPainel.configuracoes.translate_to_english = traducaoAtiva;
    sincronizarInterfaceTraducao(traducaoAtiva);

    exibirNotificacao(
      traducaoAtiva
        ? "Tradução PT ➔ EN ativada (fale em português, insira em inglês)."
        : "Tradução instantânea desativada.",
      "info"
    );
  } catch (erro) {
    exibirNotificacao(`Erro ao alterar tradução: ${erro.message}`, "erro");
  }
}

async function salvarConfiguracoes(evento) {
  if (evento) evento.preventDefault();

  const radioSelecionado = document.querySelector(
    'input[name="modo_acionamento"]:checked'
  );
  const modoSelecionado =
    radioSelecionado?.value || estadoPainel.configuracoes.modo_acionamento || "hibrido";

  const cargaConfiguracoes = {
    modo_acionamento: modoSelecionado,
    grammar_correction: Boolean(campoGramatica?.checked),
    append_at_cursor: Boolean(campoAdicionarCursor?.checked),
    auto_hunt_input: Boolean(campoCacaCampo?.checked),
    click_to_focus_input: Boolean(campoCliqueFoco?.checked),
    insertion_method: campoMetodoInsercao?.value || "clipboard_paste",
    auto_start_login: Boolean(campoAutoinicio?.checked),
    chunk_backup_enabled: Boolean(campoBackupFatias?.checked),
    chunk_start_seconds: Math.max(5, parseInt(campoInicioFatias?.value || "40", 10) || 40),
    silence_auto_stop_seconds: Math.max(
      5,
      parseInt(campoParadaSilencio?.value || "60", 10) || 60
    ),
    hotkey: campoAtalho?.value || "Alt",
    language: campoIdioma?.value || "pt",
    groq_stt_model:
      (campoModeloStt?.value || "").trim() || "whisper-large-v3-turbo",
    groq_llm_model: (campoModeloLlm?.value || "").trim() || "qwen/qwen3.8-27b",
  };

  if (botaoSalvarAjustes) botaoSalvarAjustes.disabled = true;

  try {
    const resposta = await fetch(`${BASE_API}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cargaConfiguracoes),
    });
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const dadosAtualizados = await resposta.json();

    estadoPainel.configuracoes = {
      ...estadoPainel.configuracoes,
      ...dadosAtualizados,
      autostart_installed: cargaConfiguracoes.auto_start_login,
    };
    atualizarInterfaceStatus(estadoPainel.configuracoes);
    exibirNotificacao("Todas as preferências foram salvas com sucesso!", "sucesso");
  } catch (erro) {
    exibirNotificacao(`Erro ao salvar preferências: ${erro.message}`, "erro");
  } finally {
    if (botaoSalvarAjustes) botaoSalvarAjustes.disabled = false;
  }
}

async function restaurarPadroes() {
  const padroesFabrica = {
    modo_acionamento: "hibrido",
    tone: "verbatim",
    translate_to_english: false,
    grammar_correction: true,
    append_at_cursor: true,
    auto_hunt_input: true,
    click_to_focus_input: true,
    insertion_method: "clipboard_paste",
    auto_start_login: true,
    chunk_backup_enabled: true,
    chunk_start_seconds: 40,
    silence_auto_stop_seconds: 60,
    hotkey: "Alt",
    language: "pt",
    groq_stt_model: "whisper-large-v3-turbo",
    groq_llm_model: "qwen/qwen3.8-27b",
  };

  try {
    const resposta = await fetch(`${BASE_API}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(padroesFabrica),
    });
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const dados = await resposta.json();

    estadoPainel.configuracoes = { ...estadoPainel.configuracoes, ...dados };
    atualizarInterfaceStatus(estadoPainel.configuracoes);
    exibirNotificacao("Preferências restauradas para a configuração padrão.", "info");
  } catch (erro) {
    exibirNotificacao(`Falha ao restaurar padrões: ${erro.message}`, "erro");
  }
}

async function repetirTranscricao(idRegistro, botaoElemento) {
  if (botaoElemento) {
    botaoElemento.disabled = true;
    botaoElemento.textContent = "Reprocessando...";
  }

  try {
    const resposta = await fetch(`${BASE_API}/retry/${encodeURIComponent(idRegistro)}`, {
      method: "POST",
    });
    const dados = await resposta.json();
    if (dados.ok) {
      exibirNotificacao("Áudio retranscrito com sucesso!", "sucesso");
      carregarHistorico(false, true);
      carregarStatus(true);
    } else {
      exibirNotificacao(`Falha ao repetir: ${dados.error || "Erro desconhecido"}`, "erro");
      if (botaoElemento) {
        botaoElemento.disabled = false;
        botaoElemento.textContent = "Repetir (Retry)";
      }
    }
  } catch (erro) {
    exibirNotificacao(`Erro ao chamar repetição: ${erro.message}`, "erro");
    if (botaoElemento) {
      botaoElemento.disabled = false;
      botaoElemento.textContent = "Repetir (Retry)";
    }
  }
}

async function excluirRegistroHistorico(idRegistro, botaoElemento) {
  if (botaoElemento) {
    botaoElemento.disabled = true;
  }

  const cartaoDom = conteinerListaHistorico?.querySelector(
    `.history-card[data-id="${CSS.escape(idRegistro)}"]`
  );
  if (cartaoDom) {
    cartaoDom.classList.add("removendo");
  }

  try {
    const resposta = await fetch(
      `${BASE_API}/history/${encodeURIComponent(idRegistro)}`,
      { method: "DELETE" }
    );
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);

    estadoPainel.historico = estadoPainel.historico.filter(
      (item) => item.id !== idRegistro
    );
    if (contadorAbaHistorico) {
      contadorAbaHistorico.textContent = String(estadoPainel.historico.length);
    }
    renderizarListaHistorico(true);
    carregarStatus(true);
    exibirNotificacao("Registro e áudio excluídos do histórico.", "info");
  } catch (erro) {
    if (cartaoDom) cartaoDom.classList.remove("removendo");
    if (botaoElemento) botaoElemento.disabled = false;
    exibirNotificacao(`Não foi possível excluir: ${erro.message}`, "erro");
  }
}

// ============================================================================
// Atualização de Interface, Diagnóstico e Histórico Inteligente
// ============================================================================
function atualizarInterfaceStatus(dados) {
  const porta = dados.port || 8100;
  if (!estavaAtivoNoDaemon) {
    atualizarPilulaConexao(`Online (${porta})`, "online");
  }

  const atalho = dados.hotkey || "Alt";
  if (seloAtalhoAtivo) {
    seloAtalhoAtivo.textContent = atalho === "Alt" ? "⌥ Option" : atalho;
  }

  // Modo de acionamento
  const modoAtivo = dados.modo_acionamento || (dados.toggle_mode ? "alternar" : "hibrido");
  sincronizarSeletoresModoAcionamento(modoAtivo);

  // Provedor e Modelos
  if (metricaProvedor) {
    const nomeProvedor = dados.active_provider || dados.provider || "groq";
    metricaProvedor.textContent =
      nomeProvedor === "groq" ? "Groq Cloud" : capitalizarTexto(nomeProvedor);
  }
  if (metricaProvedorSub) {
    metricaProvedorSub.textContent = dados.groq_stt_model || "whisper-large-v3-turbo";
  }

  // Tom ativo
  const tomAtual = dados.tone || "verbatim";
  if (metricaTomAtivo) metricaTomAtivo.textContent = capitalizarTexto(tomAtual);
  if (metricaTomSub) {
    metricaTomSub.textContent = MAPA_SUBTITULOS_TOM[tomAtual] || "";
  }
  destacarCartaoTom(tomAtual);

  // As 3 Permissões do macOS
  const permissoes = dados.permissions || {};
  const statusMicrofone = permissoes.microphone_status || "Authorized";
  const microfoneOk = statusMicrofone !== "Denied" && statusMicrofone !== "Restricted";
  if (seloPermissaoMic) {
    seloPermissaoMic.textContent = `Mic: ${microfoneOk ? "OK" : statusMicrofone}`;
    seloPermissaoMic.className = `badge ${microfoneOk ? "badge-success" : "badge-error"}`;
  }

  const acessibilidadeOk = Boolean(permissoes.accessibility_trusted);
  if (seloPermissaoAx) {
    seloPermissaoAx.textContent = `AX: ${acessibilidadeOk ? "Ativo" : "Pendente"}`;
    seloPermissaoAx.className = `badge ${acessibilidadeOk ? "badge-success" : "badge-warning"}`;
  }

  const entradaOk = permissoes.input_monitoring_trusted !== false;
  if (seloPermissaoEntrada) {
    seloPermissaoEntrada.textContent = `Entrada: ${entradaOk ? "OK" : "Pendente"}`;
    seloPermissaoEntrada.className = `badge ${entradaOk ? "badge-success" : "badge-warning"}`;
  }

  // Aplicativo em primeiro plano
  const nomeAppFocado = dados.frontmost_app?.name || "macOS";
  if (metricaAppFocado) {
    metricaAppFocado.textContent = `App em foco: ${nomeAppFocado}`;
  }

  // Estatísticas
  atualizarCartaoEstatisticas(dados.stats || {});

  // Controles do Formulário Completo de Ajustes (evita sobrescrever campo enquanto usuário digita nele)
  const elementoFocado = document.activeElement;

  if (campoGramatica) campoGramatica.checked = Boolean(dados.grammar_correction);
  if (campoAdicionarCursor) campoAdicionarCursor.checked = Boolean(dados.append_at_cursor);
  if (campoCacaCampo) campoCacaCampo.checked = dados.auto_hunt_input !== false;
  if (campoCliqueFoco) campoCliqueFoco.checked = dados.click_to_focus_input !== false;
  if (campoMetodoInsercao && elementoFocado !== campoMetodoInsercao) {
    campoMetodoInsercao.value = dados.insertion_method || "clipboard_paste";
  }
  if (campoAutoinicio) {
    const autoinicioAtivo =
      typeof dados.autostart_installed === "boolean"
        ? dados.autostart_installed
        : dados.auto_start_login !== false;
    campoAutoinicio.checked = autoinicioAtivo;
  }
  if (campoBackupFatias) {
    campoBackupFatias.checked = dados.chunk_backup_enabled !== false;
  }
  if (campoInicioFatias && elementoFocado !== campoInicioFatias) {
    campoInicioFatias.value = dados.chunk_start_seconds || 40;
  }
  if (campoParadaSilencio && elementoFocado !== campoParadaSilencio) {
    campoParadaSilencio.value = dados.silence_auto_stop_seconds || 60;
  }
  if (campoAtalho && elementoFocado !== campoAtalho) {
    campoAtalho.value = dados.hotkey || "Alt";
  }
  if (campoIdioma && elementoFocado !== campoIdioma) {
    campoIdioma.value = dados.language || "pt";
  }
  if (campoModeloStt && elementoFocado !== campoModeloStt) {
    campoModeloStt.value = dados.groq_stt_model || "whisper-large-v3-turbo";
  }
  if (campoModeloLlm && elementoFocado !== campoModeloLlm) {
    campoModeloLlm.value = dados.groq_llm_model || "qwen/qwen3.8-27b";
  }

  sincronizarInterfaceTraducao(Boolean(dados.translate_to_english));
}

function atualizarCartaoEstatisticas(estatisticas) {
  if (metricaTotalSessoes) {
    metricaTotalSessoes.textContent = String(estatisticas.total || 0);
  }
  if (metricaDetalheSessoes) {
    const sucessos = estatisticas.success ?? estatisticas.sent ?? 0;
    const erros = estatisticas.errors ?? 0;
    const mediaMs = estatisticas.avg_duration_ms ?? 0;
    metricaDetalheSessoes.textContent = `${sucessos} enviados · ${erros} erros (${mediaMs}ms méd.)`;
  }
}

function renderizarPainelDiagnostico(relatorio, permissoesContingencia = {}) {
  if (!relatorio || typeof relatorio !== "object") return;

  const etapas = relatorio.etapas || {};
  const tudoSaudavel = Boolean(relatorio.ok);

  if (seloResumoDiagnostico) {
    seloResumoDiagnostico.textContent = tudoSaudavel
      ? "5/5 Etapas Saudáveis"
      : "Atenção Necessária";
    seloResumoDiagnostico.className = `badge ${
      tudoSaudavel ? "badge-success" : "badge-warning"
    }`;
  }

  if (textoMetaDiagnostico) {
    const horario = relatorio.executado_em
      ? formatarHorarioLocal(relatorio.executado_em)
      : "agora";
    const duracao = relatorio.duracao_ms ?? 0;
    textoMetaDiagnostico.textContent = `Última verificação às ${horario} (${duracao}ms).`;
  }

  ORDEM_ETAPAS_DIAGNOSTICO.forEach((chaveEtapa) => {
    const elementoEtapa = document.getElementById(`etapa-${chaveEtapa}`);
    if (!elementoEtapa) return;

    const dadosEtapa = etapas[chaveEtapa] || {};
    const etapaOk = Boolean(dadosEtapa.ok);
    const paragrafoDetalhe = elementoEtapa.querySelector(".etapa-detalhe");

    elementoEtapa.classList.remove("saude-ok", "saude-alerta", "saude-falha");
    elementoEtapa.classList.add(etapaOk ? "saude-ok" : "saude-falha");

    let resumoLegivel = dadosEtapa.detalhe || "";

    if (chaveEtapa === "armazenamento_banco") {
      const orfas = dadosEtapa.sessoes_orfas_recuperadas ?? 0;
      const integridade = dadosEtapa.integridade_banco || "ok";
      resumoLegivel = etapaOk
        ? `SQLite íntegro (${integridade}) · ${orfas} órfã(s) recuperada(s)`
        : dadosEtapa.detalhe || "Falha ao verificar banco SQLite";
    } else if (chaveEtapa === "chaves_provedores") {
      const textoGroq = dadosEtapa.groq_configurado ? "Groq OK" : "Sem chave Groq";
      const textoOgg = dadosEtapa.ogg_disponivel ? "OGG ativo" : "Contingência WAV";
      const textoSenseVoice = dadosEtapa.sensevoice_disponivel
        ? "SenseVoice pronto"
        : "SenseVoice ausente";
      resumoLegivel = `${textoGroq} · ${textoOgg} · ${textoSenseVoice}`;
    } else if (chaveEtapa === "permissoes_macos") {
      const microfone =
        dadosEtapa.microfone_status ||
        permissoesContingencia?.microphone_status ||
        "OK";
      const acessibilidade =
        dadosEtapa.acessibilidade_ativa ??
        permissoesContingencia?.accessibility_trusted;
      const entrada =
        dadosEtapa.monitoramento_entrada_ativo ??
        permissoesContingencia?.input_monitoring_trusted;
      resumoLegivel = `Mic: ${microfone} · AX: ${acessibilidade ? "OK" : "Pendente"} · Entrada: ${
        entrada ? "OK" : "Pendente"
      }`;
      if (!etapaOk && dadosEtapa.microfone_ok !== false) {
        elementoEtapa.classList.replace("saude-falha", "saude-alerta");
      }
    } else if (chaveEtapa === "subsistema_audio") {
      if (dadosEtapa.dispositivo_nome) {
        const khz = dadosEtapa.taxa_amostragem
          ? ` (${Math.round(Number(dadosEtapa.taxa_amostragem) / 1000)} kHz)`
          : "";
        resumoLegivel = `${dadosEtapa.dispositivo_nome}${khz}`;
      } else {
        resumoLegivel = dadosEtapa.detalhe || "Microfone indisponível";
      }
    } else if (chaveEtapa === "escutador_atalho") {
      const textoAtalho = dadosEtapa.atalho || "Alt";
      const textoModo =
        MAPA_MODOS_ACIONAMENTO[dadosEtapa.modo_acionamento]?.curto ||
        dadosEtapa.modo_acionamento ||
        "Híbrido";
      resumoLegivel = dadosEtapa.escuta_ativa
        ? `Escutador único ativo (${textoAtalho} · ${textoModo})`
        : dadosEtapa.detalhe || `Aguardando escuta (${textoAtalho})`;
    }

    if (paragrafoDetalhe) {
      paragrafoDetalhe.textContent = resumoLegivel;
    }
  });
}

function sincronizarSeletoresModoAcionamento(chaveModo) {
  const modoNormalizado = MAPA_MODOS_ACIONAMENTO[chaveModo] ? chaveModo : "hibrido";
  const infoModo = MAPA_MODOS_ACIONAMENTO[modoNormalizado];

  if (indicadorModoEstudio) {
    indicadorModoEstudio.innerHTML = `Modo ativo: <strong>${escaparHtml(
      infoModo.completo
    )}</strong>`;
  }
  if (rotuloModoCurtoTopo) {
    rotuloModoCurtoTopo.textContent = infoModo.curto;
  }

  // Botões em destaque no Estúdio
  if (seletorModoEstudio) {
    const cartoes = seletorModoEstudio.querySelectorAll(".cartao-modo-acionamento");
    cartoes.forEach((cartao) => {
      const ativo = cartao.dataset.modo === modoNormalizado;
      cartao.classList.toggle("ativo", ativo);
      cartao.setAttribute("aria-pressed", ativo ? "true" : "false");
    });
  }

  // Rádios na aba de Ajustes
  radiosModoAcionamento.forEach((radio) => {
    radio.checked = radio.value === modoNormalizado;
  });
  sincronizarClassesContingenciaRadio();
}

function sincronizarClassesContingenciaRadio() {
  if (suportaSeletorHas) return;
  radiosModoAcionamento.forEach((radio) => {
    const cartaoPai = radio.closest(".opcao-radio-card");
    if (cartaoPai) {
      cartaoPai.classList.toggle("selecionado", radio.checked);
    }
  });
}

function destacarCartaoTom(chaveTom) {
  const cartoes = document.querySelectorAll(".tone-card");
  cartoes.forEach((cartao) => {
    const ativo = cartao.dataset.tone === chaveTom;
    cartao.classList.toggle("active", ativo);
    cartao.setAttribute("aria-pressed", ativo ? "true" : "false");
  });
}

function sincronizarInterfaceTraducao(ativado) {
  if (alternadorTraducaoIngles) {
    alternadorTraducaoIngles.checked = Boolean(ativado);
  }
  if (textoStatusTraducao) {
    textoStatusTraducao.textContent = ativado ? "ATIVADO (PT ➔ EN)" : "Desativado";
    textoStatusTraducao.classList.toggle("active", Boolean(ativado));
  }
  if (!suportaSeletorHas && barraTraducao) {
    barraTraducao.classList.toggle("active", Boolean(ativado));
  }
}

// ============================================================================
// Histórico Sem Interromper Reprodução de Áudio
// ============================================================================
function existeAudioTocandoNoHistorico() {
  if (!conteinerListaHistorico) return false;
  const reprodutoresAudio = conteinerListaHistorico.querySelectorAll("audio");
  for (const reprodutor of reprodutoresAudio) {
    if (!reprodutor.paused && !reprodutor.ended) {
      return true;
    }
  }
  return false;
}

function calcularAssinaturaHistorico(itensFiltrados) {
  const cabecalhoFiltro = `${estadoPainel.filtroAtivo}::${estadoPainel.termoBusca}::`;
  const corpoAssinatura = itensFiltrados
    .map(
      (item) =>
        `${item.id}|${item.status}|${item.text_final || ""}|${
          item.error_message || ""
        }`
    )
    .join(";;");
  return cabecalhoFiltro + corpoAssinatura;
}

function renderizarListaHistorico(forcarRenderizacao = false) {
  if (!conteinerListaHistorico) return;

  // Nunca substitui innerHTML em segundo plano enquanto houver um <audio> tocando!
  if (!forcarRenderizacao && existeAudioTocandoNoHistorico()) {
    if (!estadoPainel.renderizacaoHistoricoPendente) {
      estadoPainel.renderizacaoHistoricoPendente = true;
      const reprodutoresAtivos = conteinerListaHistorico.querySelectorAll("audio");
      reprodutoresAtivos.forEach((reprodutor) => {
        if (!reprodutor.paused && !reprodutor.ended) {
          const aoPausarOuTerminar = () => {
            if (!existeAudioTocandoNoHistorico() && estadoPainel.renderizacaoHistoricoPendente) {
              estadoPainel.renderizacaoHistoricoPendente = false;
              renderizarListaHistorico(true);
            }
          };
          reprodutor.addEventListener("ended", aoPausarOuTerminar, { once: true });
          reprodutor.addEventListener("pause", aoPausarOuTerminar, { once: true });
        }
      });
    }
    return;
  }

  let itens = [...estadoPainel.historico];

  if (estadoPainel.filtroAtivo !== "all") {
    itens = itens.filter((registro) => registro.status === estadoPainel.filtroAtivo);
  }

  if (estadoPainel.termoBusca) {
    const buscaMinuscula = estadoPainel.termoBusca.toLowerCase();
    itens = itens.filter(
      (registro) =>
        (registro.text_final &&
          registro.text_final.toLowerCase().includes(buscaMinuscula)) ||
        (registro.text_raw &&
          registro.text_raw.toLowerCase().includes(buscaMinuscula)) ||
        (registro.active_app &&
          registro.active_app.toLowerCase().includes(buscaMinuscula))
    );
  }

  const assinaturaAtual = calcularAssinaturaHistorico(itens);
  if (
    !forcarRenderizacao &&
    assinaturaAtual === estadoPainel.ultimaAssinaturaHistorico
  ) {
    return;
  }
  estadoPainel.ultimaAssinaturaHistorico = assinaturaAtual;
  estadoPainel.renderizacaoHistoricoPendente = false;

  if (itens.length === 0) {
    conteinerListaHistorico.innerHTML = `
      <div class="empty-state">
        <p><strong>Nenhuma sessão encontrada</strong> para o filtro selecionado.</p>
        <p class="subtitle">Pressione ⌥ Option em qualquer janela do macOS ou use o microfone do Estúdio acima.</p>
      </div>
    `;
    return;
  }

  conteinerListaHistorico.innerHTML = itens
    .map((registro) => montarCartaoHistorico(registro))
    .join("");
}

function montarCartaoHistorico(registro) {
  const seloStatus = obterSeloStatus(registro.status);
  const horarioFormatado = formatarHorarioLocal(registro.created_at);
  const duracaoSegundos = registro.duration_ms
    ? `${(registro.duration_ms / 1000).toFixed(1)}s`
    : "0.0s";
  const nomeAplicativo = registro.active_app || "macOS";
  const rotuloTom = capitalizarTexto(registro.tone || "verbatim");
  const rotuloProvedor = capitalizarTexto(registro.provider || "groq");

  const ehErro = registro.status === "error";
  const permiteRepetir =
    ehErro ||
    registro.status === "partial" ||
    registro.status === "cancelled" ||
    registro.status === "written_not_sent";

  const possuiDiferencaBruto = Boolean(
    registro.text_raw &&
      registro.text_final &&
      registro.text_raw.trim() !== registro.text_final.trim()
  );

  const idSeguro = escaparHtml(registro.id);

  return `
    <article class="history-card" data-id="${idSeguro}">
      <div class="history-card-header">
        <div class="history-meta">
          ${seloStatus}
          <span title="${escaparHtml(registro.created_at || "")}">${horarioFormatado}</span>
          <span class="meta-separador" aria-hidden="true">·</span>
          <span><strong>${escaparHtml(nomeAplicativo)}</strong></span>
          <span class="meta-separador" aria-hidden="true">·</span>
          <span>${duracaoSegundos}</span>
          <span class="badge badge-version">${escaparHtml(rotuloTom)}</span>
          <span class="badge badge-neutral">${escaparHtml(rotuloProvedor)}</span>
        </div>

        <div class="history-actions">
          ${
            registro.text_final
              ? `<button type="button" class="btn btn-sm btn-outline" data-acao="copiar" data-id="${idSeguro}">Copiar</button>`
              : ""
          }
          ${
            permiteRepetir
              ? `<button type="button" class="btn btn-sm btn-primary" data-acao="repetir" data-id="${idSeguro}">Repetir (Retry)</button>`
              : ""
          }
          <button type="button" class="btn btn-sm btn-danger-ghost" data-acao="excluir" data-id="${idSeguro}" aria-label="Excluir registro do histórico">Excluir</button>
        </div>
      </div>

      <div class="history-content">
        ${
          ehErro
            ? `
              <div class="error-banner">
                <div>
                  <strong>Falha na transcrição:</strong> ${escaparHtml(
                    registro.error_message || "Erro desconhecido"
                  )}
                </div>
                <span>Áudio preservado para reprocessamento</span>
              </div>
            `
            : `
              <div class="text-final-box" id="texto-final-${idSeguro}">${escaparHtml(
                registro.text_final || "(Sem fala detectada)"
              )}</div>
            `
        }

        ${
          possuiDiferencaBruto
            ? `
              <button type="button" class="raw-toggle-btn" data-acao="alternar-bruto" data-id="${idSeguro}" aria-expanded="false">
                ▶ Ver transcrição bruta original (sem ajuste de tom)
              </button>
              <div class="text-raw-box" id="texto-bruto-${idSeguro}" hidden>${escaparHtml(
                registro.text_raw
              )}</div>
            `
            : ""
        }

        <div class="audio-player-wrapper">
          <audio controls preload="none" src="${BASE_API}/audio/${encodeURIComponent(
            registro.id
          )}"></audio>
        </div>
      </div>
    </article>
  `;
}

function copiarTextoCartao(idRegistro) {
  const elementoTexto = document.getElementById(`texto-final-${idRegistro}`);
  if (elementoTexto) {
    navigator.clipboard.writeText(elementoTexto.innerText.trim());
    exibirNotificacao("Texto copiado para a área de transferência!", "sucesso");
  }
}

function alternarTextoBruto(idRegistro, botaoGatilho) {
  const caixaBruta = document.getElementById(`texto-bruto-${idRegistro}`);
  if (!caixaBruta) return;
  const vaiMostrar = caixaBruta.hidden;
  caixaBruta.hidden = !vaiMostrar;
  if (botaoGatilho) {
    botaoGatilho.setAttribute("aria-expanded", vaiMostrar ? "true" : "false");
    botaoGatilho.textContent = vaiMostrar
      ? "▼ Ocultar transcrição bruta original"
      : "▶ Ver transcrição bruta original (sem ajuste de tom)";
  }
}

// ============================================================================
// Gravação pelo Navegador com Codificação WAV PCM 16-bit Real / MIME Real
// ============================================================================
function escolherTipoMimeSuportado() {
  if (typeof window.MediaRecorder === "undefined") return "";
  const candidatos = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/mp4",
  ];
  for (const tipo of candidatos) {
    if (
      typeof MediaRecorder.isTypeSupported === "function" &&
      MediaRecorder.isTypeSupported(tipo)
    ) {
      return tipo;
    }
  }
  return "";
}

async function alternarGravacaoNavegador() {
  if (estadoPainel.gravandoNoNavegador) {
    pararGravacaoNavegador();
  } else {
    await iniciarGravacaoNavegador();
  }
}

async function iniciarGravacaoNavegador() {
  try {
    const fluxoMicrofone = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    pedacosAudio = [];
    estadoPainel.gravandoNoNavegador = true;

    const mimePreferido = escolherTipoMimeSuportado();
    gravadorMidia = mimePreferido
      ? new MediaRecorder(fluxoMicrofone, { mimeType: mimePreferido })
      : new MediaRecorder(fluxoMicrofone);

    tipoMimeGravado = gravadorMidia.mimeType || mimePreferido || "audio/webm";

    gravadorMidia.ondataavailable = (evento) => {
      if (evento.data && evento.data.size > 0) {
        pedacosAudio.push(evento.data);
      }
    };

    gravadorMidia.onstop = processarAudioGravadoNoNavegador;
    gravadorMidia.start();

    conectarAnalisadorMicrofoneLocal(fluxoMicrofone);
    definirModoVisualizador("listening");

    botaoMicrofonePrincipal?.classList.add("recording");
    botaoMicrofonePrincipal?.setAttribute("aria-pressed", "true");
    atualizarRotuloEstadoGravacao(
      "Ouvindo no navegador... Clique novamente para encerrar",
      "ouvindo"
    );

    instanteInicioGravacao = Date.now();
    iniciarCronometroVisual(() => instanteInicioGravacao);
  } catch (erro) {
    exibirNotificacao(
      `Não foi possível acessar o microfone no navegador: ${erro.message}`,
      "erro"
    );
  }
}

function pararGravacaoNavegador() {
  if (gravadorMidia && estadoPainel.gravandoNoNavegador) {
    gravadorMidia.stop();
    gravadorMidia.stream.getTracks().forEach((trilha) => trilha.stop());
  }

  estadoPainel.gravandoNoNavegador = false;
  estadoPainel.processandoNoNavegador = true;
  analisadorAudio = null;

  botaoMicrofonePrincipal?.classList.remove("recording");
  botaoMicrofonePrincipal?.classList.add("processing");
  botaoMicrofonePrincipal?.setAttribute("aria-pressed", "false");
  atualizarRotuloEstadoGravacao("Codificando áudio e transcrevendo...", "processando");

  pararCronometroVisual(false);
  definirModoVisualizador("processing");
}

async function processarAudioGravadoNoNavegador() {
  const mimeRecipienteReal = (tipoMimeGravado || "audio/webm").split(";")[0].trim();
  const blobBruto = new Blob(pedacosAudio, { type: mimeRecipienteReal });

  try {
    // Codifica para WAV PCM 16-bit 16kHz genuíno; se falhar, envia o MIME real (nunca finge WAV!)
    const midiaPreparada = await converterBlobParaWavPcm16(
      blobBruto,
      mimeRecipienteReal
    );
    const audioBase64 = await converterBlobParaBase64(midiaPreparada.blob);

    const resposta = await fetch(`${BASE_API}/transcribe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dataBase64: audioBase64,
        mimeType: midiaPreparada.tipoMime,
        language: estadoPainel.configuracoes.language || "pt",
        tone: estadoPainel.configuracoes.tone || "verbatim",
      }),
    });

    const dados = await resposta.json();
    if (dados.ok) {
      exibirNotificacao("Transcrição concluída com sucesso!", "sucesso");
      if (textoResultadoAoVivo) {
        textoResultadoAoVivo.textContent =
          dados.text_final || "(Sem fala detectada)";
      }
      if (conteinerAudioAoVivo && dados.entry_id) {
        conteinerAudioAoVivo.innerHTML = `
          <audio controls src="${BASE_API}/audio/${encodeURIComponent(
            dados.entry_id
          )}"></audio>
        `;
      }
      if (caixaResultadoAoVivo) {
        caixaResultadoAoVivo.hidden = false;
      }

      carregarHistorico(false, true);
      carregarStatus(true);
    } else {
      exibirNotificacao(
        `Falha na transcrição: ${dados.error || "Erro desconhecido"}`,
        "erro"
      );
    }
  } catch (erro) {
    exibirNotificacao(`Erro ao enviar áudio: ${erro.message}`, "erro");
  } finally {
    estadoPainel.processandoNoNavegador = false;
    botaoMicrofonePrincipal?.classList.remove("processing", "recording");
    atualizarRotuloEstadoGravacao("Pronto para ouvir", "ocioso");
    pararCronometroVisual(true);
    definirModoVisualizador("idle");
  }
}

async function converterBlobParaWavPcm16(blobOriginal, tipoMimeOriginal) {
  try {
    const ConstrutorContexto = window.AudioContext || window.webkitAudioContext;
    if (!ConstrutorContexto) {
      return { blob: blobOriginal, tipoMime: tipoMimeOriginal };
    }

    const bytesOriginais = await blobOriginal.arrayBuffer();
    const contextoDecodificacao = new ConstrutorContexto();
    let bufferDecodificado;
    try {
      bufferDecodificado = await contextoDecodificacao.decodeAudioData(
        bytesOriginais.slice(0)
      );
    } finally {
      await contextoDecodificacao.close().catch(() => {});
    }

    const taxaAlvo = 16000;
    const totalAmostrasAlvo = Math.max(
      1,
      Math.ceil(bufferDecodificado.duration * taxaAlvo)
    );

    let amostrasMono;
    if (typeof window.OfflineAudioContext !== "undefined") {
      const contextoOffline = new OfflineAudioContext(
        1,
        totalAmostrasAlvo,
        taxaAlvo
      );
      const fonteBuffer = contextoOffline.createBufferSource();
      fonteBuffer.buffer = bufferDecodificado;
      fonteBuffer.connect(contextoOffline.destination);
      fonteBuffer.start(0);
      const bufferReamostrado = await contextoOffline.startRendering();
      amostrasMono = bufferReamostrado.getChannelData(0);
    } else {
      amostrasMono = bufferDecodificado.getChannelData(0);
    }

    const taxaEfetiva =
      typeof window.OfflineAudioContext !== "undefined"
        ? taxaAlvo
        : bufferDecodificado.sampleRate;

    const blobWav = codificarAmostrasParaWavPcm16(amostrasMono, taxaEfetiva);
    return { blob: blobWav, tipoMime: "audio/wav" };
  } catch {
    return { blob: blobOriginal, tipoMime: tipoMimeOriginal || "audio/webm" };
  }
}

function codificarAmostrasParaWavPcm16(amostrasFloat32, taxaAmostragem) {
  const bytesDados = amostrasFloat32.length * 2;
  const bufferFinal = new ArrayBuffer(44 + bytesDados);
  const visao = new DataView(bufferFinal);

  const escreverAscii = (posicao, texto) => {
    for (let i = 0; i < texto.length; i += 1) {
      visao.setUint8(posicao + i, texto.charCodeAt(i));
    }
  };

  escreverAscii(0, "RIFF");
  visao.setUint32(4, 36 + bytesDados, true);
  escreverAscii(8, "WAVE");
  escreverAscii(12, "fmt ");
  visao.setUint32(16, 16, true); // Tamanho do bloco fmt PCM (16 bytes)
  visao.setUint16(20, 1, true); // Formato PCM = 1
  visao.setUint16(22, 1, true); // Mono = 1 canal
  visao.setUint32(24, taxaAmostragem, true);
  visao.setUint32(28, taxaAmostragem * 2, true); // Taxa de bytes por segundo
  visao.setUint16(32, 2, true); // Alinhamento de bloco (2 bytes)
  visao.setUint16(34, 16, true); // Bits por amostra = 16
  escreverAscii(36, "data");
  visao.setUint32(40, bytesDados, true);

  let deslocamento = 44;
  for (let i = 0; i < amostrasFloat32.length; i += 1) {
    const amostraLimitada = Math.max(-1, Math.min(1, amostrasFloat32[i]));
    const inteiro16 =
      amostraLimitada < 0
        ? amostraLimitada * 0x8000
        : amostraLimitada * 0x7fff;
    visao.setInt16(deslocamento, inteiro16, true);
    deslocamento += 2;
  }

  return new Blob([bufferFinal], { type: "audio/wav" });
}

function converterBlobParaBase64(blobAudio) {
  return new Promise((resolver, rejeitar) => {
    const leitor = new FileReader();
    leitor.onloadend = () => {
      const resultado = String(leitor.result || "");
      const parteBase64 = resultado.includes(",")
        ? resultado.split(",")[1]
        : resultado;
      resolver(parteBase64);
    };
    leitor.onerror = () => rejeitar(new Error("Falha ao ler blob de áudio"));
    leitor.readAsDataURL(blobAudio);
  });
}

function iniciarCronometroVisual(obterInstanteBase) {
  clearInterval(intervaloCronometro);
  if (cronometroGravacao) cronometroGravacao.textContent = "00:00";

  intervaloCronometro = setInterval(() => {
    const segundosDecorridos = Math.max(
      0,
      Math.floor((Date.now() - obterInstanteBase()) / 1000)
    );
    const minutos = String(Math.floor(segundosDecorridos / 60)).padStart(2, "0");
    const segundos = String(segundosDecorridos % 60).padStart(2, "0");
    if (cronometroGravacao) {
      cronometroGravacao.textContent = `${minutos}:${segundos}`;
    }
  }, 350);
}

function pararCronometroVisual(zerarMostrador) {
  clearInterval(intervaloCronometro);
  intervaloCronometro = null;
  if (zerarMostrador && cronometroGravacao) {
    cronometroGravacao.textContent = "00:00";
  }
}

// ============================================================================
// Visualizador 60fps de Brilho Vermelho Difuso (<canvas id="visualizer-canvas">)
// ============================================================================
function conectarAnalisadorMicrofoneLocal(fluxoAudio) {
  const ConstrutorContexto = window.AudioContext || window.webkitAudioContext;
  if (!ConstrutorContexto) return;

  if (!contextoAudio || contextoAudio.state === "closed") {
    contextoAudio = new ConstrutorContexto();
  }
  if (contextoAudio.state === "suspended") {
    contextoAudio.resume().catch(() => {});
  }

  const fonteFluxo = contextoAudio.createMediaStreamSource(fluxoAudio);
  analisadorAudio = contextoAudio.createAnalyser();
  analisadorAudio.fftSize = 256;
  analisadorAudio.smoothingTimeConstant = 0.75;
  fonteFluxo.connect(analisadorAudio);
  bufferDominioTempo = new Uint8Array(analisadorAudio.fftSize);
}

function lerNivelVozInstantaneo() {
  if (estadoPainel.gravandoNoNavegador && analisadorAudio && bufferDominioTempo) {
    analisadorAudio.getByteTimeDomainData(bufferDominioTempo);
    let somaQuadrados = 0;
    for (let i = 0; i < bufferDominioTempo.length; i += 1) {
      const normalizado = (bufferDominioTempo[i] - 128) / 128;
      somaQuadrados += normalizado * normalizado;
    }
    const raizMediaQuadratica = Math.sqrt(somaQuadrados / bufferDominioTempo.length);
    return Math.min(1, Math.pow(Math.min(1, raizMediaQuadratica * 4.2), 0.72));
  }

  const nivelDaemon = Number(estadoPainel.estadoDaemon?.nivel_voz || 0);
  return Math.min(1, Math.pow(Math.min(1, Math.max(0, nivelDaemon) * 3.4), 0.72));
}

function definirModoVisualizador(novoModo) {
  if (novoModo === modoVisualCanvas) return;

  if (novoModo === "listening" || novoModo === "processing") {
    modoVisualCanvas = novoModo;
    modoVisualAnteriorAtivo = novoModo;
    return;
  }

  if (
    novoModo === "idle" &&
    (modoVisualCanvas === "listening" || modoVisualCanvas === "processing")
  ) {
    modoVisualCanvas = "esvaindo";
    instanteInicioDissolucao = performance.now();
    nivelCongeladoDissolucao = nivelVisualSuavizado;
    return;
  }

  if (modoVisualCanvas !== "esvaindo") {
    modoVisualCanvas = "idle";
  }
}

function redimensionarCanvasAltaDefinicao() {
  if (!canvasVisualizador) return;
  const proporcaoPixels = Math.min(window.devicePixelRatio || 1, 2);
  const tamanhoLogico = 320;
  canvasVisualizador.width = tamanhoLogico * proporcaoPixels;
  canvasVisualizador.height = tamanhoLogico * proporcaoPixels;
}

function iniciarMotorVisualizador60Fps() {
  if (!canvasVisualizador) return;
  cancelAnimationFrame(idQuadroAnimacao);

  const lacoQuadro = (instanteMs) => {
    idQuadroAnimacao = requestAnimationFrame(lacoQuadro);
    desenharQuadroBrilhoDifuso(instanteMs);
  };

  idQuadroAnimacao = requestAnimationFrame(lacoQuadro);
}

function desenharQuadroBrilhoDifuso(instanteMs) {
  if (!canvasVisualizador) return;
  const contexto = canvasVisualizador.getContext("2d");
  if (!contexto) return;

  const largura = canvasVisualizador.width;
  const altura = canvasVisualizador.height;
  const escala = largura / 320;
  const centroX = largura * 0.5;
  const centroY = altura * 0.5;
  const tempoSegundos = instanteMs * 0.001;

  contexto.clearRect(0, 0, largura, altura);

  const alvoNivel = modoVisualCanvas === "listening" ? lerNivelVozInstantaneo() : 0;
  const fatorSuavizacao = alvoNivel > nivelVisualSuavizado ? 0.34 : 0.12;
  nivelVisualSuavizado += (alvoNivel - nivelVisualSuavizado) * fatorSuavizacao;

  if (modoVisualCanvas === "idle") {
    // Aura sutil de repouso ao redor do botão central
    const respiracaoCalma = 0.5 + 0.5 * Math.sin(tempoSegundos * 1.5);
    const raioRepouso = (66 + respiracaoCalma * 5) * escala;
    const gradienteRepouso = contexto.createRadialGradient(
      centroX,
      centroY,
      18 * escala,
      centroX,
      centroY,
      raioRepouso
    );
    gradienteRepouso.addColorStop(0, "rgba(239, 68, 68, 0.08)");
    gradienteRepouso.addColorStop(0.55, "rgba(99, 102, 241, 0.04)");
    gradienteRepouso.addColorStop(1, "rgba(15, 23, 42, 0)");

    contexto.fillStyle = gradienteRepouso;
    contexto.beginPath();
    contexto.arc(centroX, centroY, raioRepouso, 0, Math.PI * 2);
    contexto.fill();
    return;
  }

  if (modoVisualCanvas === "listening") {
    const respiracao = 0.5 + 0.5 * Math.sin(tempoSegundos * 2.3);
    const nivel = nivelVisualSuavizado;

    // Camada 1: Halo externo difuso vermelho carmesim/rubi (64px -> 148px sem cortar em 160px)
    const raioExterno = Math.min(150, 64 + respiracao * 6 + nivel * 76) * escala;
    const opacidadeCentro = 0.34 + respiracao * 0.05 + nivel * 0.38;
    const opacidadeMeio = 0.16 + respiracao * 0.03 + nivel * 0.24;

    const haloPrincipal = contexto.createRadialGradient(
      centroX,
      centroY,
      12 * escala,
      centroX,
      centroY,
      raioExterno
    );
    haloPrincipal.addColorStop(0, `rgba(239, 68, 68, ${opacidadeCentro.toFixed(3)})`);
    haloPrincipal.addColorStop(0.42, `rgba(220, 38, 38, ${opacidadeMeio.toFixed(3)})`);
    haloPrincipal.addColorStop(
      0.76,
      `rgba(165, 28, 28, ${(opacidadeMeio * 0.35).toFixed(3)})`
    );
    haloPrincipal.addColorStop(1, "rgba(127, 29, 29, 0)");

    contexto.fillStyle = haloPrincipal;
    contexto.beginPath();
    contexto.arc(centroX, centroY, raioExterno, 0, Math.PI * 2);
    contexto.fill();

    // Camada 2: Duas ondas concêntricas de névoa acústica moduladas pela voz
    const velocidadeNevoa = 0.56 + nivel * 0.36;
    for (let indice = 0; indice < 2; indice += 1) {
      const fase = (tempoSegundos * velocidadeNevoa + indice * 0.5) % 1;
      const decaimento = Math.pow(1 - fase, 1.65);
      const opacidadeOnda = decaimento * (0.09 + nivel * 0.22);
      const raioOndaExterno =
        Math.min(152, 48 + fase * (64 + nivel * 38)) * escala;
      const raioOndaInterno = raioOndaExterno * 0.28;

      const gradienteOnda = contexto.createRadialGradient(
        centroX,
        centroY,
        raioOndaInterno,
        centroX,
        centroY,
        raioOndaExterno
      );
      gradienteOnda.addColorStop(0, "rgba(248, 113, 113, 0)");
      gradienteOnda.addColorStop(
        0.48,
        `rgba(239, 68, 68, ${opacidadeOnda.toFixed(3)})`
      );
      gradienteOnda.addColorStop(
        0.8,
        `rgba(185, 28, 28, ${(opacidadeOnda * 0.36).toFixed(3)})`
      );
      gradienteOnda.addColorStop(1, "rgba(127, 29, 29, 0)");

      contexto.fillStyle = gradienteOnda;
      contexto.beginPath();
      contexto.arc(centroX, centroY, raioOndaExterno, 0, Math.PI * 2);
      contexto.fill();
    }

    // Camada 3: Núcleo rubi-coral quente ao redor do botão
    const raioNucleo = (52 + respiracao * 3 + nivel * 26) * escala;
    const opacidadeCoral = 0.36 + nivel * 0.42;
    const nucleoCoral = contexto.createRadialGradient(
      centroX,
      centroY,
      10 * escala,
      centroX,
      centroY,
      raioNucleo
    );
    nucleoCoral.addColorStop(0, `rgba(255, 160, 155, ${opacidadeCoral.toFixed(3)})`);
    nucleoCoral.addColorStop(
      0.52,
      `rgba(239, 68, 68, ${(0.2 + nivel * 0.25).toFixed(3)})`
    );
    nucleoCoral.addColorStop(1, "rgba(220, 38, 38, 0)");

    contexto.fillStyle = nucleoCoral;
    contexto.beginPath();
    contexto.arc(centroX, centroY, raioNucleo, 0, Math.PI * 2);
    contexto.fill();
    return;
  }

  if (modoVisualCanvas === "processing") {
    const pulsacao = 0.5 + 0.5 * Math.sin(tempoSegundos * 3.1);
    const raioAmbar = (88 + pulsacao * 8) * escala;

    const gradienteProcessando = contexto.createRadialGradient(
      centroX,
      centroY,
      16 * escala,
      centroX,
      centroY,
      raioAmbar
    );
    gradienteProcessando.addColorStop(
      0,
      `rgba(245, 158, 11, ${(0.32 + pulsacao * 0.06).toFixed(3)})`
    );
    gradienteProcessando.addColorStop(0.5, "rgba(225, 62, 45, 0.16)");
    gradienteProcessando.addColorStop(1, "rgba(127, 29, 29, 0)");

    contexto.fillStyle = gradienteProcessando;
    contexto.beginPath();
    contexto.arc(centroX, centroY, raioAmbar, 0, Math.PI * 2);
    contexto.fill();

    // Arco fino minimalista suavizado girando ao redor do microfone
    const raioArco = 52 * escala;
    const anguloBase = (tempoSegundos * 3.2) % (Math.PI * 2);

    contexto.save();
    contexto.lineCap = "round";
    contexto.lineWidth = 2.2 * escala;
    contexto.strokeStyle = "rgba(254, 215, 165, 0.78)";
    contexto.beginPath();
    contexto.arc(centroX, centroY, raioArco, anguloBase, anguloBase + Math.PI * 0.72);
    contexto.stroke();
    contexto.restore();
    return;
  }

  if (modoVisualCanvas === "esvaindo") {
    const decorridoSegundos = (instanteMs - instanteInicioDissolucao) / 1000;
    if (decorridoSegundos >= 0.35) {
      modoVisualCanvas = "idle";
      return;
    }

    const progresso = Math.min(1, Math.max(0, decorridoSegundos / 0.35));
    const fatorOpacidade = Math.exp(-4.0 * progresso) * (1 - progresso);
    const fatorContracao = 1 - 0.36 * Math.pow(progresso, 1.25);
    const raioDissolucao =
      (74 + nivelCongeladoDissolucao * 38) * fatorContracao * escala;

    const corTopo =
      modoVisualAnteriorAtivo === "processing"
        ? `rgba(245, 140, 45, ${(0.32 * fatorOpacidade).toFixed(3)})`
        : `rgba(239, 68, 68, ${(0.34 * fatorOpacidade).toFixed(3)})`;

    const gradienteSaida = contexto.createRadialGradient(
      centroX,
      centroY,
      10 * escala,
      centroX,
      centroY,
      raioDissolucao
    );
    gradienteSaida.addColorStop(0, corTopo);
    gradienteSaida.addColorStop(
      0.5,
      `rgba(220, 38, 38, ${(0.16 * fatorOpacidade).toFixed(3)})`
    );
    gradienteSaida.addColorStop(1, "rgba(127, 29, 29, 0)");

    contexto.fillStyle = gradienteSaida;
    contexto.beginPath();
    contexto.arc(centroX, centroY, raioDissolucao, 0, Math.PI * 2);
    contexto.fill();
  }
}

// ============================================================================
// Utilitários de Formatação e Segurança DOM
// ============================================================================
function exibirNotificacao(mensagem, tipo = "info") {
  if (!conteinerNotificacoes) return;

  const mapaClasses = {
    sucesso: "toast-sucesso",
    erro: "toast-erro",
    alerta: "toast-alerta",
    info: "toast-info",
  };

  const elementoAviso = document.createElement("div");
  elementoAviso.className = `toast ${mapaClasses[tipo] || "toast-info"}`;
  elementoAviso.textContent = mensagem;
  conteinerNotificacoes.appendChild(elementoAviso);

  setTimeout(() => {
    elementoAviso.classList.add("saindo");
    setTimeout(() => elementoAviso.remove(), 260);
  }, 3400);
}

function obterSeloStatus(status) {
  switch (status) {
    case "sent":
    case "success":
      return '<span class="badge badge-success">Enviado</span>';
    case "written_not_sent":
      return '<span class="badge badge-warning">Não Enviado</span>';
    case "partial":
      return '<span class="badge badge-version">Recuperado</span>';
    case "cancelled":
      return '<span class="badge badge-neutral">Cancelado</span>';
    case "error":
      return '<span class="badge badge-error">Erro</span>';
    case "empty":
      return '<span class="badge badge-neutral">Silêncio</span>';
    default:
      return `<span class="badge badge-neutral">${escaparHtml(status || "")}</span>`;
  }
}

function formatarHorarioLocal(textoIso) {
  if (!textoIso) return "";
  try {
    const data = new Date(textoIso);
    if (Number.isNaN(data.getTime())) return textoIso;
    return data.toLocaleTimeString("pt-BR", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return textoIso;
  }
}

function capitalizarTexto(texto) {
  if (!texto) return "";
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

function escaparHtml(texto) {
  if (!texto) return "";
  return String(texto)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
