"""Şarj kararı mantığı — containment (kutu içinde merkez), IoU DEĞİL.

Tetikleme kuralı: sahnedeki HERHANGİ bir tabanca kutusunun MERKEZİ, HERHANGİ bir
araç kutusunun içindeyse 'şarj' ham sinyali True olur. Tüm tespit çiftleri gezilir;
sadece ilk kutuya bakılmaz.

Bu modül headless'tır — sadece kutu geometrisiyle çalışır, çizim/IO yapmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float = 0.0

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)


def center_inside(inner: Box, outer: Box) -> bool:
    """inner kutusunun merkezi outer kutusunun içinde mi?"""
    cx, cy = inner.center
    return (outer.x1 <= cx <= outer.x2) and (outer.y1 <= cy <= outer.y2)


@dataclass
class ChargeDecision:
    charging: bool                              # ham sinyal (debounce ÖNCESİ)
    matches: list[tuple[int, int]] = field(default_factory=list)  # (gun_idx, vehicle_idx)
    matched_guns: set[int] = field(default_factory=set)
    matched_vehicles: set[int] = field(default_factory=set)


def evaluate(vehicles: list[Box], guns: list[Box]) -> ChargeDecision:
    """Tüm tabanca×araç çiftlerini gez; herhangi bir containment -> charging=True."""
    matches: list[tuple[int, int]] = []
    mg: set[int] = set()
    mv: set[int] = set()
    for gi, gun in enumerate(guns):
        for vi, veh in enumerate(vehicles):
            if center_inside(gun, veh):
                matches.append((gi, vi))
                mg.add(gi)
                mv.add(vi)
    return ChargeDecision(charging=bool(matches), matches=matches,
                          matched_guns=mg, matched_vehicles=mv)
