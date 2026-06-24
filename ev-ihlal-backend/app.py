"""FastAPI uygulaması — bağımlılıkları bağlar, olay tetiğini ve panoyu sunar.

Çalıştır:
  cd ev-ihlal-backend
  python app.py            (veya: uvicorn app:app --port 8090)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from config import Settings
from adapters.camera_isapi import build_camera
from adapters.event_store_sqlite import SqliteEventStore
from adapters.notifier_log import LogNotifier
from adapters.storage_local import LocalObjectStorage
from adapters.telemetry_mock import MockTelemetry
from adapters.uplink_local import LocalUplink
from forwarder import Forwarder
from orchestration import ViolationEngine
from retention import RetentionCleaner
from ingest import AlarmIngest
from dashboard import render_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("evihlal.app")


class Container:
    """Bağımlılık kabı — tüm adaptörler tek yerde, config'e göre seçilir (mock↔gerçek)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # --- arayüz → implementasyon seçimi (tek satırda takılıp çıkar) ---
        self.telemetry = MockTelemetry(settings.telemetry_default_status)   # Faz 1: mock
        self.camera = build_camera(settings)                                # isapi | mock
        self.storage = LocalObjectStorage(settings.images_dir)              # Faz 1: yerel
        self.store = SqliteEventStore(settings.db_path)                     # Faz 1: SQLite
        self.notifier = LogNotifier()                                       # Faz 1: log
        self.uplink = LocalUplink()                                         # Faz 1: yerel merkez

        self.forwarder = Forwarder(settings, self.store, self.uplink)
        self.retention = RetentionCleaner(settings, self.store, self.storage)
        self.engine = ViolationEngine(
            settings, self.telemetry, self.camera, self.storage,
            self.store, self.notifier, self.forwarder,
        )


SETTINGS = Settings.from_env()
C = Container(SETTINGS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("EV ihlal backend başlıyor | kamera=%s | grace=%.0fs | telemetri=mock",
             SETTINGS.camera_mode, SETTINGS.grace_period_sec)
    tasks = [
        asyncio.create_task(C.forwarder.run_forever()),
        asyncio.create_task(C.retention.run_forever()),
    ]
    # Kamera ISAPI alarm akışını dinle (gerçek kamera + açıksa) -> otomatik tetik
    ingest = None
    if SETTINGS.camera_mode == "isapi" and SETTINGS.event_stream_enabled:
        ingest = AlarmIngest(SETTINGS, C.camera, C.engine, asyncio.get_running_loop())
        ingest.start()
    else:
        log.info("ISAPI ingest KAPALI (camera_mode=%s, event_stream_enabled=%s) "
                 "— olaylar manuel tetiklenir.", SETTINGS.camera_mode,
                 SETTINGS.event_stream_enabled)
    try:
        yield
    finally:
        if ingest:
            ingest.stop()
        C.engine.cancel_all()
        for t in tasks:
            t.cancel()


app = FastAPI(title="EV İhlal Backend — Faz 1", lifespan=lifespan)


# ---- istek modelleri ----
class OccupancyBody(BaseModel):
    station_id: str
    source: str = "manual"


class TelemetryMockBody(BaseModel):
    status: str
    station_id: Optional[str] = None   # None -> varsayılanı değiştir


# ---- olay tetikleri ----
@app.post("/api/events/occupancy")
async def occupancy(body: OccupancyBody):
    """İşgal olayı (gerçek kamera alarmı yerine Faz 1 manuel/sim tetik). grace geri sayımı başlar."""
    result = await C.engine.on_occupancy_event(body.station_id, body.source)
    return {"station_id": body.station_id, "result": result,
            "grace_period_sec": SETTINGS.grace_period_sec}


@app.post("/api/events/occupancy/now")
async def occupancy_now(body: OccupancyBody):
    """Demo: geri sayımı atla, hemen değerlendir."""
    event = await C.engine.evaluate(body.station_id, body.source)
    if event is None:
        return {"violation": False, "reason": "ihlal yok / debounce"}
    return {"violation": True, "event_id": event.id,
            "status": event.telemetry_status.value, "image_key": event.image_key}


# ---- telemetri mock kontrolü (demo) ----
@app.post("/api/telemetry/mock")
async def set_telemetry(body: TelemetryMockBody):
    if not isinstance(C.telemetry, MockTelemetry):
        raise HTTPException(400, "Telemetri mock değil.")
    if body.station_id:
        s = C.telemetry.set_status(body.station_id, body.status)
        return {"station_id": body.station_id, "status": s.value}
    s = C.telemetry.set_default(body.status)
    return {"default_status": s.value}


# ---- olaylar / medya / pano ----
@app.get("/api/events")
async def list_events(limit: int = 100):
    evs = C.store.list(limit)
    return JSONResponse([{
        "id": e.id, "station_id": e.station_id,
        "detected_at": e.detected_at.isoformat() if e.detected_at else None,
        "status": e.telemetry_status.value, "state": e.state.value,
        "source": e.source, "image_key": e.image_key,
        "forwarded_at": e.forwarded_at.isoformat() if e.forwarded_at else None,
        "note": e.note,
    } for e in evs])


@app.get("/media/{key:path}")
async def media(key: str):
    data = C.storage.get_bytes(key)
    if data is None:
        raise HTTPException(404, "Görsel yok (silinmiş olabilir — retention).")
    return Response(content=data, media_type="image/jpeg")


@app.get("/health")
async def health():
    return {"ok": True, "camera_mode": SETTINGS.camera_mode}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return render_dashboard(C.store.list(50), SETTINGS)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=SETTINGS.host, port=SETTINGS.port,
                timeout_graceful_shutdown=3)
