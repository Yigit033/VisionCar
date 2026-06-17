"""Etiketli ham kare + metadata kaydı.

İlke 2: kayıt HER ZAMAN tam çözünürlüklü ham kare üzerinde, kayıpsız (PNG) yapılır.
Çıktı düzeni:
  data/recordings/<etiket>_<ts>/
      frame_000000.png      (kayıpsız ham kare)
      frame_000001.png
      ...
      metadata.json         (etiket, başlangıç/bitiş, çözünürlük, fps, kare listesi,
                             her kare için pulse sonucu özetleri)

Performans: tam çözünürlüklü PNG yazımı yavaştır (~4MP'de yüzlerce ms). Bu yüzden
yazma işi, işleme döngüsünü BLOKE ETMEMEK için ayrı bir arka plan iş parçacığında
(writer thread) ve sınırlı bir kuyruk üzerinden yapılır. Disk yetişemezse kareler
sessizce değil, SAYILIP loglanarak düşürülür (metadata'ya 'dropped' olarak yazılır).
Böylece yakalama + canlı tespit kayıt sırasında da tam hızda kalır.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

log = logging.getLogger("visioncar.recorder")


def _safe_label(label: str) -> str:
    keep = "-_."
    cleaned = "".join(c if (c.isalnum() or c in keep) else "_" for c in label.strip())
    return cleaned or "kayit"


def _timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


@dataclass
class RecordingState:
    active: bool = False
    label: str = ""
    directory: str = ""
    frame_count: int = 0      # diske gerçekten yazılan kare sayısı
    started_at: float = 0.0
    dropped: int = 0          # disk yetişemediği için düşürülen kare


class Recorder:
    """Tek seferde tek bir kayıt oturumu. Yazma arka plan thread'inde yapılır."""

    def __init__(self, output_dir: Path, queue_size: int = 128,
                 png_compression: int = 3) -> None:
        self.output_dir = Path(output_dir)
        self.queue_size = queue_size
        self.png_compression = png_compression

        self._lock = threading.Lock()
        self._active = False
        self._label = ""
        self._dir: Optional[Path] = None
        self._started_at = 0.0
        self._started_wall = ""
        self._declared_fps = 0.0

        self._submitted = 0          # kuyruğa konan kare (idx kaynağı)
        self._written = 0            # diske yazılan kare
        self._dropped = 0            # kuyruk dolu olduğu için düşen kare
        self._width = 0
        self._height = 0

        self._queue: Optional[queue.Queue] = None
        self._writer: Optional[threading.Thread] = None
        self._meta_frames: list[dict[str, Any]] = []  # yalnızca writer thread yazar

    # ---- oturum ---------------------------------------------------------
    def start(self, label: str, declared_fps: float = 0.0) -> RecordingState:
        with self._lock:
            if self._active:
                return self._state_locked()
            safe = _safe_label(label)
            self._dir = self.output_dir / f"{safe}_{_timestamp()}"
            self._dir.mkdir(parents=True, exist_ok=True)
            self._active = True
            self._label = label
            self._started_at = time.monotonic()
            self._started_wall = time.strftime("%Y-%m-%d %H:%M:%S")
            self._declared_fps = declared_fps
            self._submitted = self._written = self._dropped = 0
            self._width = self._height = 0
            self._meta_frames = []
            self._queue = queue.Queue(maxsize=self.queue_size)
            self._writer = threading.Thread(target=self._writer_loop,
                                            name="recorder-writer", daemon=True)
            self._writer.start()
            return self._state_locked()

    def add_frame(self, frame: np.ndarray, pulse: Optional[dict[str, Any]] = None) -> None:
        """Kareyi yazma kuyruğuna koy (bloklamaz). Kuyruk doluysa kareyi düşür."""
        with self._lock:
            if not self._active or self._queue is None:
                return
            idx = self._submitted
            t_rel = round(time.monotonic() - self._started_at, 4)
            self._submitted += 1
        item = (idx, frame, pulse, t_rel)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            with self._lock:
                self._dropped += 1
                if self._dropped % 50 == 1:
                    log.warning("Kayıt: disk yetişemiyor, %d kare düşürüldü.",
                                self._dropped)

    def _writer_loop(self) -> None:
        assert self._queue is not None
        while True:
            item = self._queue.get()
            if item is None:           # sentinel: dur
                break
            idx, frame, pulse, t_rel = item
            fname = f"frame_{idx:06d}.png"
            self._height, self._width = frame.shape[:2]
            cv2.imwrite(str(self._dir / fname), frame,
                        [cv2.IMWRITE_PNG_COMPRESSION, self.png_compression])
            entry: dict[str, Any] = {"index": idx, "file": fname, "t_rel": t_rel}
            if pulse is not None:
                entry["pulse"] = pulse
            self._meta_frames.append(entry)
            with self._lock:
                self._written += 1

    def stop(self) -> Optional[str]:
        """Kaydı durdur, kalan kuyruğu boşalt, metadata.json yaz, klasör yolunu döndür."""
        with self._lock:
            if not self._active or self._dir is None:
                return None
            self._active = False
            out = self._dir
            q = self._queue
            writer = self._writer

        # kalan kareleri yazdır ve writer'ı bitir (sentinel)
        if q is not None:
            q.put(None)
        if writer is not None:
            writer.join(timeout=60.0)

        meta = {
            "label": self._label,
            "started_at": self._started_wall,
            "duration_sec": round(time.monotonic() - self._started_at, 3),
            "frame_count": self._written,
            "submitted": self._submitted,
            "dropped": self._dropped,
            "resolution": {"width": self._width, "height": self._height},
            "declared_fps": self._declared_fps,
            "frames": sorted(self._meta_frames, key=lambda e: e["index"]),
        }
        with open(out / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        if self._dropped:
            log.warning("Kayıt bitti: %d yazıldı, %d düşürüldü (disk hızı sınırı).",
                        self._written, self._dropped)
        self._dir = None
        self._queue = None
        self._writer = None
        return str(out)

    # ---- durum ----------------------------------------------------------
    def state(self) -> RecordingState:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> RecordingState:
        return RecordingState(
            active=self._active,
            label=self._label if self._active else "",
            directory=str(self._dir) if self._dir else "",
            frame_count=self._written,
            started_at=self._started_at,
            dropped=self._dropped,
        )
