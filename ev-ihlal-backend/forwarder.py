"""Store-and-forward — olaylar önce yerele yazılır, sonra merkeze iletilir.

Outbox = DB'deki state=OPEN olaylar. Worker periyodik olarak bunları uplink ile
gönderir; başarılıysa FORWARDED'a çeker, başarısızsa deneme sayısını artırır ve bir
sonraki turda tekrar dener (retry). Faz 2'de uplink kopsa olaylar burada birikir ve
bağlantı gelince iletilir — dayanıklılık bu desenden gelir.
"""
from __future__ import annotations

import asyncio
import logging

from config import Settings
from interfaces import EventStore, Uplink
from models import ViolationEvent, utcnow

log = logging.getLogger("evihlal.forwarder")


class Forwarder:
    def __init__(self, settings: Settings, store: EventStore, uplink: Uplink) -> None:
        self.s = settings
        self.store = store
        self.uplink = uplink

    def enqueue(self, event: ViolationEvent) -> None:
        # Kuyruk = DB'deki OPEN olaylar; ayrı bir yapı gerekmez. Sadece işaretle.
        log.info("Outbox'a eklendi: olay#%s", event.id)

    def process_once(self) -> int:
        """Bekleyen olayları bir kez işle; iletilen sayısını döndür."""
        pending = self.store.list_pending_forward()
        sent = 0
        for ev in pending:
            if ev.forward_attempts >= self.s.forward_max_retries:
                continue  # max deneme aşıldı — operatör müdahalesine bırak
            try:
                self.uplink.send(ev)
            except Exception as exc:
                self.store.bump_forward_attempt(ev.id)
                log.warning("Forward başarısız (olay#%s, deneme arttı): %s", ev.id, exc)
            else:
                self.store.mark_forwarded(ev.id, utcnow())
                sent += 1
        return sent

    async def run_forever(self) -> None:
        log.info("Forwarder döngüsü başladı (her %.0fs).", self.s.forward_interval_sec)
        while True:
            try:
                self.process_once()
            except Exception as exc:
                log.error("Forwarder turu hata: %s", exc)
            await asyncio.sleep(self.s.forward_interval_sec)
