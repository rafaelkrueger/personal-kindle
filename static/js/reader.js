import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.min.mjs";

const readerConfig = JSON.parse(document.getElementById("readerConfig")?.textContent || "{}");
const { bookId, pdfUrl, initialPage, initialBookmarks } = readerConfig;

const canvas = document.getElementById("pdfCanvas");
const ctx = canvas.getContext("2d");
const textLayerDiv = document.getElementById("textLayer");
const pdfWrapper = document.getElementById("pdfWrapper");
const pdfCard = document.querySelector(".pdf-card");
const readerLayout = document.querySelector(".reader-layout");
const pageInfo = document.getElementById("pageInfo");
const prevBtn = document.getElementById("prevPage");
const nextBtn = document.getElementById("nextPage");
const bookmarkBtn = document.getElementById("bookmarkBtn");
const toggleSidePanelBtn = document.getElementById("toggleSidePanel");
const zoomOutBtn = document.getElementById("zoomOutBtn");
const zoomInBtn = document.getElementById("zoomInBtn");
const zoomResetBtn = document.getElementById("zoomResetBtn");
const fullscreenBtn = document.getElementById("fullscreenBtn");
const imageAiModeBtn = document.getElementById("imageAiModeBtn");
const zoomInfo = document.getElementById("zoomInfo");
const bookmarksWrap = document.getElementById("bookmarks");
const bookmarksSection = document.getElementById("bookmarksSection");
const bookmarksCount = document.getElementById("bookmarksCount");
const highlightBtn = document.getElementById("highlightBtn");
const highlightsWrap = document.getElementById("highlights");
const highlightsSection = document.getElementById("highlightsSection");
const highlightsCount = document.getElementById("highlightsCount");
const highlightColor = document.getElementById("highlightColor");
const sidePanel = document.querySelector(".side-panel");
const aiSelectionMenu = document.getElementById("aiSelectionMenu");
const aiAskBtn = document.getElementById("aiAskBtn");
const aiTranslateBtn = document.getElementById("aiTranslateBtn");
const aiSpeakBtn = document.getElementById("aiSpeakBtn");
const aiResponseBox = document.getElementById("aiResponseBox");
const aiResponseContent = document.getElementById("aiResponseContent");
const aiCloseResponseBtn = document.getElementById("aiCloseResponseBtn");
const imageSelectionBox = document.getElementById("imageSelectionBox");
const ttsControls = document.getElementById("ttsControls");
const ttsStatus = document.getElementById("ttsStatus");
const ttsPauseResumeBtn = document.getElementById("ttsPauseResumeBtn");
const ttsStopBtn = document.getElementById("ttsStopBtn");

const progressKey = `mk_progress_${bookId}`;
const localSavedPage = Number.parseInt(localStorage.getItem(progressKey) || "0", 10) || 0;

let pdfDoc = null;
let pageNum = Math.max(initialPage || 1, localSavedPage || 1);
let rendering = false;
let pagePending = null;
let bookmarkSet = new Set(initialBookmarks || []);
let resizeTimer = null;
let progressTimer = null;
let progressInFlight = false;
let progressPending = false;
let zoomLevel = Number.parseFloat(localStorage.getItem("mk_zoom_level") || "1") || 1;
let sidePanelCollapsed = localStorage.getItem("mk_sidepanel_collapsed") === "true";
let sidePanelBeforeFullscreen = sidePanelCollapsed;
let selectedText = "";
let selectedImageDataUrl = "";
let imageAiMode = false;
let imageDragStart = null;
let currentUtterance = null;

pdfjsLib.GlobalWorkerOptions.workerSrc =
  "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.worker.min.mjs";

function clampZoom(value) {
  return Math.min(2.2, Math.max(0.75, value));
}

function isFullscreenMode() {
  return Boolean(document.fullscreenElement);
}

function updateZoomInfo() {
  if (!zoomInfo) return;
  zoomInfo.textContent = `${Math.round(zoomLevel * 100)}%`;
}

function updateFullscreenUi() {
  const active = isFullscreenMode();
  document.body.classList.toggle("is-reader-fullscreen", active);
  if (fullscreenBtn) {
    fullscreenBtn.textContent = active ? "Sair tela cheia" : "Tela cheia";
  }
}

function setZoom(newZoom) {
  zoomLevel = clampZoom(newZoom);
  localStorage.setItem("mk_zoom_level", String(zoomLevel));
  updateZoomInfo();
  if (pdfDoc && !rendering) {
    renderPage(pageNum);
  }
}

function setSidePanelCollapsed(collapsed) {
  sidePanelCollapsed = Boolean(collapsed);
  readerLayout?.classList.toggle("panel-collapsed", sidePanelCollapsed);
  sidePanel?.setAttribute("aria-hidden", sidePanelCollapsed ? "true" : "false");
  if (toggleSidePanelBtn) {
    const label = sidePanelCollapsed ? "Mostrar painel" : "Ocultar painel";
    const icon = sidePanelCollapsed ? "‹" : "›";
    toggleSidePanelBtn.setAttribute("aria-label", label);
    toggleSidePanelBtn.setAttribute("title", label);
    toggleSidePanelBtn.innerHTML = `<span aria-hidden="true">${icon}</span>`;
  }
  localStorage.setItem("mk_sidepanel_collapsed", String(sidePanelCollapsed));
}

function setSectionState(sectionEl, countEl, count) {
  if (!sectionEl || !countEl) return;
  countEl.textContent = String(count);
  sectionEl.classList.toggle("is-empty", count === 0);
  if (count === 0) {
    sectionEl.open = false;
    sectionEl.dataset.locked = "true";
  } else {
    sectionEl.dataset.locked = "false";
  }
}

function guardEmptySection(sectionEl) {
  if (!sectionEl) return;
  const summary = sectionEl.querySelector("summary");
  if (!summary) return;
  summary.addEventListener("click", (e) => {
    if (sectionEl.dataset.locked === "true") {
      e.preventDefault();
    }
  });
}

function initPanelSections() {
  guardEmptySection(bookmarksSection);
  guardEmptySection(highlightsSection);
  setSectionState(bookmarksSection, bookmarksCount, bookmarkSet.size);
  setSectionState(highlightsSection, highlightsCount, highlightsWrap.childElementCount);
}

function hydrateHighlightColors() {
  highlightsWrap.querySelectorAll(".highlight-item[data-color]").forEach((item) => {
    item.style.borderLeftColor = item.dataset.color || "#ffe066";
  });
}

function renderBookmarkList() {
  bookmarksWrap.innerHTML = "";
  [...bookmarkSet]
    .sort((a, b) => a - b)
    .forEach((p) => {
      const btn = document.createElement("button");
      btn.className = "chip";
      btn.dataset.page = String(p);
      btn.textContent = `Pagina ${p}`;
      btn.addEventListener("click", () => queueRenderPage(p));
      bookmarksWrap.appendChild(btn);
    });
  setSectionState(bookmarksSection, bookmarksCount, bookmarkSet.size);
}

function saveProgressLocal() {
  localStorage.setItem(progressKey, String(pageNum));
}

function buildProgressPayload() {
  return { page: pageNum, totalPages: pdfDoc?.numPages || 0 };
}

async function flushProgressToServer() {
  if (!pdfDoc || progressInFlight) {
    progressPending = true;
    return;
  }
  progressInFlight = true;
  progressPending = false;
  try {
    await fetch(`/api/book/${bookId}/progress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildProgressPayload()),
      keepalive: true,
    });
  } catch (_) {
    // Mantem progresso local e tenta novamente no proximo ciclo.
  } finally {
    progressInFlight = false;
    if (progressPending) {
      flushProgressToServer();
    }
  }
}

function scheduleProgressSave(immediate = false) {
  saveProgressLocal();
  clearTimeout(progressTimer);
  if (immediate) {
    flushProgressToServer();
    return;
  }
  progressTimer = setTimeout(() => {
    flushProgressToServer();
  }, 250);
}

function sendProgressBeacon() {
  if (!pdfDoc || !navigator.sendBeacon) return;
  const payload = JSON.stringify(buildProgressPayload());
  const body = new Blob([payload], { type: "application/json" });
  navigator.sendBeacon(`/api/book/${bookId}/progress`, body);
}

function hideAiMenu() {
  if (!aiSelectionMenu) return;
  aiSelectionMenu.classList.remove("show");
  aiSelectionMenu.setAttribute("aria-hidden", "true");
}

function showAiMenu(x, y) {
  if (!aiSelectionMenu) return;
  aiSelectionMenu.style.left = `${x}px`;
  aiSelectionMenu.style.top = `${y}px`;
  aiSelectionMenu.classList.add("show");
  aiSelectionMenu.setAttribute("aria-hidden", "false");
}

function showAiResponse(text) {
  if (!aiResponseBox || !aiResponseContent) return;
  aiResponseContent.textContent = text;
  aiResponseBox.classList.add("show");
}

function updateTtsStatus(text) {
  if (ttsStatus) ttsStatus.textContent = text;
}

function detectLanguageForTts(text) {
  const normalized = (text || "").toLowerCase();
  if (!normalized) return "pt-BR";
  if (/[а-яё]/i.test(normalized)) return "ru-RU";
  if (/[\u4e00-\u9fff]/.test(normalized)) return "zh-CN";
  if (/[\u3040-\u30ff]/.test(normalized)) return "ja-JP";
  if (/[\u0600-\u06ff]/.test(normalized)) return "ar-SA";

  const score = { "pt-BR": 0, "en-US": 0, "es-ES": 0, "fr-FR": 0, "de-DE": 0, "it-IT": 0 };
  const words = normalized.split(/[^a-zà-ÿ]+/).filter(Boolean);
  const stopwords = {
    "pt-BR": ["de", "que", "não", "para", "com", "uma", "você", "isso", "por", "como", "livro"],
    "en-US": ["the", "and", "for", "with", "that", "this", "from", "you", "what", "about"],
    "es-ES": ["que", "para", "con", "una", "como", "pero", "esta", "esto", "por", "del"],
    "fr-FR": ["que", "pour", "avec", "une", "dans", "est", "pas", "vous", "comme", "des"],
    "de-DE": ["und", "mit", "eine", "nicht", "ist", "das", "wie", "von", "der", "die"],
    "it-IT": ["che", "con", "una", "per", "non", "come", "del", "della", "questo", "sono"],
  };
  for (const w of words) {
    Object.entries(stopwords).forEach(([lang, list]) => {
      if (list.includes(w)) score[lang] += 1;
    });
  }
  const best = Object.entries(score).sort((a, b) => b[1] - a[1])[0];
  return best && best[1] > 0 ? best[0] : "pt-BR";
}

function pickVoiceForLang(lang) {
  const voices = window.speechSynthesis?.getVoices?.() || [];
  if (!voices.length) return null;
  const normalized = lang.toLowerCase();
  return (
    voices.find((v) => v.lang?.toLowerCase() === normalized) ||
    voices.find((v) => v.lang?.toLowerCase().startsWith(normalized.split("-")[0])) ||
    voices.find((v) => v.lang?.toLowerCase().startsWith("pt")) ||
    voices[0]
  );
}

function stopSpeech() {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  currentUtterance = null;
  ttsControls?.classList.remove("show");
  updateTtsStatus("Leitura: pronta");
}

function speakSelectedText() {
  if (selectedImageDataUrl && !selectedText) {
    showAiResponse("Para leitura em voz alta, selecione um texto. A selecao de imagem nao gera fala.");
    return;
  }
  const text = (selectedText || "").trim();
  if (!text) {
    showAiResponse("Selecione um texto primeiro para ler em voz alta.");
    return;
  }
  if (!window.speechSynthesis || typeof SpeechSynthesisUtterance === "undefined") {
    showAiResponse("Seu navegador nao suporta leitura em voz alta (Speech Synthesis).");
    return;
  }

  const lang = detectLanguageForTts(text);
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = 1;
  utterance.pitch = 1;
  utterance.volume = 1;
  const voice = pickVoiceForLang(lang);
  if (voice) utterance.voice = voice;

  utterance.onstart = () => {
    ttsControls?.classList.add("show");
    if (ttsPauseResumeBtn) ttsPauseResumeBtn.textContent = "Pausar";
    updateTtsStatus(`Lendo (${lang})...`);
  };
  utterance.onend = () => {
    ttsControls?.classList.remove("show");
    updateTtsStatus("Leitura: concluida");
    currentUtterance = null;
  };
  utterance.onerror = () => {
    ttsControls?.classList.remove("show");
    updateTtsStatus("Leitura: erro");
    currentUtterance = null;
  };

  window.speechSynthesis.cancel();
  currentUtterance = utterance;
  window.speechSynthesis.speak(utterance);
}

function togglePauseSpeech() {
  if (!window.speechSynthesis) return;
  if (window.speechSynthesis.speaking && !window.speechSynthesis.paused) {
    window.speechSynthesis.pause();
    if (ttsPauseResumeBtn) ttsPauseResumeBtn.textContent = "Retomar";
    updateTtsStatus("Leitura: pausada");
  } else if (window.speechSynthesis.paused) {
    window.speechSynthesis.resume();
    if (ttsPauseResumeBtn) ttsPauseResumeBtn.textContent = "Pausar";
    updateTtsStatus("Lendo...");
  }
}

function setImageAiMode(enabled) {
  imageAiMode = Boolean(enabled);
  if (imageAiModeBtn) {
    imageAiModeBtn.textContent = imageAiMode ? "Imagem IA: ON" : "Imagem IA";
  }
  if (!imageAiMode && imageSelectionBox) {
    imageSelectionBox.classList.remove("show");
  }
}

function getPointerPositionInCanvas(event) {
  const rect = canvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  return { x, y, rect };
}

function cropCanvasAreaToDataUrl(x1, y1, x2, y2) {
  const sx = Math.max(0, Math.min(x1, x2));
  const sy = Math.max(0, Math.min(y1, y2));
  const ex = Math.min(canvas.width, Math.max(x1, x2));
  const ey = Math.min(canvas.height, Math.max(y1, y2));
  const width = Math.max(0, ex - sx);
  const height = Math.max(0, ey - sy);
  if (width < 12 || height < 12) return "";

  const tmpCanvas = document.createElement("canvas");
  tmpCanvas.width = width;
  tmpCanvas.height = height;
  const tmpCtx = tmpCanvas.getContext("2d");
  tmpCtx.drawImage(canvas, sx, sy, width, height, 0, 0, width, height);
  return tmpCanvas.toDataURL("image/png");
}

async function askAi(question, opts = {}) {
  const payload = {
    question,
    selectionText: opts.selectionText || selectedText,
    imageDataUrl: opts.imageDataUrl || selectedImageDataUrl,
    page: pageNum,
  };
  showAiResponse("Pensando...");
  try {
    const res = await fetch(`/api/book/${bookId}/ask-ai`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.error || "Falha ao consultar IA.");
    }
    showAiResponse(data.answer || "Sem resposta.");
  } catch (err) {
    showAiResponse(`Erro: ${err.message}`);
  }
}

function updatePageInfo() {
  pageInfo.textContent = `Pagina ${pageNum} / ${pdfDoc.numPages}`;
  bookmarkBtn.textContent = bookmarkSet.has(pageNum) ? "Remover marcador" : "Marcar pagina";
}

async function renderPage(num) {
  rendering = true;
  selectedImageDataUrl = "";
  imageSelectionBox.classList.remove("show");
  const page = await pdfDoc.getPage(num);
  const baseViewport = page.getViewport({ scale: 1 });

  const maxWidth = Math.max(Math.min(pdfCard.clientWidth - 22, 860), 280);
  const fullscreenHeightRatio = isFullscreenMode() ? 0.88 : 0.72;
  const maxHeight = Math.max(Math.min(window.innerHeight * fullscreenHeightRatio, 980), 360);
  const fitScale = Math.max(Math.min(maxWidth / baseViewport.width, maxHeight / baseViewport.height), 0.45);
  const scale = fitScale * zoomLevel;
  const viewport = page.getViewport({ scale });

  pdfWrapper.style.width = `${viewport.width}px`;
  pdfWrapper.style.height = `${viewport.height}px`;
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  textLayerDiv.innerHTML = "";
  textLayerDiv.style.width = `${viewport.width}px`;
  textLayerDiv.style.height = `${viewport.height}px`;

  await page.render({ canvasContext: ctx, viewport }).promise;
  const textContent = await page.getTextContent();
  await pdfjsLib.renderTextLayer({
    textContentSource: textContent,
    container: textLayerDiv,
    viewport,
  }).promise;

  rendering = false;
  pageNum = num;
  updatePageInfo();
  scheduleProgressSave();

  if (pagePending !== null) {
    const pending = pagePending;
    pagePending = null;
    renderPage(pending);
  }
}

function queueRenderPage(num) {
  if (num < 1 || !pdfDoc || num > pdfDoc.numPages) return;
  if (rendering) {
    pagePending = num;
    return;
  }
  renderPage(num);
}

async function toggleBookmark() {
  const has = bookmarkSet.has(pageNum);
  await fetch(`/api/book/${bookId}/bookmark`, {
    method: has ? "DELETE" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page: pageNum }),
  });
  if (has) {
    bookmarkSet.delete(pageNum);
  } else {
    bookmarkSet.add(pageNum);
  }
  updatePageInfo();
  renderBookmarkList();
}

function appendHighlight(page, text, color) {
  const item = document.createElement("article");
  item.className = "highlight-item";
  item.style.borderLeftColor = color;
  item.innerHTML = `<small>Pagina ${page}</small><p></p>`;
  item.querySelector("p").textContent = text;
  highlightsWrap.prepend(item);
  setSectionState(highlightsSection, highlightsCount, highlightsWrap.childElementCount);
}

async function saveHighlight() {
  const selection = window.getSelection();
  const text = (selection?.toString() || "").trim();
  if (!text) return;
  const color = highlightColor?.value || "#ffe066";
  const payload = { page: pageNum, text, color };

  const res = await fetch(`/api/book/${bookId}/highlight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (res.ok) {
    appendHighlight(pageNum, text, color);
    selection.removeAllRanges();
  }
}

function handleTextSelection(event) {
  if (imageAiMode) return;
  const selection = window.getSelection();
  const text = (selection?.toString() || "").trim();
  if (!text) {
    selectedText = "";
    hideAiMenu();
    return;
  }
  selectedText = text;
  selectedImageDataUrl = "";
  showAiMenu(event.clientX + 10, event.clientY + 10);
}

function startImageSelection(event) {
  if (!imageAiMode || rendering) return;
  if (event.target !== canvas && event.target !== imageSelectionBox) return;
  const p = getPointerPositionInCanvas(event);
  imageDragStart = { x: p.x, y: p.y };
  imageSelectionBox.style.left = `${p.x}px`;
  imageSelectionBox.style.top = `${p.y}px`;
  imageSelectionBox.style.width = "0px";
  imageSelectionBox.style.height = "0px";
  imageSelectionBox.classList.add("show");
  hideAiMenu();
}

function moveImageSelection(event) {
  if (!imageDragStart || !imageAiMode) return;
  const p = getPointerPositionInCanvas(event);
  const left = Math.min(imageDragStart.x, p.x);
  const top = Math.min(imageDragStart.y, p.y);
  const width = Math.abs(imageDragStart.x - p.x);
  const height = Math.abs(imageDragStart.y - p.y);
  imageSelectionBox.style.left = `${left}px`;
  imageSelectionBox.style.top = `${top}px`;
  imageSelectionBox.style.width = `${width}px`;
  imageSelectionBox.style.height = `${height}px`;
}

function endImageSelection(event) {
  if (!imageDragStart || !imageAiMode) return;
  const p = getPointerPositionInCanvas(event);
  selectedImageDataUrl = cropCanvasAreaToDataUrl(imageDragStart.x, imageDragStart.y, p.x, p.y);
  imageDragStart = null;
  if (selectedImageDataUrl) {
    selectedText = "";
    showAiMenu(event.clientX + 10, event.clientY + 10);
  } else {
    imageSelectionBox.classList.remove("show");
  }
}

async function toggleFullscreen() {
  try {
    if (isFullscreenMode()) {
      await document.exitFullscreen();
      return;
    }
    sidePanelBeforeFullscreen = sidePanelCollapsed;
    setSidePanelCollapsed(true);
    await document.documentElement.requestFullscreen();
  } catch (_) {
    // Silencioso para evitar bloquear leitura em navegadores restritivos.
  }
}

nextBtn.addEventListener("click", () => queueRenderPage(pageNum + 1));
prevBtn.addEventListener("click", () => queueRenderPage(pageNum - 1));
bookmarkBtn.addEventListener("click", toggleBookmark);
highlightBtn.addEventListener("click", saveHighlight);
toggleSidePanelBtn?.addEventListener("click", () => setSidePanelCollapsed(!sidePanelCollapsed));
zoomOutBtn?.addEventListener("click", () => setZoom(zoomLevel - 0.1));
zoomInBtn?.addEventListener("click", () => setZoom(zoomLevel + 0.1));
zoomResetBtn?.addEventListener("click", () => setZoom(1));
fullscreenBtn?.addEventListener("click", toggleFullscreen);
imageAiModeBtn?.addEventListener("click", () => setImageAiMode(!imageAiMode));
aiAskBtn?.addEventListener("click", async () => {
  hideAiMenu();
  const prompt = window.prompt("O que voce quer perguntar para a IA?");
  if (!prompt) return;
  await askAi(prompt);
});
aiTranslateBtn?.addEventListener("click", async () => {
  hideAiMenu();
  const base = selectedImageDataUrl
    ? "Descreva e traduza para portugues o conteudo da imagem selecionada."
    : "Traduza para portugues do Brasil o trecho selecionado.";
  await askAi(base);
});
aiSpeakBtn?.addEventListener("click", () => {
  hideAiMenu();
  speakSelectedText();
});
aiCloseResponseBtn?.addEventListener("click", () => {
  aiResponseBox?.classList.remove("show");
});
ttsPauseResumeBtn?.addEventListener("click", togglePauseSpeech);
ttsStopBtn?.addEventListener("click", stopSpeech);

textLayerDiv?.addEventListener("mouseup", handleTextSelection);
document.addEventListener("mousedown", (e) => {
  if (!aiSelectionMenu?.contains(e.target)) {
    hideAiMenu();
  }
});

canvas.addEventListener("mousedown", startImageSelection);
canvas.addEventListener("mousemove", moveImageSelection);
canvas.addEventListener("mouseup", endImageSelection);
canvas.addEventListener("mouseleave", endImageSelection);

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && (e.key === "+" || e.key === "=")) {
    e.preventDefault();
    setZoom(zoomLevel + 0.1);
    return;
  }
  if (e.ctrlKey && e.key === "-") {
    e.preventDefault();
    setZoom(zoomLevel - 0.1);
    return;
  }
  if (e.ctrlKey && e.key === "0") {
    e.preventDefault();
    setZoom(1);
    return;
  }
  if (e.key.toLowerCase() === "f") {
    e.preventDefault();
    toggleFullscreen();
    return;
  }
  if (!e.ctrlKey && (e.key === "+" || e.key === "=")) {
    e.preventDefault();
    setZoom(zoomLevel + 0.1);
    return;
  }
  if (!e.ctrlKey && e.key === "-") {
    e.preventDefault();
    setZoom(zoomLevel - 0.1);
    return;
  }
  if (e.key === "ArrowLeft") queueRenderPage(pageNum - 1);
  if (e.key === "ArrowRight") queueRenderPage(pageNum + 1);
});

document.addEventListener("fullscreenchange", () => {
  const active = isFullscreenMode();
  updateFullscreenUi();
  if (!active) {
    setSidePanelCollapsed(sidePanelBeforeFullscreen);
  }
  if (pdfDoc && !rendering) {
    renderPage(pageNum);
  }
  scheduleProgressSave(true);
});

window.addEventListener("resize", () => {
  if (!pdfDoc) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    renderPage(pageNum);
  }, 150);
});

window.addEventListener("pagehide", () => {
  scheduleProgressSave(true);
  sendProgressBeacon();
});

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    scheduleProgressSave(true);
    sendProgressBeacon();
    stopSpeech();
  }
});

document.body.classList.add("pi-lite");

pdfjsLib
  .getDocument({
    url: pdfUrl,
    disableAutoFetch: true,
    disableStream: true,
    isEvalSupported: false,
  })
  .promise.then((pdf) => {
    pdfDoc = pdf;
    zoomLevel = clampZoom(zoomLevel);
    updateZoomInfo();
    updateFullscreenUi();
    setSidePanelCollapsed(sidePanelCollapsed);
    initPanelSections();
    hydrateHighlightColors();
    renderBookmarkList();
    renderPage(pageNum);
  });
