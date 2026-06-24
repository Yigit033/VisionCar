"""Yerel uplink — Faz 1 'merkez' tarafı (store-and-forward hedefi).

Faz 1'de merkez yereldir; bu uplink başarıyla 'iletildi' kabul eder (no-op).
Ama desen kurulu: olay önce yerele yazılır, sonra Forwarder bunu uplink ile gönderir.
Faz 2'de bu sınıf gerçek bulut uplink ile değişir; uplink kopsa send() exception
fırlatır ve olay outbox'ta retry'lanır.
"""
from __future__ import annotations

import logging

from interfaces import Uplink
from models import ViolationEvent

log = logging.getLogger("evihlal.uplink")


class LocalUplink(Uplink):
    def send(self, event: ViolationEvent) -> None:
        # Faz 1: merkez yerel → her zaman başarılı. (Hata simülasyonu istenirse
        # buraya geçici bir raise eklenip retry deseni gözlemlenebilir.)
        log.info("⇪ uplink: olay#%s merkeze iletildi (yerel).", event.id)
