"""Ingest — kamera ISAPI alarm akışını dinler ve ihlal motoruna besler.

Akış arka plan thread'inde (bloklayan HTTP long-poll) çalışır; intrusion olayı gelince
asyncio motoruna thread-safe biçimde on_occupancy_event çağrısı planlanır.

Bu, Faz 1'de bırakılan 'kamera olayı -> backend tetik' seam'inin gerçek implementasyonu.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from config import Settings
from interfaces import CameraClient
from orchestration import ViolationEngine

log = logging.getLogger("evihlal.ingest")


class AlarmIngest:
    def __init__(self, settings: Settings, camera: CameraClient,
                 engine: ViolationEngine, loop: asyncio.AbstractEventLoop) -> None:
        self.s = settings
        self.camera = camera
        self.engine = engine
        self.loop = loop
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="isapi-ingest",
                                        daemon=True)
        self._thread.start()
        log.info("ISAPI ingest başladı | istasyon=%s | olay tipleri=%s",
                 self.s.station_id, self.s.intrusion_event_types)

    def _run(self) -> None:
        try:
            for ev in self.camera.event_stream():
                if self._stop.is_set():
                    break
                etype = ev.get("eventType", "").lower()
                estate = ev.get("eventState", "active").lower()
                if etype not in self.s.intrusion_event_types:
                    continue
                if estate == "inactive":          # hedef bölgeden ÇIKTI → sayımı iptal et
                    asyncio.run_coroutine_threadsafe(
                        self.engine.on_clear_event(self.s.station_id), self.loop)
                    continue
                log.info("📷 ISAPI alarm: %s (%s) -> işgal olayı (istasyon=%s)",
                         etype, estate, self.s.station_id)
                # asyncio motoruna thread-safe çağrı
                asyncio.run_coroutine_threadsafe(
                    self.engine.on_occupancy_event(self.s.station_id,
                                                   source=f"isapi:{etype}"),
                    self.loop,
                )
        except Exception as exc:
            log.error("Ingest döngüsü beklenmedik şekilde durdu: %s", exc)

    def stop(self) -> None:
        self._stop.set()
