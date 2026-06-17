"""RTSP/video yakalama — tam çözünürlüklü ham kare üretir, kopunca yeniden bağlanır.

Tasarım notu (İlke 2 — Ham Veri Bütünlüğü):
  Bu modül HER ZAMAN kameradan gelen tam çözünürlüklü kareyi olduğu gibi tutar.
  Hiçbir küçültme/sıkıştırma burada yapılmaz. Önizleme küçültmesi yalnızca arayüz
  katmanında ve ayrı bir kopya üzerinde yapılır.

Arka planda bir okuyucu iş parçacığı sürekli kare çeker ve "en güncel kareyi" tutar;
böylece tüketiciler (tespit/kayıt/önizleme) bloklamadan son kareyi alır.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

log = logging.getLogger("visioncar.capture")


@dataclass
class CaptureStats:
    width: int = 0
    height: int = 0
    declared_fps: float = 0.0      # kameranın bildirdiği FPS
    measured_fps: float = 0.0      # gerçekte ölçülen FPS
    connected: bool = False
    frames_read: int = 0
    reconnects: int = 0
    last_error: str = ""


class Camera:
    """Arka plan iş parçacıklı yakalama. Kaynak: RTSP URL, video dosyası veya webcam indeksi."""

    def __init__(
        self,
        source: str | int,
        reconnect_delay_sec: float = 2.0,
        rtsp_transport: str = "tcp",
        fallback_source: Optional[str | int] = None,
    ) -> None:
        self.source = source
        self.fallback_source = fallback_source
        self.reconnect_delay_sec = reconnect_delay_sec
        self.rtsp_transport = rtsp_transport

        self._cap: Optional[cv2.VideoCapture] = None
        self._latest: Optional[np.ndarray] = None
        self._latest_ts: float = 0.0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._using_fallback = False

        self.stats = CaptureStats()
        self._fps_window: list[float] = []

    # ---- yaşam döngüsü -------------------------------------------------
    def start(self) -> "Camera":
        if self._running:
            return self
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="capture", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    # ---- tüketici API'si ----------------------------------------------
    def get_frame(self) -> tuple[Optional[np.ndarray], float]:
        """Son ham kareyi (kopyası) ve zaman damgasını döndür. Bloklamaz."""
        with self._lock:
            if self._latest is None:
                return None, 0.0
            return self._latest.copy(), self._latest_ts

    def wait_for_first_frame(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._latest is not None:
                    return True
            time.sleep(0.05)
        return False

    # ---- iç döngü ------------------------------------------------------
    def _open(self, source: str | int) -> Optional[cv2.VideoCapture]:
        # RTSP için FFMPEG taşıma protokolünü ayarla (tcp daha kararlı).
        if isinstance(source, str) and source.lower().startswith("rtsp"):
            os.environ.setdefault(
                "OPENCV_FFMPEG_CAPTURE_OPTIONS",
                f"rtsp_transport;{self.rtsp_transport}",
            )
            cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        else:
            cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def _loop(self) -> None:
        while self._running:
            if self._cap is None:
                self._connect()
                if self._cap is None:
                    time.sleep(self.reconnect_delay_sec)
                    continue

            ok, frame = self._cap.read()
            if not ok or frame is None:
                # Dosya kaynağında EOF bir kopma değildir — başa sarıp döngüle
                # (yalnızca yerel test/demo için; canlı RTSP'yi etkilemez).
                if self._is_file_source():
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    if self._cap.read()[0]:
                        self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                log.warning("Kare okunamadı — bağlantı koptu, yeniden bağlanılıyor.")
                self.stats.connected = False
                self.stats.reconnects += 1
                self._cap.release()
                self._cap = None
                time.sleep(self.reconnect_delay_sec)
                continue

            now = time.monotonic()
            with self._lock:
                self._latest = frame              # tam çözünürlük, dokunulmamış
                self._latest_ts = now
            self.stats.frames_read += 1
            self.stats.height, self.stats.width = frame.shape[:2]
            self._update_measured_fps(now)

            # Dosya kaynağını kendi FPS'ine göre frenle (kamera gibi davransın).
            # Canlı RTSP zaten ağ hızında geldiği için bu kol etkisizdir.
            if self._is_file_source() and self.stats.declared_fps > 0:
                time.sleep(max(0.0, 1.0 / self.stats.declared_fps - (time.monotonic() - now)))

    def _connect(self) -> None:
        cap = self._open(self.source)
        used_fallback = False
        if cap is None and self.fallback_source is not None:
            log.warning("Birincil kaynak açılamadı, yedek kaynağa geçiliyor: %s",
                        self.fallback_source)
            cap = self._open(self.fallback_source)
            used_fallback = cap is not None

        if cap is None:
            self.stats.connected = False
            self.stats.last_error = "Kaynak açılamadı (RTSP/yedek)."
            log.error(self.stats.last_error)
            return

        self._cap = cap
        self._using_fallback = used_fallback
        self.stats.connected = True
        self.stats.last_error = ""
        self.stats.declared_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        self.stats.width, self.stats.height = w, h
        log.info(
            "Bağlandı%s — çözünürlük %dx%d, bildirilen FPS %.1f",
            " (YEDEK)" if used_fallback else "", w, h, self.stats.declared_fps,
        )

    def _update_measured_fps(self, now: float) -> None:
        self._fps_window.append(now)
        # son ~2 saniyelik pencere
        cutoff = now - 2.0
        while self._fps_window and self._fps_window[0] < cutoff:
            self._fps_window.pop(0)
        if len(self._fps_window) >= 2:
            span = self._fps_window[-1] - self._fps_window[0]
            if span > 0:
                self.stats.measured_fps = (len(self._fps_window) - 1) / span

    def _is_file_source(self) -> bool:
        src = self.fallback_source if self._using_fallback else self.source
        return isinstance(src, str) and not src.lower().startswith("rtsp") \
            and not src.isdigit()

    @property
    def using_fallback(self) -> bool:
        return self._using_fallback
