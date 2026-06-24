"""Alan modelleri (domain) — enum'lar ve veri yapıları. Dış bağımlılık yok.

ÖNEMLİ ayrım: "doluluk" kameradan gelir; "şarj alıyor mu" telemetriden (ground truth).
İhlal kararı bool değil, OCPP'ye yakın bir DURUM üzerinden verilir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChargingStatus(str, Enum):
    """OCPP'ye yakın şarj durumları (telemetri ground truth)."""
    CHARGING = "CHARGING"          # aktif şarj — ihlal YOK
    PREPARING = "PREPARING"        # takılı, başlamak üzere — (varsayılan) ihlal yok
    SUSPENDED = "SUSPENDED"        # askıya alınmış (EV/EVSE) — ihlal
    FINISHING = "FINISHING"        # bitiyor — ihlal (yer hâlâ işgal)
    NOT_CHARGING = "NOT_CHARGING"  # takılı değil / şarj yok — ihlal
    FAULTED = "FAULTED"            # arıza — ihlal
    UNKNOWN = "UNKNOWN"            # telemetri okunamadı

    @classmethod
    def parse(cls, value: str) -> "ChargingStatus":
        try:
            return cls(value.strip().upper())
        except (ValueError, AttributeError):
            return cls.UNKNOWN


@dataclass
class TelemetryReading:
    station_id: str
    status: ChargingStatus
    at: datetime = field(default_factory=utcnow)
    raw: dict[str, Any] = field(default_factory=dict)   # adaptöre özgü ham veri


class EventState(str, Enum):
    OPEN = "OPEN"                       # ihlal yerele yazıldı, merkeze gönderilmedi (outbox)
    FORWARDED = "FORWARDED"             # merkeze iletildi
    RETENTION_PURGED = "RETENTION_PURGED"  # KVKK: görsel silindi, kayıt anonimleşti


@dataclass
class ViolationEvent:
    station_id: str
    detected_at: datetime
    telemetry_status: ChargingStatus
    image_key: Optional[str] = None     # storage anahtarı (DB'de sadece link/yol durur)
    image_uri: Optional[str] = None     # denetim/insan için uri
    source: str = "manual"              # olay kaynağı (manual | isapi_alarm | ...)
    state: EventState = EventState.OPEN
    forward_attempts: int = 0
    forwarded_at: Optional[datetime] = None
    note: str = ""
    id: Optional[int] = None
    created_at: datetime = field(default_factory=utcnow)
