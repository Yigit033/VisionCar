"""Rapor görseli üretimi: ham + anotasyonlu PNG + index.csv.

Tek çağrıda aynı kareden iki dosya üretir:
  <etiket>_<ts>_raw.png        -> tam çözünürlüklü kayıpsız ham kare (dokunulmamış)
  <etiket>_<ts>_annotated.png  -> aynı kareye temiz, raporluk anotasyon

Anotasyon (İlke 2: anotasyon ham karenin KOPYASINA çizilir, ham dosya bozulmaz):
  - üstte yarı saydam başlık şeridi: etiket, tarih-saat, çözünürlük, FPS, tespit sonucu
  - ROI kutusu (varsa)
  - okunaklı sans (Hershey Duplex) tipografi

index.csv'ye bir satır eklenir: dosya, etiket, ts, çözünürlük, fps, sonuç.
"""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from .pulse_detector import ROI, clamp_roi
from .recorder import _safe_label

_FONT = cv2.FONT_HERSHEY_DUPLEX


@dataclass
class ReportShot:
    raw_path: str
    annotated_path: str
    label: str
    timestamp: str
    resolution: str
    fps: float
    result: str


def _draw_header(
    img: np.ndarray,
    lines: list[str],
    accent: tuple[int, int, int],
) -> None:
    """Üstte yarı saydam koyu şerit + sol kenarda renkli aksan + metin satırları."""
    h, w = img.shape[:2]
    scale = max(0.6, w / 1600.0)            # çözünürlüğe göre ölçek
    thickness = max(1, int(round(scale * 1.4)))
    line_h = int(38 * scale)
    pad = int(18 * scale)
    strip_h = pad * 2 + line_h * len(lines)

    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, strip_h), (24, 24, 24), -1)
    cv2.addWeighted(overlay, 0.62, img, 0.38, 0, img)
    # sol aksan çizgisi
    cv2.rectangle(img, (0, 0), (int(8 * scale), strip_h), accent, -1)

    y = pad + int(line_h * 0.72)
    for i, text in enumerate(lines):
        color = (235, 235, 235) if i == 0 else (205, 205, 205)
        s = scale * (1.05 if i == 0 else 0.82)
        cv2.putText(img, text, (int(20 * scale), y), _FONT, s, (0, 0, 0),
                    thickness + 2, cv2.LINE_AA)  # ince gölge -> okunurluk
        cv2.putText(img, text, (int(20 * scale), y), _FONT, s, color,
                    thickness, cv2.LINE_AA)
        y += line_h


def _draw_roi(img: np.ndarray, roi: ROI, accent: tuple[int, int, int]) -> None:
    if roi is None:
        return
    h, w = img.shape[:2]
    roi = clamp_roi(roi, w, h)
    if roi is None:
        return
    x, y, rw, rh = roi
    t = max(2, int(round(w / 700.0)))
    cv2.rectangle(img, (x, y), (x + rw, y + rh), accent, t, cv2.LINE_AA)
    cv2.putText(img, "ROI", (x + 6, max(0, y - 8)), _FONT, max(0.6, w / 1800.0),
                accent, max(1, t - 1), cv2.LINE_AA)


def make_report_shot(
    frame: np.ndarray,
    label: str,
    output_dir: Path,
    *,
    fps: float = 0.0,
    roi: ROI = None,
    result: str = "",
    pulsing: Optional[bool] = None,
) -> ReportShot:
    """Ham + anotasyonlu görseli üret, index.csv'ye yaz, ReportShot döndür."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    safe = _safe_label(label)
    ts = time.strftime("%Y%m%d_%H%M%S")
    wall = time.strftime("%Y-%m-%d %H:%M:%S")
    h, w = frame.shape[:2]
    res_str = f"{w}x{h}"

    raw_path = output_dir / f"{safe}_{ts}_raw.png"
    ann_path = output_dir / f"{safe}_{ts}_annotated.png"

    # 1) Ham kare — dokunulmamış, kayıpsız.
    cv2.imwrite(str(raw_path), frame, [cv2.IMWRITE_PNG_COMPRESSION, 1])

    # 2) Anotasyon ham karenin KOPYASINA çizilir.
    annotated = frame.copy()
    if annotated.ndim == 2:
        annotated = cv2.cvtColor(annotated, cv2.COLOR_GRAY2BGR)

    # tespit sonucuna göre aksan rengi
    if pulsing is True:
        accent = (80, 220, 90)        # yeşil = pulse var
    elif pulsing is False:
        accent = (90, 160, 235)       # turuncu/mavi = pulse yok
    else:
        accent = (200, 200, 200)

    header_lines = [
        f"VisionCar  -  {label}",
        f"{wall}    {res_str}    {fps:.1f} FPS",
        f"Tespit: {result}" if result else "Tespit: -",
    ]
    _draw_roi(annotated, roi, accent)
    _draw_header(annotated, header_lines, accent)
    cv2.imwrite(str(ann_path), annotated, [cv2.IMWRITE_PNG_COMPRESSION, 1])

    shot = ReportShot(
        raw_path=str(raw_path),
        annotated_path=str(ann_path),
        label=label,
        timestamp=ts,
        resolution=res_str,
        fps=round(fps, 2),
        result=result,
    )
    _append_index(output_dir / "index.csv", shot)
    return shot


def _append_index(index_path: Path, shot: ReportShot) -> None:
    new_file = not index_path.exists()
    with open(index_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(
                ["raw_file", "annotated_file", "label", "timestamp",
                 "resolution", "fps", "result"]
            )
        writer.writerow([
            Path(shot.raw_path).name,
            Path(shot.annotated_path).name,
            shot.label,
            shot.timestamp,
            shot.resolution,
            shot.fps,
            shot.result,
        ])
