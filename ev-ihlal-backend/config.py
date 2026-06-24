"""Tüm ayarlar tek yerden — .env / ortam değişkeninden okunur. Sırlar koda gömülmez.

Faz 2/3'e hazır: yeni dış bağımlılıklar (S3 anahtarları, OCPP endpoint'i) buraya
ortam değişkeni olarak eklenir; kodun geri kalanı Settings üzerinden okur.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # python-dotenv yoksa salt ortam değişkeni
    pass

BASE_DIR = Path(__file__).resolve().parent


def _str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


@dataclass
class Settings:
    # kamera
    camera_mode: str = "isapi"          # isapi | mock
    camera_ip: str = "192.168.137.1"
    camera_user: str = "admin"
    camera_password: str = ""           # ENV only
    camera_channel: str = "101"
    camera_timeout_sec: float = 5.0

    # kurallar (oturum modeli)
    grace_period_sec: float = 90.0          # tetikten ihlal kararına kadar bekleme
    vacancy_grace_sec: float = 15.0         # hedef bu kadar süre dönmezse oturum kapanır
    repeat_notify_sec: float = 0.0          # 0=oturum başına tek olay; >0=süregelen re-kanıt aralığı
    non_violation_statuses: tuple[str, ...] = ("CHARGING", "PREPARING")

    # telemetri (mock)
    telemetry_default_status: str = "NOT_CHARGING"

    # ISAPI alarm akışı (kamera olayı -> otomatik tetik)
    event_stream_enabled: bool = True
    station_id: str = "ST-01"               # bu (tek) kameranın eşlendiği istasyon
    # Hikvision olay tipleri: intrusion=fielddetection, line=linedetection,
    # region giriş=regionEntrance. İhlal tetiği için hangileri sayılacak:
    intrusion_event_types: tuple[str, ...] = ("fielddetection",)

    # saklama / forward / retention
    data_dir: Path = field(default_factory=lambda: BASE_DIR / "data")
    forward_interval_sec: float = 10.0
    forward_max_retries: int = 5
    retention_days: float = 30.0
    retention_interval_sec: float = 3600.0

    # sunucu
    host: str = "127.0.0.1"
    port: int = 8090

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "events.db"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            camera_mode=_str("CAMERA_MODE", "isapi").lower(),
            camera_ip=_str("CAMERA_IP", "192.168.137.1"),
            camera_user=_str("CAMERA_USER", "admin"),
            camera_password=_str("CAMERA_PASSWORD", ""),
            camera_channel=_str("CAMERA_CHANNEL", "101"),
            camera_timeout_sec=_float("CAMERA_TIMEOUT_SEC", 5.0),
            grace_period_sec=_float("GRACE_PERIOD_SEC", 90.0),
            vacancy_grace_sec=_float("VACANCY_GRACE_SEC", 15.0),
            repeat_notify_sec=_float("REPEAT_NOTIFY_SEC", 0.0),
            non_violation_statuses=_csv("NON_VIOLATION_STATUSES",
                                        ("CHARGING", "PREPARING")),
            telemetry_default_status=_str("TELEMETRY_DEFAULT_STATUS",
                                          "NOT_CHARGING").upper(),
            event_stream_enabled=_str("EVENT_STREAM_ENABLED", "true").lower()
            in ("1", "true", "yes", "on"),
            station_id=_str("STATION_ID", "ST-01"),
            intrusion_event_types=tuple(
                s.strip().lower() for s in
                _str("INTRUSION_EVENT_TYPES", "fielddetection").split(",") if s.strip()),
            data_dir=Path(_str("DATA_DIR", str(BASE_DIR / "data"))),
            forward_interval_sec=_float("FORWARD_INTERVAL_SEC", 10.0),
            forward_max_retries=_int("FORWARD_MAX_RETRIES", 5),
            retention_days=_float("RETENTION_DAYS", 30.0),
            retention_interval_sec=_float("RETENTION_INTERVAL_SEC", 3600.0),
            host=_str("HOST", "127.0.0.1"),
            port=_int("PORT", 8090),
        )
