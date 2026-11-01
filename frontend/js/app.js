/**
 * Voice Transcription App - Frontend Application Logic
 */

const API_BASE = ""; // Relative URL, served directly by FastAPI on port 8100

// State
let appState = {
  settings: {},
  stats: {},
  history: [],
  activeFilter: "all",
  searchQuery: "",
  isOnline: false,
  isRecording: false
};

// Audio recording in browser
let mediaRecorder = null;
let audioChunks = [];
let recordStartTime = 0;
let timerInterval = null;
let audioContext = null;
let analyser = null;
let animFrameId = null;

// DOM Elements
const daemonPill = document.getElementById("daemon-connection-pill");
const daemonStatusText = document.getElementById("daemon-status-text");
const activeHotkeyBadge = document.getElementById("active-hotkey-badge");
const btnRefreshAll = document.getElementById("btn-refresh-all");

// Metrics
const metricProvider = document.getElementById("metric-provider");
const metricProviderSub = document.getElementById("metric-provider-sub");
const metricActiveTone = document.getElementById("metric-active-tone");
const badgePermMic = document.getElementById("badge-perm-mic");
const badgePermAx = document.getElementById("badge-perm-ax");
const metricFrontApp = document.getElementById("metric-front-app");
const metricTotalCount = document.getElementById("metric-total-count");
const metricStatsDetail = document.getElementById("metric-stats-detail");

// Studio & Recording
const tonesGrid = document.getElementById("tones-selector-grid");
const btnHeroMic = document.getElementById("btn-hero-mic");
const recordingTimer = document.getElementById("recording-timer");
const recordingStateLabel = document.getElementById("recording-state-label");
const visualizerCanvas = document.getElementById("visualizer-canvas");
const liveResultBox = document.getElementById("live-result-box");
const liveResultText = document.getElementById("live-result-text");
const liveResultAudioWrapper = document.getElementById("live-result-audio-wrapper");
const btnCopyLive = document.getElementById("btn-copy-live");
const btnCloseLive = document.getElementById("btn-close-live");

// Tabs & History
const tabButtons = document.querySelectorAll(".tab-btn");
const tabContents = document.querySelectorAll(".tab-content");
const historyListContainer = document.getElementById("history-list-container");
const historySearchInput = document.getElementById("history-search-input");
const filterPills = document.querySelectorAll(".filter-pill");
const tabHistoryCount = document.getElementById("tab-history-count");

// Settings Form
const settingGrammar = document.getElementById("setting-grammar");
const settingAppend = document.getElementById("setting-append");
const settingToggle = document.getElementById("setting-toggle");
const settingAutostart = document.getElementById("setting-autostart");
const settingHotkey = document.getElementById("setting-hotkey");
const settingLanguage = document.getElementById("setting-language");
const settingChunkBackup = document.getElementById("setting-chunk-backup");
const settingChunkStart = document.getElementById("setting-chunk-start");
const settingSilenceStop = document.getElementById("setting-silence-stop");
const btnSaveSettings = document.getElementById("btn-save-settings");
const btnResetSettings = document.getElementById("btn-reset-settings");

const toastContainer = document.getElementById("toast-container");

// Translation Feature Elements
const toggleTranslateEn = document.getElementById("toggle-translate-en");
const translateStatusText = document.getElementById("translate-status-text");
const translationFeatureBar = document.getElementById("translation-feature-bar");

// ==========================================
// Initialization
// ==========================================
document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  fetchStatus();
  fetchHistory();

  // Poll status and history every 4 seconds to catch macOS global hotkey transcriptions live
  setInterval(() => {
    if (!appState.isRecording) {
      fetchStatus(true);
      fetchHistory(true);
    }
  }, 4000);
});

function setupEventListeners() {
  btnRefreshAll.addEventListener("click", () => {
    fetchStatus();
    fetchHistory();
    showToast("Atualizando dados do servidor...", "info");
  });

  // Tab switching
  tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      tabButtons.forEach(b => b.classList.remove("active"));
      tabContents.forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      const targetId = btn.dataset.tab;
      document.getElementById(targetId)?.classList.add("active");
    });
  });

  // Tone selector
  tonesGrid.addEventListener("click", (e) => {
    const card = e.target.closest(".tone-card");
    if (!card) return;
    const selectedTone = card.dataset.tone;
    updateTone(selectedTone);
  });

  // Translation Toggle
  if (toggleTranslateEn) {
    toggleTranslateEn.addEventListener("change", async (e) => {
      const isEnabled = e.target.checked;
      await updateTranslationSetting(isEnabled);
    });
  }

  // Recording button
  btnHeroMic.addEventListener("click", toggleBrowserRecording);

  // Live box actions
  btnCopyLive.addEventListener("click", () => {
    const text = liveResultText.innerText;
    if (text) {
      navigator.clipboard.writeText(text);
      showToast("Texto copiado para a área de transferência!", "success");
    }
  });

  btnCloseLive.addEventListener("click", () => {
    liveResultBox.style.display = "none";
  });

  // Search input with debounce
  let searchTimeout = null;
  historySearchInput.addEventListener("input", (e) => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      appState.searchQuery = e.target.value.trim();
      renderHistoryList();
    }, 250);
  });

  // History filter pills
  filterPills.forEach(pill => {
    pill.addEventListener("click", () => {
      filterPills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      appState.activeFilter = pill.dataset.filter;
      renderHistoryList();
    });
  });

  // Settings Save & Reset
  btnSaveSettings.addEventListener("click", saveSettings);
  btnResetSettings.addEventListener("click", resetSettings);
}

// ==========================================
// API Calls
// ==========================================
async function fetchStatus(isBackground = false) {
  try {
    const res = await fetch(`${API_BASE}/status`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    appState.settings = data;
    appState.stats = data.stats || {};
    appState.isOnline = true;

    updateUIStatus(data);
  } catch (err) {
    appState.isOnline = false;
    daemonPill.innerHTML = '<span class="status-dot dot-offline"></span><span class="status-label" id="daemon-status-text">Offline</span>';
    if (!isBackground) {
      showToast("Não foi possível conectar ao daemon local (:8100)", "error");
    }
  }
}

async function fetchHistory(isBackground = false) {
  try {
    const res = await fetch(`${API_BASE}/history?limit=100`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    appState.history = data.entries || [];
    tabHistoryCount.innerText = data.count || appState.history.length;
    renderHistoryList();
  } catch (err) {
    if (!isBackground) {
      historyListContainer.innerHTML = `
        <div class="empty-state">
          <p>Erro ao carregar histórico: ${err.message}</p>
          <button class="btn btn-outline btn-sm" onclick="fetchHistory()">Tentar Novamente</button>
        </div>
      `;
    }
  }
}

async function updateTone(toneKey) {
  try {
    const res = await fetch(`${API_BASE}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tone: toneKey })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const updated = await res.json();
    appState.settings.tone = updated.tone;
    highlightToneCard(updated.tone);
    metricActiveTone.innerText = capitalize(updated.tone);
    showToast(`Tom atualizado para: ${capitalize(updated.tone)}`, "success");
  } catch (err) {
    showToast(`Falha ao alterar tom: ${err.message}`, "error");
  }
}

async function updateTranslationSetting(enabled) {
  try {
    const res = await fetch(`${API_BASE}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ translate_to_english: enabled })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const updated = await res.json();
    appState.settings.translate_to_english = updated.translate_to_english;
    syncTranslationUI(updated.translate_to_english);
    const msg = updated.translate_to_english
      ? "Tradução PT ➔ EN ATIVADA (você fala em português e digita em inglês)"
      : "Tradução desativada (transcreve e digita em português)";
    showToast(msg, "info");
  } catch (err) {
    showToast(`Erro ao alterar tradução: ${err.message}`, "error");
  }
}

function syncTranslationUI(enabled) {
  if (toggleTranslateEn) {
    toggleTranslateEn.checked = !!enabled;
  }
  if (translateStatusText) {
    translateStatusText.innerText = enabled ? "ATIVADO (PT ➔ EN)" : "Desativado";
    translateStatusText.className = "switch-status-text" + (enabled ? " active" : "");
  }
  if (translationFeatureBar) {
    if (enabled) {
      translationFeatureBar.classList.add("active");
    } else {
      translationFeatureBar.classList.remove("active");
    }
  }
}

async function saveSettings() {
  const payload = {
    grammar_correction: settingGrammar.checked,
    append_at_cursor: settingAppend.checked,
    toggle_mode: settingToggle.checked,
    hotkey: settingHotkey.value,
    language: settingLanguage.value,
    chunk_backup_enabled: settingChunkBackup ? settingChunkBackup.checked : true,
    chunk_start_seconds: settingChunkStart ? parseInt(settingChunkStart.value, 10) || 40 : 40
  };

  try {
    const res = await fetch(`${API_BASE}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    appState.settings = data;
    updateUIStatus(data);
    showToast("Preferências salvas com sucesso!", "success");
  } catch (err) {
    showToast(`Erro ao salvar: ${err.message}`, "error");
  }
}

async function resetSettings() {
  const defaults = {
    grammar_correction: true,
    append_at_cursor: true,
    toggle_mode: false,
    hotkey: "Alt",
    language: "pt",
    tone: "verbatim"
  };
  try {
    const res = await fetch(`${API_BASE}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(defaults)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    appState.settings = data;
    updateUIStatus(data);
    showToast("Preferências restauradas para o padrão!", "info");
  } catch (err) {
    showToast(`Erro: ${err.message}`, "error");
  }
}

async function triggerRetry(entryId, btnElement) {
  if (btnElement) {
    btnElement.disabled = true;
    btnElement.innerText = "Reprocessando...";
  }

  try {
    const res = await fetch(`${API_BASE}/retry/${entryId}`, { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      showToast("Áudio retranscrito com sucesso!", "success");
      fetchHistory();
    } else {
      showToast(`Falha no retry: ${data.error || "Desconhecido"}`, "error");
      if (btnElement) {
        btnElement.disabled = false;
        btnElement.innerText = "🔄 Repetir (Retry)";
      }
    }
  } catch (err) {
    showToast(`Erro ao chamar retry: ${err.message}`, "error");
    if (btnElement) {
      btnElement.disabled = false;
      btnElement.innerText = "🔄 Repetir (Retry)";
    }
  }
}

// ==========================================
// UI Updates
// ==========================================
function updateUIStatus(data) {
  daemonPill.innerHTML = '<span class="status-dot dot-online"></span><span class="status-label" id="daemon-status-text">Online (8100)</span>';

  // Hotkey badge
  const hotkey = data.hotkey || "Alt";
  activeHotkeyBadge.innerText = hotkey === "Alt" ? "⌥ Option / Alt" : hotkey;

  // Provider
  metricProvider.innerText = capitalize(data.active_provider || "Groq");
  metricProviderSub.innerText = `${data.groq_stt_model || "whisper-large-v3-turbo"} (Nuvem)`;

  // Tone
  const currentTone = data.tone || "verbatim";
  metricActiveTone.innerText = capitalize(currentTone);
  highlightToneCard(currentTone);

  // Permissions
  const perms = data.permissions || {};
  const isMicOk = perms.microphone_status === "Authorized" || perms.microphone_status === "NotDetermined";
  badgePermMic.innerText = `Microfone: ${perms.microphone_status || "OK"}`;
  badgePermMic.className = `badge ${isMicOk ? "badge-success" : "badge-error"}`;

  const isAxOk = perms.accessibility_trusted;
  badgePermAx.innerText = `Acessibilidade: ${isAxOk ? "Ativo" : "Pendente"}`;
  badgePermAx.className = `badge ${isAxOk ? "badge-success" : "badge-warning"}`;

  // Front app
  const frontApp = data.frontmost_app?.name || "Nenhum";
  metricFrontApp.innerText = `App em foco: ${frontApp}`;

  // Stats
  const stats = data.stats || {};
  metricTotalCount.innerText = stats.total || 0;
  metricStatsDetail.innerText = `${stats.success || 0} sucessos · ${stats.errors || 0} erros (${stats.avg_duration_ms || 0}ms médio)`;

  // Settings form controls
  settingGrammar.checked = !!data.grammar_correction;
  settingAppend.checked = !!data.append_at_cursor;
  settingToggle.checked = !!data.toggle_mode;
  settingHotkey.value = data.hotkey || "Alt";
  settingLanguage.value = data.language || "pt";
  if (settingChunkBackup) settingChunkBackup.checked = data.chunk_backup_enabled !== false;
  if (settingChunkStart) settingChunkStart.value = data.chunk_start_seconds || 40;
  if (settingSilenceStop) settingSilenceStop.value = data.silence_auto_stop_seconds || 60;

  // Sync translation toggle
  syncTranslationUI(!!data.translate_to_english);
}

function highlightToneCard(toneKey) {
  const cards = document.querySelectorAll(".tone-card");
  cards.forEach(card => {
    if (card.dataset.tone === toneKey) {
      card.classList.add("active");
    } else {
      card.classList.remove("active");
    }
  });
}

function renderHistoryList() {
  let items = [...appState.history];

  // Filter
  if (appState.activeFilter !== "all") {
    items = items.filter(i => i.status === appState.activeFilter);
  }

  // Search
  if (appState.searchQuery) {
    const q = appState.searchQuery.toLowerCase();
    items = items.filter(i => 
      (i.text_final && i.text_final.toLowerCase().includes(q)) ||
      (i.text_raw && i.text_raw.toLowerCase().includes(q)) ||
      (i.active_app && i.active_app.toLowerCase().includes(q))
    );
  }

  if (items.length === 0) {
    historyListContainer.innerHTML = `
      <div class="empty-state">
        <span style="font-size: 2rem;">📭</span>
        <p>Nenhuma gravação encontrada com os filtros selecionados.</p>
        <p class="subtitle">Use o atalho ⌥ Option em qualquer janela do Mac ou clique no microfone acima para gravar.</p>
      </div>
    `;
    return;
  }

  historyListContainer.innerHTML = items.map(entry => renderHistoryCard(entry)).join("");
}

function renderHistoryCard(entry) {
  const statusBadge = getStatusBadge(entry.status);
  const timeFormatted = formatTime(entry.created_at);
  const durationSec = entry.duration_ms ? (entry.duration_ms / 1000).toFixed(1) + "s" : "0s";
  const appName = entry.active_app || "macOS";
  const toneLabel = capitalize(entry.tone || "verbatim");
  const providerLabel = capitalize(entry.provider || "groq");

  const isError = entry.status === "error";
  const hasRawDiff = entry.text_raw && entry.text_final && entry.text_raw.trim() !== entry.text_final.trim();

  return `
    <div class="history-card" data-id="${entry.id}">
      <div class="history-card-header">
        <div class="history-meta">
          ${statusBadge}
          <span title="${entry.created_at}">🕒 ${timeFormatted}</span>
          <span>💻 <strong>${escapeHtml(appName)}</strong></span>
          <span>⏱️ ${durationSec}</span>
          <span class="badge badge-version">🎭 ${toneLabel}</span>
          <span class="badge" style="background: rgba(6,182,212,0.15); color: #67e8f9;">⚡ ${providerLabel}</span>
        </div>
        <div class="history-actions">
          ${entry.text_final ? `
            <button class="btn btn-sm btn-outline" onclick="copyCardText('${entry.id}')" title="Copiar texto final">
              📋 Copiar
            </button>
          ` : ""}
          ${isError ? `
            <button class="btn btn-sm btn-primary" onclick="triggerRetry('${entry.id}', this)" title="Reprocessar áudio salvo">
              🔄 Repetir (Retry)
            </button>
          ` : ""}
        </div>
      </div>

      <div class="history-content">
        ${isError ? `
          <div class="error-banner">
            <div>
              <strong>⚠️ Falha de Transcrição:</strong> ${escapeHtml(entry.error_message || "Erro desconhecido")}
            </div>
            <span style="font-size: 0.75rem; color: #fecaca;">Áudio bruto preservado no disco</span>
          </div>
        ` : `
          <div class="text-final-box" id="text-final-${entry.id}">
            ${escapeHtml(entry.text_final || "(Sem fala detectada)")}
          </div>
        `}

        ${hasRawDiff ? `
          <button class="raw-toggle-btn" onclick="toggleRawText('${entry.id}')">
            ▶ Ver transcrição bruta original (sem tom)
          </button>
          <div class="text-raw-box" id="text-raw-${entry.id}" style="display: none;">
            ${escapeHtml(entry.text_raw)}
          </div>
        ` : ""}

        <!-- Player de Áudio do WAV Gravado -->
        <div class="audio-player-wrapper">
          <audio controls preload="none" src="${API_BASE}/audio/${entry.id}" style="width: 100%; height: 32px;"></audio>
        </div>
      </div>
    </div>
  `;
}

// Card helpers
window.copyCardText = function(entryId) {
  const el = document.getElementById(`text-final-${entryId}`);
  if (el) {
    navigator.clipboard.writeText(el.innerText.trim());
    showToast("Texto copiado para a área de transferência!", "success");
  }
};

window.toggleRawText = function(entryId) {
  const el = document.getElementById(`text-raw-${entryId}`);
  if (el) {
    const isHidden = el.style.display === "none";
    el.style.display = isHidden ? "block" : "none";
  }
};

// ==========================================
// Browser Microphone Audio Recording
// ==========================================
async function toggleBrowserRecording() {
  if (appState.isRecording) {
    stopBrowserRecording();
  } else {
    startBrowserRecording();
  }
}

async function startBrowserRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioChunks = [];
    appState.isRecording = true;

    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };

    mediaRecorder.onstop = handleRecordingStopped;
    mediaRecorder.start();

    // Visualizer Setup
    setupVisualizer(stream);

    // Button state
    btnHeroMic.classList.add("recording");
    recordingStateLabel.innerText = "Gravando... Clique no botão para parar";
    recordingStateLabel.style.color = "var(--error)";

    recordStartTime = Date.now();
    recordingTimer.innerText = "00:00";
    clearInterval(timerInterval);
    timerInterval = setInterval(() => {
      const elapsedSec = Math.floor((Date.now() - recordStartTime) / 1000);
      const m = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
      const s = String(elapsedSec % 60).padStart(2, "0");
      recordingTimer.innerText = `${m}:${s}`;
    }, 500);

  } catch (err) {
    showToast(`Erro ao acessar microfone no navegador: ${err.message}`, "error");
  }
}

function stopBrowserRecording() {
  if (mediaRecorder && appState.isRecording) {
    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach(t => t.stop());
  }

  appState.isRecording = false;
  btnHeroMic.classList.remove("recording");
  btnHeroMic.classList.add("processing");
  recordingStateLabel.innerText = "Transcrevendo e ajustando tom...";
  recordingStateLabel.style.color = "var(--warning)";
  clearInterval(timerInterval);
  cancelAnimationFrame(animFrameId);
  clearCanvas();
}

async function handleRecordingStopped() {
  const audioBlob = new Blob(audioChunks, { type: "audio/wav" });
  btnHeroMic.classList.remove("processing");
  recordingStateLabel.innerText = "Pronto para ouvir";
  recordingStateLabel.style.color = "var(--text-primary)";

  const reader = new FileReader();
  reader.readAsDataURL(audioBlob);
  reader.onloadend = async () => {
    const base64Audio = reader.result.split(",")[1];
    try {
      showToast("Enviando áudio para processamento...", "info");
      const activeTone = appState.settings.tone || "verbatim";
      const res = await fetch(`${API_BASE}/transcribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dataBase64: base64Audio,
          mimeType: "audio/wav",
          language: appState.settings.language || "pt",
          tone: activeTone
        })
      });

      const data = await res.json();
      if (data.ok) {
        showToast("Transcrição concluída com sucesso!", "success");
        // Mostra no banner de resultado ao vivo
        liveResultText.innerText = data.text_final || "(Sem fala detectada)";
        liveResultAudioWrapper.innerHTML = `
          <audio controls src="${API_BASE}/audio/${data.entry_id}" style="width: 100%; height: 32px; margin-top: 6px;"></audio>
        `;
        liveResultBox.style.display = "flex";

        // Atualiza histórico
        fetchHistory();
        fetchStatus(true);
      } else {
        showToast(`Falha na transcrição: ${data.error || "Erro"}`, "error");
      }
    } catch (err) {
      showToast(`Erro na requisição: ${err.message}`, "error");
    }
  };
}

// Canvas Wave Visualizer
function setupVisualizer(stream) {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  const source = audioContext.createMediaStreamSource(stream);
  analyser = audioContext.createAnalyser();
  analyser.fftSize = 64;
  source.connect(analyser);

  const ctx = visualizerCanvas.getContext("2d");
  const bufferLength = analyser.frequencyBinCount;
  const dataArray = new Uint8Array(bufferLength);

  function draw() {
    animFrameId = requestAnimationFrame(draw);
    analyser.getByteFrequencyData(dataArray);

    ctx.clearRect(0, 0, visualizerCanvas.width, visualizerCanvas.height);
    const centerX = visualizerCanvas.width / 2;
    const centerY = visualizerCanvas.height / 2;
    const baseRadius = 55;

    let sum = 0;
    for (let i = 0; i < bufferLength; i++) sum += dataArray[i];
    const avg = sum / bufferLength;
    const waveRadius = baseRadius + (avg * 0.4);

    // Glowing outer ring
    ctx.beginPath();
    ctx.arc(centerX, centerY, waveRadius, 0, 2 * Math.PI);
    ctx.strokeStyle = `rgba(239, 68, 68, ${Math.min(0.8, avg / 120)})`;
    ctx.lineWidth = 4 + (avg * 0.05);
    ctx.stroke();

    // Second softer ring
    ctx.beginPath();
    ctx.arc(centerX, centerY, waveRadius + 14, 0, 2 * Math.PI);
    ctx.strokeStyle = `rgba(99, 102, 241, ${Math.min(0.5, avg / 180)})`;
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  draw();
}

function clearCanvas() {
  const ctx = visualizerCanvas.getContext("2d");
  ctx.clearRect(0, 0, visualizerCanvas.width, visualizerCanvas.height);
}

// ==========================================
// Utilities
// ==========================================
function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerText = message;
  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(50px)";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function getStatusBadge(status) {
  switch (status) {
    case "sent":
    case "success":
      return '<span class="badge badge-success">✓ Enviado</span>';
    case "written_not_sent":
      return '<span class="badge badge-warning">📝 Não Enviado</span>';
    case "partial":
      return '<span class="badge" style="background: rgba(147, 51, 234, 0.2); color: #c084fc; border: 1px solid rgba(147, 51, 234, 0.4);">🔄 Recuperado (Crash)</span>';
    case "cancelled":
      return '<span class="badge" style="background: rgba(156,163,175,0.2); color: #9ca3af; border: 1px solid rgba(156,163,175,0.3);">🛑 Cancelado</span>';
    case "error":
      return '<span class="badge badge-error">✕ Erro</span>';
    case "empty":
      return '<span class="badge badge-warning">∅ Vazio</span>';
    default:
      return `<span class="badge">${status}</span>`;
  }
}

function formatTime(isoString) {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    return d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return isoString;
  }
}

function capitalize(str) {
  if (!str) return "";
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function escapeHtml(text) {
  if (!text) return "";
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
