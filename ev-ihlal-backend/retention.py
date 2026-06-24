"""KVKK retention — araç görüntüsü kişisel veridir; eski kanıt görselleri otomatik silinir.

retention_days'ten eski olayların GÖRSELİ object storage'dan silinir ve DB kaydı
anonimleştirilir (image_key/uri null, state=RETENTION_PURGED). Olay kaydının kendisi
(istatistik için) kalır ama kişisel veri (görsel) kalmaz.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from config import Settings
from interfaces import EventStore, ObjectStorage
from models import utcnow

log = logging.getLogger("evihlal.retention")


class RetentionCleaner:
    def __init__(self, settings: Settings, store: EventStore,
                 storage: ObjectStorage) -> None:
        self.s = settings
        self.store = store
        self.storage = storage

    def process_once(self) -> int:
        cutoff = utcnow() - timedelta(days=self.s.retention_days)
        old = self.store.list_images_older_than(cutoff)
        purged = 0
        for ev in old:
            if ev.image_key:
                try:
                    self.storage.delete(ev.image_key)
                except Exception as exc:
                    log.error("Görsel silinemedi (olay#%s): %s", ev.id, exc)
                    continue
            self.store.mark_image_purged(ev.id)
            purged += 1
        if purged:
            log.info("Retention: %d eski görsel silindi (>%.0f gün).",
                     purged, self.s.retention_days)
        return purged

    async def run_forever(self) -> None:
        log.info("Retention döngüsü başladı (her %.0fs, %.0f gün saklama).",
                 self.s.retention_interval_sec, self.s.retention_days)
        while True:
            try:
                self.process_once()
            except Exception as exc:
                log.error("Retention turu hata: %s", exc)
            await asyncio.sleep(self.s.retention_interval_sec)
