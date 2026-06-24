"""İhlal motoru — orkestrasyon. Timer + debounce + ihlal kararı.

Akış (her istasyon için):
  1) İşgal olayı gelir (gerçek kamera alarmı ya da Faz 1 manuel/sim tetik).
  2) O istasyon için grace_period geri sayımı başlar (zaten sayıyorsa yeni tetik yok sayılır).
  3) Süre dolunca telemetri (ground truth) sorulur.
  4) Durum 'ihlal değil' kümesindeyse (ör. CHARGING): olay sessizce kapanır, bildirim yok.
  5) Aksi halde İHLAL: snapshot (gerçek kamera) -> storage -> olay DB'ye yazılır (outbox)
     -> bildirim -> forward kuyruğuna alınır.
Debounce: aynı istasyon için debounce_window içinde tek ihlal (DB tabanlı, restart'a dayanıklı).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Optional

from config import Settings
from interfaces import (CameraClient, EventStore, Notifier, ObjectStorage,
                        TelemetryProvider)
from models import EventState, ViolationEvent, utcnow

log = logging.getLogger("evihlal.engine")


class ViolationEngine:
    def __init__(self, settings: Settings, telemetry: TelemetryProvider,
                 camera: CameraClient, storage: ObjectStorage, store: EventStore,
                 notifier: Notifier, forwarder=None) -> None:
        self.s = settings
        self.telemetry = telemetry
        self.camera = camera
        self.storage = storage
        self.store = store
        self.notifier = notifier
        self.forwarder = forwarder
        self._pending: dict[str, asyncio.Task] = {}

    # ---- olay girişi ----------------------------------------------------
    async def on_occupancy_event(self, station_id: str, source: str = "manual") -> str:
        """İşgal olayı: grace_period geri sayımını başlatır."""
        task = self._pending.get(station_id)
        if task and not task.done():
            return "already_pending"          # süregelen işgal — yeni sayaç yok
        if self._debounced(station_id):
            return "debounced"
        self._pending[station_id] = asyncio.create_task(
            self._countdown(station_id, source))
        log.info("İşgal olayı: istasyon=%s kaynak=%s — %.0fs geri sayım başladı",
                 station_id, source, self.s.grace_period_sec)
        return "scheduled"

    async def _countdown(self, station_id: str, source: str) -> None:
        try:
            await asyncio.sleep(self.s.grace_period_sec)
            await self.evaluate(station_id, source)
        except asyncio.CancelledError:
            pass
        finally:
            self._pending.pop(station_id, None)

    # ---- ihlal kararı ---------------------------------------------------
    async def evaluate(self, station_id: str,
                       source: str = "manual") -> Optional[ViolationEvent]:
        """Telemetriyi sorar; ihlalse kanıt üretir. (Test için doğrudan da çağrılır.)"""
        reading = self.telemetry.get_charging_status(station_id)
        status = reading.status

        if status.value in self.s.non_violation_statuses:
            log.info("İhlal YOK: istasyon=%s durum=%s — olay sessizce kapandı.",
                     station_id, status.value)
            return None

        if self._debounced(station_id):
            log.info("Debounce: istasyon=%s — yakın zamanda ihlal var, tek kayıt.",
                     station_id)
            return None

        # --- İHLAL: kanıt yakala (gerçek kamera snapshot) ---
        try:
            image = self.camera.snapshot(station_id)
        except Exception as exc:                       # kamera hatası olayı düşürmesin
            log.error("Snapshot başarısız (istasyon=%s): %s", station_id, exc)
            image, key, uri = None, None, None
        else:
            now = utcnow()
            key = f"{station_id}/{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
            uri = self.storage.put(key, image)

        event = ViolationEvent(
            station_id=station_id,
            detected_at=utcnow(),
            telemetry_status=status,
            image_key=key,
            image_uri=uri,
            source=source,
            state=EventState.OPEN,
            note="" if image else "snapshot alinamadi",
        )
        # Store-and-forward 1. adım: ÖNCE yerele yaz (outbox).
        event = self.store.save(event)
        # Bildirim (kendi backend'imizden).
        try:
            self.notifier.notify(event)
        except Exception as exc:
            log.error("Bildirim hatası: %s", exc)
        # 2. adım: merkeze gönderim kuyruğu (retry'lı, asenkron).
        if self.forwarder:
            self.forwarder.enqueue(event)
        log.warning("İHLAL kaydedildi: olay#%s istasyon=%s durum=%s",
                    event.id, station_id, status.value)
        return event

    # ---- debounce -------------------------------------------------------
    def _debounced(self, station_id: str) -> bool:
        last = self.store.last_violation_at(station_id)
        if last is None:
            return False
        return (utcnow() - last) < timedelta(seconds=self.s.debounce_window_sec)

    # ---- kapanış --------------------------------------------------------
    def cancel_all(self) -> None:
        for task in self._pending.values():
            task.cancel()
        self._pending.clear()
