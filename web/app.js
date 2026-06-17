// VisionCar web arayüzü — çekirdeğin ince istemcisi.
// Tüm görsel kod burada: ROI seçimi ve pulse overlay'i canvas üzerinde çizilir.
// Sunucudan gelen MJPEG sade küçültülmüş ham önizlemedir (overlay sunucuda çizilmez).

const $ = (id) => document.getElementById(id);

const els = {
  connDot: $("conn-dot"),
  res: $("st-res"), fps: $("st-fps"), rec: $("st-rec"),
  label: $("st-label"), result: $("st-result"),
  pBright: $("p-bright"), pAmp: $("p-amp"), pFreq: $("p-freq"), pCross: $("p-cross"),
  img: $("stream"), canvas: $("overlay"), wrap: $("preview-wrap"),
  roiReadout: $("roi-readout"), btnClearRoi: $("btn-clear-roi"),
  labelInput: $("label-input"),
  btnRecord: $("btn-record"), recMeta: $("rec-meta"),
  btnSnapshot: $("btn-snapshot"), snapMeta: $("snap-meta"),
  gallery: $("gallery"), btnRefreshGallery: $("btn-refresh-gallery"),
};

const ctx = els.canvas.getContext("2d");

// Paylaşılan durum
let state = null;          // son /api/state cevabı
let fullW = 0, fullH = 0;  // kameranın tam çözünürlüğü
let recording = false;

// ROI çizim durumu (canvas/görüntü piksel koordinatlarında)
let dragging = false;
let dragStart = null;   // {x, y} canvas-css piksel
let dragNow = null;

// ---- yardımcılar: koordinat eşleme ----
// Canvas CSS pikseli -> tam çözünürlük pikseli
function toFull(px, py) {
  const r = els.canvas.getBoundingClientRect();
  const fx = (px / r.width) * fullW;
  const fy = (py / r.height) * fullH;
  return [Math.round(fx), Math.round(fy)];
}
// Tam çözünürlük -> canvas CSS pikseli
function toCanvas(fx, fy) {
  const r = els.canvas.getBoundingClientRect();
  return [(fx / fullW) * r.width, (fy / fullH) * r.height];
}

function resizeCanvas() {
  const r = els.wrap.getBoundingClientRect();
  els.canvas.width = r.width;
  els.canvas.height = r.height;
}
window.addEventListener("resize", resizeCanvas);

// ---- durum çekme döngüsü ----
async function pollState() {
  try {
    const res = await fetch("/api/state");
    state = await res.json();
    applyState(state);
  } catch (e) {
    els.connDot.className = "dot off";
  }
}

function applyState(s) {
  fullW = s.resolution.width;
  fullH = s.resolution.height;

  els.connDot.className = "dot " + (s.connected ? "on" : "off");
  els.res.textContent = fullW && fullH ? `${fullW}×${fullH}` : "—";
  const fps = s.measured_fps || s.declared_fps || 0;
  els.fps.textContent = fps ? fps.toFixed(1) : "—";

  recording = s.recording.active;
  els.rec.textContent = recording
    ? `açık (${s.recording.frame_count} kare)` : "kapalı";
  els.label.textContent = recording && s.recording.label ? s.recording.label : "—";

  els.result.textContent = s.result_text || "—";
  els.result.className = s.pulse.pulsing ? "pulse"
    : (s.pulse.window_filled ? "nopulse" : "");

  els.pBright.textContent = s.pulse.brightness.toFixed(1);
  els.pAmp.textContent = s.pulse.amplitude.toFixed(1);
  els.pFreq.textContent = s.pulse.pulsing ? `${s.pulse.frequency_hz.toFixed(1)} Hz` : "—";
  els.pCross.textContent = s.pulse.crossings;

  // kayıt butonu görünümü
  els.btnRecord.textContent = recording ? "Kaydı durdur" : "Kaydı başlat";
  els.btnRecord.className = "btn " + (recording ? "recording" : "primary");

  // ROI okunması
  if (s.roi) {
    els.roiReadout.textContent =
      `ROI: x=${s.roi.x} y=${s.roi.y} w=${s.roi.w} h=${s.roi.h}`;
  } else {
    els.roiReadout.textContent = "ROI: tüm kare";
  }

  drawOverlay();
}

// ---- overlay çizimi: ROI kutusu + sürükleme bandı + pulse rozeti ----
function drawOverlay() {
  resizeCanvasIfNeeded();
  ctx.clearRect(0, 0, els.canvas.width, els.canvas.height);

  const pulsing = state && state.pulse && state.pulse.pulsing;
  const accent = pulsing ? "#46d17a" : "#5b8dff";

  // kaydedilmiş ROI
  if (state && state.roi && fullW) {
    const [x0, y0] = toCanvas(state.roi.x, state.roi.y);
    const [x1, y1] = toCanvas(state.roi.x + state.roi.w, state.roi.y + state.roi.h);
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    ctx.fillStyle = accent;
    ctx.font = "600 13px Segoe UI, sans-serif";
    ctx.fillText("ROI", x0 + 5, y0 + 16);

    // pulse rozeti
    if (state.pulse.window_filled || state.pulse.crossings) {
      const txt = pulsing
        ? `● PULSE  ~${state.pulse.frequency_hz.toFixed(1)} Hz`
        : "○ pulse yok";
      ctx.font = "600 14px Segoe UI, sans-serif";
      const tw = ctx.measureText(txt).width;
      const bx = x0, by = Math.max(0, y0 - 26);
      ctx.fillStyle = "rgba(0,0,0,.6)";
      ctx.fillRect(bx, by, tw + 14, 22);
      ctx.fillStyle = pulsing ? "#46d17a" : "#e9a13b";
      ctx.fillText(txt, bx + 7, by + 16);
    }
  }

  // aktif sürükleme bandı
  if (dragging && dragStart && dragNow) {
    const x = Math.min(dragStart.x, dragNow.x);
    const y = Math.min(dragStart.y, dragNow.y);
    const w = Math.abs(dragNow.x - dragStart.x);
    const h = Math.abs(dragNow.y - dragStart.y);
    ctx.strokeStyle = "#ffffff";
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(91,141,255,.18)";
    ctx.fillRect(x, y, w, h);
  }
}

function resizeCanvasIfNeeded() {
  const r = els.wrap.getBoundingClientRect();
  if (Math.abs(els.canvas.width - r.width) > 1 ||
      Math.abs(els.canvas.height - r.height) > 1) {
    els.canvas.width = r.width;
    els.canvas.height = r.height;
  }
}

// ---- ROI fare etkileşimi ----
function canvasPos(ev) {
  const r = els.canvas.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}
els.canvas.addEventListener("mousedown", (ev) => {
  dragging = true;
  dragStart = canvasPos(ev);
  dragNow = dragStart;
});
els.canvas.addEventListener("mousemove", (ev) => {
  if (!dragging) return;
  dragNow = canvasPos(ev);
  drawOverlay();
});
window.addEventListener("mouseup", async () => {
  if (!dragging) return;
  dragging = false;
  if (!dragStart || !dragNow) return;
  const dx = Math.abs(dragNow.x - dragStart.x);
  const dy = Math.abs(dragNow.y - dragStart.y);
  if (dx < 6 || dy < 6) { drawOverlay(); return; }  // küçük tıklamayı yok say

  const [fx0, fy0] = toFull(Math.min(dragStart.x, dragNow.x),
                            Math.min(dragStart.y, dragNow.y));
  const [fx1, fy1] = toFull(Math.max(dragStart.x, dragNow.x),
                            Math.max(dragStart.y, dragNow.y));
  const roi = { x: fx0, y: fy0, w: fx1 - fx0, h: fy1 - fy0 };
  await postJSON("/api/roi", roi);
  pollState();
});

els.btnClearRoi.addEventListener("click", async () => {
  await postJSON("/api/roi", { x: null, y: null, w: null, h: null });
  pollState();
});

// ---- kayıt ----
els.btnRecord.addEventListener("click", async () => {
  if (recording) {
    const r = await postJSON("/api/record/stop", {});
    if (r && r.directory) els.recMeta.textContent = "Kaydedildi: " + r.directory;
  } else {
    const label = els.labelInput.value.trim() || "kayit";
    const r = await postJSON("/api/record/start", { label });
    if (r && r.directory) els.recMeta.textContent = "Kayıt klasörü: " + r.directory;
  }
  pollState();
});

// ---- snapshot ----
els.btnSnapshot.addEventListener("click", async () => {
  const label = els.labelInput.value.trim() || "kayit";
  els.btnSnapshot.disabled = true;
  const r = await postJSON("/api/snapshot", { label });
  els.btnSnapshot.disabled = false;
  if (r && r.annotated_name) {
    els.snapMeta.textContent =
      `Üretildi: ${r.raw_name} + ${r.annotated_name}`;
    loadGallery();
  } else {
    els.snapMeta.textContent = "Snapshot alınamadı (kamera bağlı mı?).";
  }
});

// ---- galeri ----
async function loadGallery() {
  try {
    const res = await fetch("/api/report_shots?limit=12");
    const data = await res.json();
    if (!data.items.length) {
      els.gallery.innerHTML = '<div class="empty">Henüz rapor görseli yok.</div>';
      return;
    }
    els.gallery.innerHTML = data.items.map((it) =>
      `<a href="/report_shots/${it.annotated_name}" target="_blank" title="${it.annotated_name}">
         <img src="/report_shots/${it.annotated_name}" alt="${it.annotated_name}" />
       </a>`).join("");
  } catch (e) { /* sunucu yoksa sessiz geç */ }
}
els.btnRefreshGallery.addEventListener("click", loadGallery);

// ---- ortak ----
async function postJSON(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (e) { return null; }
}

// başlat
resizeCanvas();
els.img.addEventListener("load", resizeCanvas);
loadGallery();
pollState();
setInterval(pollState, 250);
