"""Headless çekirdek kanıt testi — gerçek kameraya İHTİYAÇ DUYMAZ.

Sentetik bir "yanıp sönen LED" videosu üretir, ardından çekirdeğin tüm parçalarını
bu video üzerinde çalıştırır ve doğrular:
  - capture.Camera bir video dosyasını okuyabiliyor, çözünürlük/FPS raporluyor
  - PulseDetector yanıp sönen ROI'da pulse'u DOĞRU, sabit ROI'da pulse YOK diyor
  - Recorder tam çözünürlüklü kayıpsız PNG + metadata.json üretiyor
  - report_shots raw + annotated PNG + index.csv üretiyor

Çalıştır:  python scripts/test_core.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.capture import Camera
from core.pulse_detector import PulseDetector
from core.recorder import Recorder
from core.report_shots import make_report_shot

W, H, FPS, SECONDS = 640, 480, 30, 4
LED = (40, 40, 120, 120)  # x, y, w, h — sol üstte bir kutu


def make_synth_video(path: Path, blink_hz: float = 3.0) -> None:
    """Sol üstte ~blink_hz frekansında yanıp sönen parlak bir kutu içeren video."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(str(path), fourcc, FPS, (W, H))
    n = FPS * SECONDS
    for i in range(n):
        frame = np.full((H, W, 3), 30, dtype=np.uint8)  # koyu arka plan
        # sabit gri referans kutu (sağ alt) — burada pulse OLMAMALI
        cv2.rectangle(frame, (460, 320), (580, 440), (110, 110, 110), -1)
        # yanıp sönen LED kutusu
        phase = np.sin(2 * np.pi * blink_hz * (i / FPS))
        on = phase > 0
        x, y, w, h = LED
        color = (60, 220, 60) if on else (20, 40, 20)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, -1)
        vw.write(frame)
    vw.release()


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  -> {detail}" if detail else ""))
    return ok


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="visioncar_test_"))
    video = tmp / "synth_blink.mp4"
    print(f"Sentetik video üretiliyor: {video}")
    make_synth_video(video)

    all_ok = True

    # --- capture --------------------------------------------------------
    print("\n[1] capture.Camera (video dosyası kaynağı)")
    cam = Camera(source=str(video)).start()
    if not cam.wait_for_first_frame(timeout=10):
        print("  [FAIL] İlk kare gelmedi.")
        cam.stop()
        return 1
    time.sleep(0.5)
    s = cam.stats
    all_ok &= check("çözünürlük doğru", (s.width, s.height) == (W, H),
                    f"{s.width}x{s.height}")
    all_ok &= check("bildirilen FPS okundu", abs(s.declared_fps - FPS) < 2,
                    f"{s.declared_fps}")

    # --- pulse: yanıp sönen ROI -> PULSE VAR ----------------------------
    print("\n[2] PulseDetector — yanıp sönen LED ROI'si")
    det = PulseDetector(window_frames=60, brightness_std_threshold=6.0,
                        min_blink_crossings=4)
    # videoyu doğrudan baştan okuyup detektörü besle (deterministik)
    cap = cv2.VideoCapture(str(video))
    last = None
    t = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t += 1.0 / FPS
        last = det.update(frame, LED, t)
    cap.release()
    all_ok &= check("yanıp sönen ROI'de pulse tespit edildi", last.pulsing,
                    f"freq~{last.frequency_hz:.1f}Hz, geçiş={last.crossings}, "
                    f"std={last.amplitude:.1f}")

    # --- pulse: sabit ROI -> PULSE YOK ----------------------------------
    print("\n[3] PulseDetector — sabit referans kutu (pulse olmamalı)")
    det2 = PulseDetector(window_frames=60, brightness_std_threshold=6.0,
                         min_blink_crossings=4)
    STATIC = (460, 320, 120, 120)
    cap = cv2.VideoCapture(str(video))
    last2 = None
    t = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t += 1.0 / FPS
        last2 = det2.update(frame, STATIC, t)
    cap.release()
    all_ok &= check("sabit ROI'de pulse YOK (doğru negatif)", not last2.pulsing,
                    f"std={last2.amplitude:.1f}, geçiş={last2.crossings}")

    # --- recorder -------------------------------------------------------
    print("\n[4] Recorder — tam çözünürlüklü kayıpsız PNG + metadata.json")
    rec = Recorder(tmp / "recordings")
    rec.start("test_etiket", declared_fps=FPS)
    frame, _ = cam.get_frame()
    for _ in range(5):
        f, _ = cam.get_frame()
        if f is not None:
            rec.add_frame(f, pulse={"pulsing": True})
        time.sleep(0.05)
    rec_dir = rec.stop()
    rec_path = Path(rec_dir) if rec_dir else None
    pngs = sorted(rec_path.glob("frame_*.png")) if rec_path else []
    all_ok &= check("kayıpsız PNG kareler yazıldı", len(pngs) >= 1,
                    f"{len(pngs)} kare")
    if pngs:
        saved = cv2.imread(str(pngs[0]))
        all_ok &= check("kayıtlı kare tam çözünürlükte", saved.shape[:2] == (H, W),
                        f"{saved.shape[1]}x{saved.shape[0]}")
    meta_ok = rec_path and (rec_path / "metadata.json").exists()
    all_ok &= check("metadata.json üretildi", bool(meta_ok))
    if meta_ok:
        meta = json.loads((rec_path / "metadata.json").read_text(encoding="utf-8"))
        all_ok &= check("metadata kare sayısı tutarlı",
                        meta["frame_count"] == len(pngs), str(meta["frame_count"]))

    # --- report_shots ---------------------------------------------------
    print("\n[5] report_shots — raw + annotated PNG + index.csv")
    rep_dir = tmp / "report_shots"
    if frame is not None:
        shot = make_report_shot(frame, "dogrudan_gunes", rep_dir, fps=FPS,
                                roi=LED, result="PULSE VAR (~3.0 Hz)", pulsing=True)
        raw_ok = Path(shot.raw_path).exists()
        ann_ok = Path(shot.annotated_path).exists()
        idx_ok = (rep_dir / "index.csv").exists()
        all_ok &= check("raw.png üretildi", raw_ok)
        all_ok &= check("annotated.png üretildi", ann_ok)
        all_ok &= check("index.csv üretildi", idx_ok)
        if raw_ok:
            raw_img = cv2.imread(shot.raw_path)
            all_ok &= check("raw tam çözünürlükte", raw_img.shape[:2] == (H, W),
                            f"{raw_img.shape[1]}x{raw_img.shape[0]}")

    cam.stop()

    print("\n" + ("=" * 48))
    print("SONUC:", "TUM TESTLER GECTI [OK]" if all_ok else "BAZI TESTLER BASARISIZ [X]")
    print(f"Çıktılar incelemek için: {tmp}")
    print("=" * 48)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
