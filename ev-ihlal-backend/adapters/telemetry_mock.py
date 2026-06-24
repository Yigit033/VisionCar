"""Mock telemetri — Faz 1. 'Şarj alıyor mu?' ground truth'unu taklit eder.

Varsayılan bir durum döndürür; istasyon bazında çalışma anında override edilebilir
(demo/test için). Faz 3'te bu adaptör gerçek OCPP/CSMS/Modbus adaptörüyle değişir;
arayüz (TelemetryProvider) aynı kalır.
"""
from __future__ import annotations

import threading

from interfaces import TelemetryProvider
from models import ChargingStatus, TelemetryReading


class MockTelemetry(TelemetryProvider):
    def __init__(self, default_status: str = "NOT_CHARGING") -> None:
        self._default = ChargingStatus.parse(default_status)
        self._overrides: dict[str, ChargingStatus] = {}
        self._lock = threading.Lock()

    def get_charging_status(self, station_id: str) -> TelemetryReading:
        with self._lock:
            status = self._overrides.get(station_id, self._default)
        return TelemetryReading(
            station_id=station_id,
            status=status,
            raw={"source": "mock", "default": self._default.value},
        )

    # ---- demo/test yardımcıları (gerçek adaptörde olmayacak) ----
    def set_status(self, station_id: str, status: str) -> ChargingStatus:
        s = ChargingStatus.parse(status)
        with self._lock:
            self._overrides[station_id] = s
        return s

    def set_default(self, status: str) -> ChargingStatus:
        with self._lock:
            self._default = ChargingStatus.parse(status)
        return self._default
