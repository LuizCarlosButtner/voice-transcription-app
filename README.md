# Voice Transcription App

Aplicativo desktop autônomo e nativo para macOS que transforma voz em texto em qualquer janela ativa, com ajuste contextual de tom, tradução instantânea e caça inteligente de campos de texto.

Diretório oficial do projeto:
```text
/Users/luizcarlospereira/programas/voice-transcription-app
```

---

## Recursos Principais

### 1. Três Modos de Acionamento Global (`⌥ Option` por padrão)
Configuráveis instantaneamente pela Barra de Menus do macOS ou pelo Painel de Controle Web:
- **Híbrido (`hibrido` — Padrão Recomendado):**
  - **Segurar (≥ 0.35s):** grava enquanto a tecla estiver pressionada e envia assim que você soltar.
  - **Toque Rápido (< 0.35s):** trava a gravação ligada com mãos livres; um novo toque encerra e insere o texto.
- **Segurar para Falar (`segurar` — Push-and-Hold):**
  - Grava estritamente enquanto a tecla permanecer pressionada (ignorando repetições automáticas de teclado) e sempre finaliza ao soltar, mesmo em toques curtos.
- **Toque para Alternar (`alternar` — Liga/Desliga):**
  - 1º toque inicia a captura contínua; 2º toque interrompe, transcreve e insere no cursor.
- **Cancelamento Rápido (`Esc`):** interrompe imediatamente qualquer gravação sem colar texto, preservando o áudio no histórico para eventual recuperação.

### 2. Brilho Vermelho Difuso Sofisticado (CoreGraphics + Painel Web 60fps)
- **Overlay Nativo macOS (`NSPanel` 220×220 px):** posicionado horizontalmente centralizado a ~5.5% da base da tela, 100% transparente a cliques (`ignoresMouseEvents`) e sem roubar foco.
  - **Ouvindo:** halo amplo vermelho carmesim/rubi renderizado via `CGGradientCreateWithColors` + `CGContextDrawRadialGradient`, acompanhado de duas ondas concêntricas de névoa acústica e núcleo rubi-coral quente modulado pela amplitude real da voz (sem círculos chapados e sem corte nas bordas).
  - **Processando:** halo difuso âmbar/rubi suave com arco fino minimalista anti-aliased em rotação contínua.
  - **Dissolução Suave:** contração orgânica e fade-out exponencial de `0.35s` ao retornar ao repouso.
- **Estúdio Web Sincronizado em Tempo Real (`GET /eventos` SSE):** o `<canvas>` do painel web renderiza o mesmo brilho difuso a 60fps tanto em testes pelo navegador quanto ao pressionar `Option` em qualquer aplicativo do macOS.

### 3. Protocolo de Autoteste de Inicialização (5 Etapas)
No boot do daemon (e sob demanda via barra de menus ou `POST /diagnostico/executar`), o aplicativo valida automaticamente:
1. **`armazenamento_banco`:** criação segura de `~/.voice-transcription`, verificação `PRAGMA quick_check` no SQLite e recuperação automática de fatias de áudio órfãs.
2. **`chaves_provedores`:** validação de `GROQ_API_KEY`, suporte a gravação leve OGG Vorbis (`soundfile`) e disponibilidade de contingência local (`SenseVoice`).
3. **`permissoes_macos`:** diagnóstico individual de **Microfone**, **Acessibilidade** e **Monitoramento de Entrada**.
4. **`subsistema_audio`:** filtragem automática de drivers virtuais (como BlackHole, Voicemod, Loopback e Soundflower), seleção do microfone físico real e fallback automático de taxa de amostragem para 16 kHz.
5. **`escutador_atalho`:** garantia de instância única e idempotente do listener global de teclado com supervisão contínua (watchdog).

### 4. Caça Inteligente de Input em Abas e Aplicativos (`AXWebArea`)
- Ativa `AXEnhancedUserInterface` e `AXManualAccessibility` automaticamente para que navegadores (Chrome, Brave, Arc, Edge, Safari) e apps Electron exponham a árvore interna da aba.
- Calcula pontuação de relevância priorizando compositores multi-linha (`AXTextArea` / `AXTextView`) dentro de `AXWebArea` com dicas semânticas de chat/prompt, penalizando fortemente barras de endereço/URL no topo da janela e ignorando textos estáticos não editáveis.
- Caso o foco direto via Acessibilidade não seja confirmado, executa opcionalmente um clique suave no centro do campo restaurando a posição original do cursor do mouse em seguida, e preserva integralmente o conteúdo anterior da área de transferência (clipboard) ao colar.

### 5. Tons de Voz, Tradução PT ➔ EN e Proteção Anti-Perda
- **Quatro Estilos de Escrita:** `Verbatim` (sem filtro), `Coloquial`, `Semiformal` e `Formal`.
- **Tradução Instantânea (PT ➔ EN):** fale em português brasileiro e insira diretamente em inglês no aplicativo ativo.
- **Backup Contínuo por Fatias OGG & Auto-Parada por Silêncio:** grava fatias preventivas de 30s após o limiar configurado (padrão: 40s) e encerra automaticamente após silêncio prolongado (padrão: 60s).

---

## Permissões Necessárias no macOS

Em **Ajustes do Sistema > Privacidade e Segurança**, conceda ao `VoiceTranscription.app` (ou ao terminal utilizado em desenvolvimento):
1. **Microfone:** captura da sua voz pelo microfone físico.
2. **Acessibilidade:** inspeção de foco `AXUIElement` / `AXWebArea` e colagem no cursor ativo.
3. **Monitoramento de Entrada:** escuta global da tecla de atalho em segundo plano.

---

## Instalação, Execução e Empacotamento

### 1. Ambiente Virtual e Dependências
```bash
cd /Users/luizcarlospereira/programas/voice-transcription-app
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

Configure a chave `GROQ_API_KEY` no seu ambiente (`~/.zshenv` / `~/.zshrc`) ou em um arquivo `.env` na raiz do projeto:
```bash
cp .env.example .env
```

### 2. Executar o Aplicativo Completo (Menu Bar + Overlay + Painel Web)
```bash
./venv/bin/python backend/main.py
```
O Painel de Controle Web fica disponível em `http://127.0.0.1:8100/`.

### 3. Gerar o Bundle Nativo `VoiceTranscription.app`
```bash
./venv/bin/python packaging/build_app.py
```

### 4. Executar a Suíte de Testes Isolada
```bash
./venv/bin/pytest
```

---

## Licença

MIT License. Consulte o arquivo `LICENSE` para mais detalhes.
