"""Çekirdek orkestratör — capture + pulse + recorder + report_shots'ı headless birleştirir.

Bu sınıf arayüzden BAĞIMSIZDIR (api/web import etmez). API katmanı bunun üstünde
ince bir kabuktur; arayüz olmadan da (örn. bir CLI veya test scriptinden) sürülebilir.

Sorumluluk:
  - kamerayı başlat/durdur
  - sürekli işleme döngüsünde her ham kareyi pulse detektörüne ver
  - kayıt aktifse ham kareyi recorder'a ilet
  - güncel durumu (çözünürlük/fps/etiket/kayıt/pulse) tek yerde topla
  - anlık snapshot (raw+annotated) üret
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

import numpy as np

from . import config as cfg_mod
from .capture import Camera
from .pulse_detector import ROI, PulseDetector, PulseResult, clamp_roi
from .recorder import Recorder
from .report_shots import make_report_shot

log = logging.getLogger("visioncar.engine")


def _result_text(p: PulseResult) -> str:
    if not p.window_filled and p.crossings == 0:
        return "olcum suruyor..."
    if p.pulsing:
        return f"PULSE VAR  (~{p.frequency_hz:.1f} Hz)"
    return "pulse yok"


class Engine:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        cam = cfg.get("camera", {})
        self.camera = Camera(
            source=cam.get("rtsp_url"),
            reconnect_delay_sec=float(cam.get("reconnect_delay_sec", 2.0)),
            rtsp_transport=cam.get("rtsp_transport", "tcp"),
            fallback_source=cam.get("fallback_source"),
        )

        pcfg = cfg.get("pulse", {})
        self.detector = PulseDetector(
            window_frames=int(pcfg.get("window_frames", 60)),
            brightness_std_threshold=float(pcfg.get("brightness_std_threshold", 6.0)),
            min_blink_crossings=int(pcfg.get("min_blink_crossings", 4)),
        )

        rec_cfg = cfg.get("recording", {})
        self.recorder = Recorder(cfg_mod.resolve_path(
            rec_cfg.get("output_dir", "data/recordings")))
        # Her N karede bir kaydet (1 = her kare).
        self.record_every_n = max(1, int(rec_cfg.get("record_every_n", 1)))
        self._rec_seen = 0
        self.report_dir = cfg_mod.resolve_path(
            cfg.get("report", {}).get("output_dir", "data/report_shots"))

        self._roi: ROI = self._roi_from_cfg(cfg.get("roi", {}))
        self._last_pulse = PulseResult()
        self._lock = threading.Lock()
        self._proc_thread: Optional[threading.Thread] = None
        self._running = False
        self._last_processed_ts = 0.0

    @staticmethod
    def _roi_from_cfg(roi_cfg: dict[str, Any]) -> ROI:
        x, y, w, h = (roi_cfg.get(k) for k in ("x", "y", "w", "h"))
        if None in (x, y, w, h):
            return None
        return (int(x), int(y), int(w), int(h))

    # ---- yaşam döngüsü -------------------------------------------------
    def start(self) -> None:
        self.camera.start()
        self._running = True
        self._proc_thread = threading.Thread(
            target=self._process_loop, name="engine", daemon=True)
        self._proc_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._proc_thread:
            self._proc_thread.join(timeout=3.0)
        if self.recorder.state().active:
            self.recorder.stop()
        self.camera.stop()

    # ---- işleme döngüsü -----------------------------------------------
    def _process_loop(self) -> None:
        while self._running:
            frame, ts = self.camera.get_frame()
            if frame is None or ts == self._last_processed_ts:
                time.sleep(0.005)
                continue
            self._last_processed_ts = ts

            with self._lock:
                roi = self._roi
            pulse = self.detector.update(frame, roi, ts)
            with self._lock:
                self._last_pulse = pulse

            if self.recorder.state().active:
                # frame stride: her N karede bir yaz
                if self._rec_seen % self.record_every_n == 0:
                    self.recorder.add_frame(frame, pulse=self._pulse_dict(pulse))
                self._rec_seen += 1

    # ---- ROI -----------------------------------------------------------
    def set_roi(self, roi: ROI, *, persist: bool = True) -> ROI:
        with self._lock:
            self._roi = roi
        self.detector.reset()
        if persist:
            if roi is None:
                cfg_mod.save_roi({"x": None, "y": None, "w": None, "h": None})
            else:
                x, y, w, h = roi
                cfg_mod.save_roi({"x": x, "y": y, "w": w, "h": h})
        return roi

    def get_roi(self) -> ROI:
        with self._lock:
            return self._roi

    # ---- kayıt ---------------------------------------------------------
    def start_recording(self, label: str) -> dict[str, Any]:
        self._rec_seen = 0
        st = self.recorder.start(label, declared_fps=self.camera.stats.declared_fps)
        return asdict(st)

    def stop_recording(self) -> Optional[str]:
        return self.recorder.stop()

    # ---- snapshot ------------------------------------------------------
    def snapshot(self, label: str) -> Optional[dict[str, Any]]:
        frame, _ = self.camera.get_frame()
        if frame is None:
            return None
        with self._lock:
            roi = self._roi
            pulse = self._last_pulse
        shot = make_report_shot(
            frame, label, self.report_dir,
            fps=self.camera.stats.measured_fps or self.camera.stats.declared_fps,
            roi=roi,
            result=_result_text(pulse),
            pulsing=pulse.pulsing if pulse.window_filled or pulse.crossings else None,
        )
        return asdict(shot)

    # ---- durum ---------------------------------------------------------
    @staticmethod
    def _pulse_dict(p: PulseResult) -> dict[str, Any]:
        return {
            "pulsing": p.pulsing,
            "brightness": round(p.brightness, 2),
            "amplitude": round(p.amplitude, 2),
            "frequency_hz": round(p.frequency_hz, 2),
            "crossings": p.crossings,
            "window_filled": p.window_filled,
        }

    def state(self) -> dict[str, Any]:
        s = self.camera.stats
        rec = self.recorder.state()
        with self._lock:
            roi = self._roi
            pulse = self._last_pulse
        return {
            "connected": s.connected,
            "using_fallback": self.camera.using_fallback,
            "resolution": {"width": s.width, "height": s.height},
            "declared_fps": round(s.declared_fps, 1),
            "measured_fps": round(s.measured_fps, 1),
            "frames_read": s.frames_read,
            "reconnects": s.reconnects,
            "last_error": s.last_error,
            "roi": ({"x": roi[0], "y": roi[1], "w": roi[2], "h": roi[3]}
                    if roi else None),
            "recording": {
                "active": rec.active,
                "label": rec.label,
                "frame_count": rec.frame_count,
                "dropped": rec.dropped,
            },
            "pulse": self._pulse_dict(pulse),
            "result_text": _result_text(pulse),
        }
