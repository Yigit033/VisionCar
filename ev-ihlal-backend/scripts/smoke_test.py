"""Uçtan uca duman testi — gerçek kameraya İHTİYAÇ DUYMAZ (MockCamera).

Faz 1 kabul kriterlerini doğrular:
  1) Tetik + telemetri 'şarj yok' -> snapshot + storage + DB + bildirim + (forward).
  2) Telemetri 'şarj var' -> ihlal yok, kayıt yok.
  3) Aynı istasyon kısa sürede tekrar -> debounce (tek kayıt).
  4) Store-and-forward: olay OPEN -> forwarder -> FORWARDED.
  5) Retention: eski görsel silinir, kayıt anonimleşir.

Çalıştır:  cd ev-ihlal-backend && python scripts/smoke_test.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Settings
from adapters.camera_isapi import MockCamera
from adapters.event_store_sqlite import SqliteEventStore
from adapters.notifier_log import LogNotifier
from adapters.storage_local import LocalObjectStorage
from adapters.telemetry_mock import MockTelemetry
from adapters.uplink_local import LocalUplink
from forwarder import Forwarder
from orchestration import ViolationEngine
from retention import RetentionCleaner
from models import EventState, utcnow


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -> {detail}" if detail else ""))
    return ok


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="evihlal_"))
    s = Settings(
        camera_mode="mock", grace_period_sec=0.2, vacancy_grace_sec=0.3,
        data_dir=tmp, retention_days=0.0,  # retention testinde her şey 'eski'
    )
    telemetry = MockTelemetry("NOT_CHARGING")
    camera = MockCamera()
    storage = LocalObjectStorage(s.images_dir)
    store = SqliteEventStore(s.db_path)
    notifier = LogNotifier()
    uplink = LocalUplink()
    forwarder = Forwarder(s, store, uplink)
    engine = ViolationEngine(s, telemetry, camera, storage, store, notifier, forwarder)

    ok = True

    # 1) şarj yok -> ihlal + kanıt
    print("\n[1] Tetik + 'NOT_CHARGING' -> ihlal kaydı + kanıt görseli")
    ev = await engine.evaluate("ST-01", source="smoke")
    ok &= check("ihlal olayı üretildi", ev is not None)
    if ev:
        ok &= check("DB'ye yazıldı (id var)", ev.id is not None, f"olay#{ev.id}")
        ok &= check("görsel storage'a kondu", bool(ev.image_key) and
                    storage.exists(ev.image_key), ev.image_key or "")
        ok &= check("DB'de sadece link/yol var (görselin kendisi değil)",
                    ev.image_key is not None and len(ev.image_key) < 200)

    # 2) şarj var -> ihlal yok
    print("\n[2] 'CHARGING' -> ihlal YOK")
    telemetry.set_status("ST-02", "CHARGING")
    ev2 = await engine.evaluate("ST-02", source="smoke")
    ok &= check("şarj varken olay üretilmedi", ev2 is None)
    ok &= check("ST-02 için DB'de kayıt yok",
                store.last_violation_at("ST-02") is None)

    # 3) oturum dedup -> aynı araç durdukça TEK olay
    print("\n[3] Oturum dedup -> ST-01 oturumu açık, tekrar 'active' YENİ olay YOK")
    before = len(store.list(1000))
    res = await engine.on_occupancy_event("ST-01", source="smoke")  # aynı araç hâlâ orada
    await asyncio.sleep(s.grace_period_sec + 0.3)
    after = len(store.list(1000))
    ok &= check("açık oturumda yeni olay yok (aynı araç=tek olay)",
                before == after and res == "session_active", f"{res}, {before}->{after}")

    # 3b) A çıkar -> oturum kapanır -> YENİ araç gelir -> YENİ olay
    print("\n[3b] A ayrılır (oturum kapanır) -> yeni araç -> YENİ olay VAR")
    await engine.on_clear_event("ST-01")                 # A bölgeden çıktı
    await asyncio.sleep(s.vacancy_grace_sec + 0.3)        # boşalma doğrulansın -> oturum kapanır
    before = len(store.list(1000))
    await engine.on_occupancy_event("ST-01", source="smoke")  # yeni araç girdi
    await asyncio.sleep(s.grace_period_sec + 0.3)
    after = len(store.list(1000))
    ok &= check("yeni araç için YENİ olay üretildi", after == before + 1,
                f"{before}->{after}")

    # 4) store-and-forward
    print("\n[4] Store-and-forward -> OPEN olaylar FORWARDED olur")
    pending_before = len(store.list_pending_forward())
    sent = forwarder.process_once()
    pending_after = len(store.list_pending_forward())
    ok &= check("bekleyen olay iletildi", sent >= 1 and pending_after == 0,
                f"sent={sent}, kalan={pending_after}")
    fwd_ev = store.get(ev.id) if ev else None
    ok &= check("olay durumu FORWARDED", fwd_ev and fwd_ev.state == EventState.FORWARDED)

    # 5) retention -> eski görsel silinir, kayıt anonimleşir
    print("\n[5] Retention (retention_days=0) -> görsel silinir, kayıt anonimleşir")
    purged = RetentionCleaner(s, store, storage).process_once()
    ok &= check("en az 1 görsel silindi", purged >= 1, f"purged={purged}")
    after_ev = store.get(ev.id) if ev else None
    ok &= check("görsel diskten silindi",
                ev is not None and not storage.exists(ev.image_key))
    ok &= check("DB kaydı anonimleşti (image_key NULL, RETENTION_PURGED)",
                after_ev and after_ev.image_key is None and
                after_ev.state == EventState.RETENTION_PURGED)
    ok &= check("olay kaydı (istatistik) korundu", after_ev is not None)

    print("\n" + "=" * 50)
    print("SONUC:", "TUM KABUL KRITERLERI GECTI [OK]" if ok else "BAZI TESTLER FAIL [X]")
    print(f"Geçici çıktılar: {tmp}")
    print("=" * 50)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
