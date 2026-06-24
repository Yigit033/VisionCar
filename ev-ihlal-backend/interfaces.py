"""Dış bağımlılık ARAYÜZLERİ — mock ↔ gerçek tek satırda takılıp çıksın diye.

Her dış sistem (kamera, telemetri, depolama, olay DB, bildirim, merkez uplink) burada
soyut bir sözleşmeyle tanımlanır. Faz 1 mock/yerel implementasyonları, Faz 2/3 gerçek
implementasyonları aynı arayüzü uygular; orkestrasyon kodu değişmez.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator, Optional

from models import TelemetryReading, ViolationEvent


class TelemetryProvider(ABC):
    """'Şarj alıyor mu?' ground truth kaynağı. Faz 1: mock. Faz 3: OCPP/CSMS/Modbus."""

    @abstractmethod
    def get_charging_status(self, station_id: str) -> TelemetryReading: ...


class CameraClient(ABC):
    """Kamera. Faz 1: gerçek ISAPI snapshot (pull) + manuel/sim olay tetiği."""

    @abstractmethod
    def snapshot(self, station_id: str) -> bytes:
        """İstasyonun kamerasından TAM çözünürlüklü JPEG kare çeker (ham kanıt)."""

    def event_stream(self) -> Iterator[dict]:
        """SEAM: kameranın ISAPI alarm/event stream'i (intrusion olayları).

        Faz 1'de zorunlu değil — olay manuel/sim tetiklenebilir. Gerçek alarm
        akışına geçildiğinde bu metot uygulanır ve orkestrasyona beslenir.
        """
        raise NotImplementedError("ISAPI alarm stream Faz 1'de bağlı değil (seam).")


class ObjectStorage(ABC):
    """Kanıt görseli deposu. Faz 1: yerel klasör. Faz 2: S3 (boto3). Görsel DB'ye konmaz."""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        """Veriyi key altına yazar, erişilebilir bir uri döndürür."""

    @abstractmethod
    def get_bytes(self, key: str) -> Optional[bytes]: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class EventStore(ABC):
    """Olay veritabanı. Faz 1: SQLite. DB'de görselin yalnızca link/yolu durur."""

    @abstractmethod
    def save(self, event: ViolationEvent) -> ViolationEvent: ...

    @abstractmethod
    def get(self, event_id: int) -> Optional[ViolationEvent]: ...

    @abstractmethod
    def list(self, limit: int = 100) -> list[ViolationEvent]: ...

    @abstractmethod
    def last_violation_at(self, station_id: str) -> Optional[datetime]:
        """Debounce için: bu istasyonun en son ihlal zamanı."""

    @abstractmethod
    def list_pending_forward(self) -> list[ViolationEvent]:
        """Store-and-forward outbox: merkeze gönderilmemiş olaylar."""

    @abstractmethod
    def mark_forwarded(self, event_id: int, at: datetime) -> None: ...

    @abstractmethod
    def bump_forward_attempt(self, event_id: int) -> None: ...

    @abstractmethod
    def list_images_older_than(self, cutoff: datetime) -> list[ViolationEvent]:
        """KVKK retention: görseli silinmesi gereken eski olaylar."""

    @abstractmethod
    def mark_image_purged(self, event_id: int) -> None: ...


class Notifier(ABC):
    """Bildirim. Faz 1: log/konsol. Bildirim KENDİ backend'imizden çıkar, satıcı bulutundan değil."""

    @abstractmethod
    def notify(self, event: ViolationEvent) -> None: ...


class Uplink(ABC):
    """Store-and-forward'ın 'merkez' tarafı. Faz 1: yerel (no-op başarı).

    Faz 2'de gerçek bulut uplink olur; uplink kopsa olaylar outbox'ta retry'lanır.
    """

    @abstractmethod
    def send(self, event: ViolationEvent) -> None:
        """Başarısızsa exception fırlatır → outbox'ta kalır, sonra tekrar denenir."""
