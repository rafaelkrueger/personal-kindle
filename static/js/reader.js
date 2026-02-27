import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.2.67/pdf.min.mjs";

const readerConfig = JSON.parse(document.getElementById("readerConfig")?.textContent || "{}");
const {
  bookId,
  pdfUrl,
  initialPage,
  initialBookmarks,
} = readerConfig;

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

let pdfDoc = null;
let pageNum = initialPage || 1;
let rendering = false;
let pagePending = null;
let bookmarkSet = new Set(initialBookmarks || []);
let animating = false;
let resizeTimer = null;
let zoomLevel = Number.parseFloat(localStorage.getItem("mk_zoom_level") || "1") || 1;
let sidePanelCollapsed = localStorage.getItem("mk_sidepanel_collapsed") === "true";
let sidePanelBeforeFullscreen = sidePanelCollapsed;

const flipCanvas = document.createElement("canvas");
flipCanvas.id = "flipCanvas";
flipCanvas.className = "flip-canvas";
const flipCtx = flipCanvas.getContext("2d");

const flipShadow = document.createElement("div");
flipShadow.className = "flip-shadow";

pdfWrapper.appendChild(flipCanvas);
pdfWrapper.appendChild(flipShadow);

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
  if (pdfDoc && !rendering && !animating) {
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
      btn.addEventListener("click", () => queueRenderPage(p, p < pageNum ? "prev" : "next"));
      bookmarksWrap.appendChild(btn);
    });
  setSectionState(bookmarksSection, bookmarksCount, bookmarkSet.size);
}

async function saveProgress() {
  await fetch(`/api/book/${bookId}/progress`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page: pageNum, totalPages: pdfDoc.numPages }),
  });
}

function updatePageInfo() {
  pageInfo.textContent = `Pagina ${pageNum} / ${pdfDoc.numPages}`;
  bookmarkBtn.textContent = bookmarkSet.has(pageNum) ? "Remover marcador" : "Marcar pagina";
}

async function renderPage(num) {
  rendering = true;
  const page = await pdfDoc.getPage(num);
  const baseViewport = page.getViewport({ scale: 1 });

  // Exibe uma pagina por vez, em pe (retrato), ajustando ao card sem rolagem.
  const maxWidth = Math.max(Math.min(pdfCard.clientWidth - 28, 920), 280);
  const fullscreenHeightRatio = isFullscreenMode() ? 0.88 : 0.72;
  const maxHeight = Math.max(Math.min(window.innerHeight * fullscreenHeightRatio, 1120), 360);
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
  saveProgress();
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function animatePageTurn(direction) {
  if (animating) return;
  if (canvas.width === 0 || canvas.height === 0) return;
  animating = true;

  flipCanvas.width = canvas.width;
  flipCanvas.height = canvas.height;
  flipCtx.clearRect(0, 0, flipCanvas.width, flipCanvas.height);
  flipCtx.drawImage(canvas, 0, 0);

  pdfWrapper.classList.remove("flip-next", "flip-prev");
  pdfWrapper.classList.add("is-turning", direction === "prev" ? "flip-prev" : "flip-next");
  await wait(40);
}

function finishPageTurnAnimation() {
  pdfWrapper.classList.remove("is-turning", "flip-next", "flip-prev");
  animating = false;
}

async function queueRenderPage(num, direction = "next") {
  if (num < 1 || !pdfDoc || num > pdfDoc.numPages) return;
  if (rendering || animating) {
    pagePending = { num, direction };
    return;
  }
  await animatePageTurn(direction);
  await wait(170);
  await renderPage(num);
  await wait(240);
  finishPageTurnAnimation();
  if (pagePending !== null) {
    const pending = { ...pagePending };
    pagePending = null;
    queueRenderPage(pending.num, pending.direction);
  }
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

async function toggleFullscreen() {
  try {
    if (isFullscreenMode()) {
      await document.exitFullscreen();
      return;
    }
    sidePanelBeforeFullscreen = sidePanelCollapsed;
    setSidePanelCollapsed(true);
    await document.documentElement.requestFullscreen();
  } catch (err) {
    // Silencioso para evitar bloquear leitura em navegadores restritivos.
  }
}

nextBtn.addEventListener("click", () => queueRenderPage(pageNum + 1, "next"));
prevBtn.addEventListener("click", () => queueRenderPage(pageNum - 1, "prev"));
bookmarkBtn.addEventListener("click", toggleBookmark);
highlightBtn.addEventListener("click", saveHighlight);
toggleSidePanelBtn?.addEventListener("click", () => setSidePanelCollapsed(!sidePanelCollapsed));
zoomOutBtn?.addEventListener("click", () => setZoom(zoomLevel - 0.1));
zoomInBtn?.addEventListener("click", () => setZoom(zoomLevel + 0.1));
zoomResetBtn?.addEventListener("click", () => setZoom(1));
fullscreenBtn?.addEventListener("click", toggleFullscreen);

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
  if (e.key === "ArrowLeft") queueRenderPage(pageNum - 1, "prev");
  if (e.key === "ArrowRight") queueRenderPage(pageNum + 1, "next");
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
});

window.addEventListener("resize", () => {
  if (!pdfDoc) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    renderPage(pageNum);
  }, 150);
});

pdfjsLib.getDocument(pdfUrl).promise.then((pdf) => {
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
