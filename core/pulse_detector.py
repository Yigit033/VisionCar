"""ROI'da ZAMANSAL pulse (yanıp-sönme) tespiti.

Yaklaşım (İlke 4'teki gece/IR notuna uygun):
  Tespit, son N karelik kayan pencere üzerindeki ROI parlaklık sinyaline dayanır.
  Renk kullanılmaz — gece kamera IR moduna geçince renk kaybolur ama parlaklık
  yanıp-sönmesi kalır. Parlaklık olarak gri-tonlama ortalaması kullanılır.

Sinyal işleme:
  - Her karede ROI'nin ortalama parlaklığı (0..255) bir kayan pencereye yazılır.
  - Pencere doluysa: sinyalin std'si bir eşiğin üstündeyse "değişim var" demektir.
  - Ortalama çizgisini kaç kez geçtiğini (sıfır-geçiş) sayarak yanıp-sönmeyi ayırt
    ederiz; tek bir parlaklık sıçraması (geçiş ~0) pulse SAYILMAZ.
  - Geçiş sayısı + pencere süresinden kabaca frekans (Hz) tahmin edilir.

Bu modül durum tutar (kayan pencere) ama tamamen headless'tır; UI/IO yapmaz.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

# ROI tipi: (x, y, w, h) tam çözünürlüklü piksel. None ise tüm kare.
ROI = Optional[tuple[int, int, int, int]]


@dataclass
class PulseResult:
    pulsing: bool = False
    brightness: float = 0.0      # anlık ROI ortalama parlaklığı (0..255)
    amplitude: float = 0.0       # pencere std'si (sinyal şiddeti)
    frequency_hz: float = 0.0    # tahmini yanıp-sönme frekansı
    crossings: int = 0           # pencerede ortalama-geçiş sayısı
    window_filled: bool = False  # pencere yeterince doldu mu


def clamp_roi(roi: ROI, frame_w: int, frame_h: int) -> ROI:
    """ROI'yi kare sınırlarına kırp; geçersizse None (tüm kare) döndür."""
    if roi is None:
        return None
    x, y, w, h = roi
    if w <= 0 or h <= 0:
        return None
    x = max(0, min(int(x), frame_w - 1))
    y = max(0, min(int(y), frame_h - 1))
    w = max(1, min(int(w), frame_w - x))
    h = max(1, min(int(h), frame_h - y))
    return (x, y, w, h)


def roi_brightness(frame: np.ndarray, roi: ROI) -> float:
    """ROI (veya tüm kare) için ortalama gri-tonlama parlaklığı."""
    if roi is not None:
        x, y, w, h = roi
        patch = frame[y:y + h, x:x + w]
    else:
        patch = frame
    if patch.size == 0:
        return 0.0
    if patch.ndim == 3:
        # BGR -> gri (parlaklık). Renk bağımlılığı yok.
        gray = patch.mean(axis=2)
    else:
        gray = patch
    return float(gray.mean())


class PulseDetector:
    def __init__(
        self,
        window_frames: int = 60,
        brightness_std_threshold: float = 6.0,
        min_blink_crossings: int = 4,
    ) -> None:
        self.window_frames = window_frames
        self.brightness_std_threshold = brightness_std_threshold
        self.min_blink_crossings = min_blink_crossings
        self._samples: deque[float] = deque(maxlen=window_frames)
        self._times: deque[float] = deque(maxlen=window_frames)

    def reset(self) -> None:
        self._samples.clear()
        self._times.clear()

    def update(self, frame: np.ndarray, roi: ROI, ts: float) -> PulseResult:
        """Yeni kareyi pencereye ekle ve güncel tespit sonucunu döndür."""
        h, w = frame.shape[:2]
        roi = clamp_roi(roi, w, h)
        brightness = roi_brightness(frame, roi)
        self._samples.append(brightness)
        self._times.append(ts)

        res = PulseResult(brightness=brightness)
        n = len(self._samples)
        if n < max(8, self.window_frames // 4):
            return res  # henüz yeterli örnek yok

        res.window_filled = n >= self.window_frames
        arr = np.fromiter(self._samples, dtype=np.float64, count=n)
        mean = arr.mean()
        std = float(arr.std())
        res.amplitude = std

        # Ortalama-geçiş sayımı: gürültüye karşı küçük bir histerezis bandı kullan.
        band = max(2.0, std * 0.5)
        state = 0  # -1 düşük, +1 yüksek, 0 belirsiz
        crossings = 0
        for v in arr:
            if v > mean + band:
                if state == -1:
                    crossings += 1
                state = 1
            elif v < mean - band:
                if state == 1:
                    crossings += 1
                state = -1
        res.crossings = crossings

        # Frekans tahmini: geçiş sayısı / 2 = tam döngü; pencere süresine böl.
        span = (self._times[-1] - self._times[0]) if n >= 2 else 0.0
        if span > 0 and crossings >= 2:
            res.frequency_hz = (crossings / 2.0) / span

        res.pulsing = (
            std >= self.brightness_std_threshold
            and crossings >= self.min_blink_crossings
        )
        return res
