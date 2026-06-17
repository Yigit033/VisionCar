"""Çift yönlü (double-sided) debounce — tek kare titremelerine karşı stabil durum.

Mantık (ardışık kare sayımı):
  - ham sinyal True geldikçe up_count artar, down_count sıfırlanır.
  - ham sinyal False geldikçe down_count artar, up_count sıfırlanır.
  - PASİF durumdayken up_count >= activation olunca -> AKTİF.
  - AKTİF durumdayken down_count >= deactivation olunca -> PASİF.

Böylece duruma geçmek için 'activation' kadar, durumdan çıkmak için 'deactivation'
kadar tutarlı kare gerekir; anlık tek-kare gürültüsü durumu değiştirmez.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DebounceStatus:
    active: bool
    up_count: int
    down_count: int
    # bar için: hangi geçişe ne kadar yakınız (0..1) ve yön ("activation"/"deactivation")
    progress: float
    progress_mode: str


class DoubleSidedDebounce:
    def __init__(self, activation: int = 30, deactivation: int = 30,
                 start_active: bool = False) -> None:
        if activation < 1 or deactivation < 1:
            raise ValueError("activation/deactivation >= 1 olmalı")
        self.activation = activation
        self.deactivation = deactivation
        self._active = start_active
        self._up = 0
        self._down = 0

    @property
    def active(self) -> bool:
        return self._active

    def update(self, raw: bool) -> DebounceStatus:
        """Ham sinyali işle, debounce edilmiş durumu döndür."""
        if raw:
            self._up += 1
            self._down = 0
        else:
            self._down += 1
            self._up = 0

        if not self._active and self._up >= self.activation:
            self._active = True
            self._up = 0
        elif self._active and self._down >= self.deactivation:
            self._active = False
            self._down = 0

        return self._status()

    def _status(self) -> DebounceStatus:
        if self._active:
            # AKTİF: pasife düşmeye ne kadar kaldı (down_count / deactivation)
            frac = min(1.0, self._down / self.deactivation)
            mode = "deactivation"
        else:
            # PASİF: aktife geçmeye ne kadar kaldı (up_count / activation)
            frac = min(1.0, self._up / self.activation)
            mode = "activation"
        return DebounceStatus(active=self._active, up_count=self._up,
                              down_count=self._down, progress=frac,
                              progress_mode=mode)

    def reset(self, start_active: bool = False) -> None:
        self._active = start_active
        self._up = 0
        self._down = 0
