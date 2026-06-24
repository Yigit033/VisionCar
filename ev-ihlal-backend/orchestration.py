"""İhlal motoru — OTURUM (occupancy session) tabanlı orkestrasyon.

Model (bir istasyon için):
  - VCA 'active' (hedef bölgede) → işgal başlar. Aktif oturum yoksa grace_period sayımı.
  - Grace dolunca telemetri (ground truth) sorulur:
      * CHARGING/PREPARING (ihlal değil) → olay yok, oturum AÇILMAZ; sonraki active'te
        tekrar sorulur (şarj bitip park devam ederse o zaman yakalanır).
      * aksi (ihlal) → snapshot + DB + bildirim + forward; OTURUM AÇILIR (bu işgal raporlandı).
  - Oturum AÇIKKEN gelen tekrar active'ler YENİ olay üretmez (aynı araç = tek olay).
      * repeat_notify_sec > 0 ise o aralıkla 'süregelen ihlal' re-kanıtı üretilir.
  - VCA 'inactive' → hedef ayrıldı; vacancy_grace_sec içinde dönmezse OTURUM KAPANIR →
    istasyon sıradaki araç için hazır. (Kısa VCA titremesi oturumu kapatmaz.)
  - Sonuç: aynı araç 10 dk dursa TEK olay; A çıkıp B girince B için YENİ olay.

Bloklayan I/O (snapshot/dosya/DB) çok-istasyonlu çalışmada loop'u durdurmasın diye
ayrı thread'e taşınır. Karar mantığı görselleştirmeden bağımsızdır.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
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

        self._present: dict[str, bool] = {}          # VCA durumu: hedef şu an bölgede mi
        self._session_active: dict[str, bool] = {}    # bu işgal için olay kaydedildi mi
        self._last_incident_at: dict[str, object] = {}  # son olay zamanı (repeat_notify için)
        self._pending: dict[str, asyncio.Task] = {}   # grace geri sayımı (olay öncesi)
        self._vacancy: dict[str, asyncio.Task] = {}    # boşalma doğrulama sayacı

    # ---- olay girişi (VCA active) --------------------------------------
    async def on_occupancy_event(self, station_id: str, source: str = "manual") -> str:
        """İşgal olayı (VCA 'active')."""
        self._present[station_id] = True
        self._cancel_vacancy(station_id)             # hedef döndü/duruyor → boşalmayı iptal et

        # Oturum zaten açık (bu araç için olay kaydedilmiş) → yeni olay yok.
        if self._session_active.get(station_id):
            if self.s.repeat_notify_sec > 0 and self._repeat_due(station_id):
                if not self._has_pending(station_id):
                    self._pending[station_id] = asyncio.create_task(
                        self._countdown(station_id, source))
                    return "repeat_scheduled"
            return "session_active"

        if self._has_pending(station_id):
            return "already_pending"                 # grace zaten sürüyor
        self._pending[station_id] = asyncio.create_task(
            self._countdown(station_id, source))
        log.info("İşgal olayı: istasyon=%s kaynak=%s — %.0fs geri sayım başladı",
                 station_id, source, self.s.grace_period_sec)
        return "scheduled"

    # ---- hedef ayrıldı (VCA inactive) ----------------------------------
    async def on_clear_event(self, station_id: str) -> None:
        """Hedef bölgeden ayrıldı: olay-öncesi sayımı iptal et + boşalmayı doğrula."""
        self._present[station_id] = False
        task = self._pending.get(station_id)
        if task and not task.done():
            task.cancel()                            # grace içinde ayrıldı → ihlal YOK
            log.info("Hedef AYRILDI (inactive): istasyon=%s — bekleyen sayım iptal, "
                     "ihlal yok.", station_id)
        # Oturumu hemen kapatma; kısa titremeyi elemek için vacancy_grace_sec bekle.
        self._schedule_vacancy_close(station_id)

    # ---- iç: geri sayım + değerlendirme --------------------------------
    async def _countdown(self, station_id: str, source: str) -> None:
        try:
            await asyncio.sleep(self.s.grace_period_sec)
            await self.evaluate(station_id, source)
        except asyncio.CancelledError:
            pass
        finally:
            self._pending.pop(station_id, None)

    async def evaluate(self, station_id: str,
                       source: str = "manual") -> Optional[ViolationEvent]:
        """Karar: hâlâ orada + telemetri 'şarj yok' ise ihlal kaydet. (Testten de çağrılır.)"""
        if not self._present.get(station_id, True):
            log.info("Karar anında hedef YOK (grace içinde ayrılmış): istasyon=%s — "
                     "olay yok.", station_id)
            return None

        reading = self.telemetry.get_charging_status(station_id)
        status = reading.status
        if status.value in self.s.non_violation_statuses:
            log.info("İhlal YOK: istasyon=%s durum=%s — oturum açılmadı.",
                     station_id, status.value)
            return None

        # --- İHLAL: kanıt yakala (bloklayan I/O thread'e) ---
        try:
            image = await asyncio.to_thread(self.camera.snapshot, station_id)
        except Exception as exc:
            log.error("Snapshot başarısız (istasyon=%s): %s", station_id, exc)
            image, key, uri = None, None, None
        else:
            now = utcnow()
            key = f"{station_id}/{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
            uri = await asyncio.to_thread(self.storage.put, key, image)

        event = ViolationEvent(
            station_id=station_id, detected_at=utcnow(), telemetry_status=status,
            image_key=key, image_uri=uri, source=source, state=EventState.OPEN,
            note="" if image else "snapshot alinamadi",
        )
        event = await asyncio.to_thread(self.store.save, event)   # outbox (önce yerele)
        try:
            self.notifier.notify(event)
        except Exception as exc:
            log.error("Bildirim hatası: %s", exc)
        if self.forwarder:
            self.forwarder.enqueue(event)

        # Oturumu aç: bu işgal raporlandı (sıradaki active'ler tekrar olay üretmez).
        self._session_active[station_id] = True
        self._last_incident_at[station_id] = utcnow()
        log.warning("İHLAL kaydedildi: olay#%s istasyon=%s durum=%s (oturum AÇIK)",
                    event.id, station_id, status.value)
        return event

    # ---- iç: boşalma doğrulama (oturum kapatma) ------------------------
    def _schedule_vacancy_close(self, station_id: str) -> None:
        self._cancel_vacancy(station_id)
        self._vacancy[station_id] = asyncio.create_task(self._vacancy_close(station_id))

    async def _vacancy_close(self, station_id: str) -> None:
        try:
            await asyncio.sleep(self.s.vacancy_grace_sec)
            if not self._present.get(station_id, False):
                if self._session_active.get(station_id):
                    log.info("Oturum KAPANDI: istasyon=%s boşaldı (>%.0fs) — sıradaki "
                             "araç için hazır.", station_id, self.s.vacancy_grace_sec)
                self._session_active[station_id] = False
                self._last_incident_at.pop(station_id, None)
        except asyncio.CancelledError:
            pass
        finally:
            self._vacancy.pop(station_id, None)

    def _cancel_vacancy(self, station_id: str) -> None:
        t = self._vacancy.get(station_id)
        if t and not t.done():
            t.cancel()

    # ---- yardımcılar ----------------------------------------------------
    def _has_pending(self, station_id: str) -> bool:
        t = self._pending.get(station_id)
        return bool(t and not t.done())

    def _repeat_due(self, station_id: str) -> bool:
        last = self._last_incident_at.get(station_id)
        if last is None:
            return True
        return (utcnow() - last).total_seconds() >= self.s.repeat_notify_sec

    def cancel_all(self) -> None:
        for d in (self._pending, self._vacancy):
            for task in d.values():
                if not task.done():
                    task.cancel()
            d.clear()
