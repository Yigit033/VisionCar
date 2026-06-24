"""Log/konsol bildirimi — Faz 1. Bildirim KENDİ backend'imizden çıkar.

Faz 2/3'te aynı arayüzle e-posta/SMS/push/webhook adaptörleri eklenir; satıcı
bulutuna bağımlı olmadan kendi kanalımızdan gönderilir.
"""
from __future__ import annotations

import logging

from interfaces import Notifier
from models import ViolationEvent

log = logging.getLogger("evihlal.notify")


class LogNotifier(Notifier):
    def notify(self, event: ViolationEvent) -> None:
        log.warning(
            "🔔 İHLAL BİLDİRİMİ | istasyon=%s | durum=%s | zaman=%s | görsel=%s | olay#%s",
            event.station_id, event.telemetry_status.value,
            event.detected_at.isoformat() if event.detected_at else "-",
            event.image_key, event.id,
        )
