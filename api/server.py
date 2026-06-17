"""FastAPI — çekirdeğin üstünde İNCE bir katman.

Sınırlar (İlke 1 & 2):
  - Bu katman core.Engine'i sürer; tespit/kayıt/rapor mantığı burada DEĞİL, core'da.
  - Canlı önizleme (MJPEG) yalnızca BANT GENİŞLİĞİ için küçültülüp sıkıştırılır;
    bu küçültme ham veri yoluna sızmaz — kayıt/tespit/rapor hep core'da tam çözünürlükte.
  - Önizleme üzerine ROI/pulse OVERLAY'i sunucuda çizilmez; web/ tarafında canvas ile
    çizilir (tüm görsel kod web/ içinde kalsın). MJPEG sade küçültülmüş ham önizlemedir.

Çalıştır:  python -m api.server   (veya: uvicorn api.server:app)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core import config as cfg_mod
from core.engine import Engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("visioncar.api")

CFG = cfg_mod.load_config()
PREVIEW = CFG.get("preview", {})
PREVIEW_MAX_W = int(PREVIEW.get("max_width", 960))
PREVIEW_QUALITY = int(PREVIEW.get("jpeg_quality", 70))

WEB_DIR = cfg_mod.PROJECT_ROOT / "web"
REPORT_DIR = cfg_mod.resolve_path(CFG.get("report", {}).get("output_dir",
                                                            "data/report_shots"))
REPORT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="VisionCar — Saha Test Aracı")
engine = Engine(CFG)


@app.on_event("startup")
def _startup() -> None:
    log.info("Çekirdek başlatılıyor. Config: %s",
             cfg_mod.config_path().name)
    log.info("Kaynak (gizlenmiş): %s",
             cfg_mod.redact(CFG).get("camera", {}).get("rtsp_url"))
    engine.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    engine.stop()


# ---- canlı önizleme (MJPEG) -------------------------------------------
def _make_preview_jpeg(frame) -> Optional[bytes]:
    """Ham karenin AYRI bir kopyasını küçültüp JPEG'e çevirir (sadece önizleme)."""
    h, w = frame.shape[:2]
    if w > PREVIEW_MAX_W:
        scale = PREVIEW_MAX_W / float(w)
        frame = cv2.resize(frame, (PREVIEW_MAX_W, int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame,
                           [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_QUALITY])
    return buf.tobytes() if ok else None


def _mjpeg_generator():
    boundary = b"--frame"
    target_dt = 1.0 / 20.0  # önizlemeyi ~20 fps ile sınırla
    last = 0.0
    while True:
        now = time.monotonic()
        if now - last < target_dt:
            time.sleep(0.005)
            continue
        last = now
        frame, _ = engine.camera.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        jpeg = _make_preview_jpeg(frame)
        if jpeg is None:
            continue
        yield (boundary + b"\r\n"
               b"Content-Type: image/jpeg\r\n"
               b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
               + jpeg + b"\r\n")


@app.get("/api/stream")
def stream():
    return StreamingResponse(
        _mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---- durum -------------------------------------------------------------
@app.get("/api/state")
def state():
    return JSONResponse(engine.state())


# ---- ROI ---------------------------------------------------------------
class RoiBody(BaseModel):
    # Tam çözünürlüklü piksel koordinatları. Hepsi null -> ROI temizle (tüm kare).
    x: Optional[int] = None
    y: Optional[int] = None
    w: Optional[int] = None
    h: Optional[int] = None


@app.post("/api/roi")
def set_roi(body: RoiBody):
    if None in (body.x, body.y, body.w, body.h):
        engine.set_roi(None)
        return {"roi": None}
    roi = (body.x, body.y, body.w, body.h)
    engine.set_roi(roi)
    return {"roi": {"x": roi[0], "y": roi[1], "w": roi[2], "h": roi[3]}}


# ---- kayıt -------------------------------------------------------------
class LabelBody(BaseModel):
    label: str = "kayit"


@app.post("/api/record/start")
def record_start(body: LabelBody):
    if engine.recorder.state().active:
        raise HTTPException(409, "Zaten kayıt sürüyor.")
    return engine.start_recording(body.label)


@app.post("/api/record/stop")
def record_stop():
    path = engine.stop_recording()
    if path is None:
        raise HTTPException(409, "Aktif kayıt yok.")
    return {"directory": path}


# ---- snapshot (rapor görseli) -----------------------------------------
@app.post("/api/snapshot")
def snapshot(body: LabelBody):
    shot = engine.snapshot(body.label)
    if shot is None:
        raise HTTPException(503, "Kare yok — kamera bağlı değil.")
    # web galerisinin erişebilmesi için dosya adlarını da döndür
    shot["raw_name"] = Path(shot["raw_path"]).name
    shot["annotated_name"] = Path(shot["annotated_path"]).name
    return shot


# ---- rapor galerisi ----------------------------------------------------
@app.get("/api/report_shots")
def report_shots(limit: int = 12):
    """En yeni annotated rapor görsellerini listele (galeri için)."""
    files = sorted(REPORT_DIR.glob("*_annotated.png"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for p in files[:limit]:
        items.append({
            "annotated_name": p.name,
            "raw_name": p.name.replace("_annotated.png", "_raw.png"),
        })
    return {"items": items}


# rapor görsel dosyalarını sun
app.mount("/report_shots", StaticFiles(directory=str(REPORT_DIR)),
          name="report_shots")

# web arayüzü (statik) — en sona mount: /api ve /report_shots gölgelenmez
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    srv = CFG.get("server", {})
    uvicorn.run(app, host=srv.get("host", "0.0.0.0"),
                port=int(srv.get("port", 8000)),
                # Canlı MJPEG akışı sonsuz ömürlü bir istektir; Ctrl+C'de uvicorn
                # bitmesini beklerken takılmasın diye kibar kapanma süresini sınırla.
                timeout_graceful_shutdown=3)
