"""Eğitilmiş 'charging gun' modelini değerlendir + ağırlığı dışa al.

Eğitim tamamlandı (runs/detect/kademe1_gun/weights/best.pt). Bu script:
  - best.pt -> models/kademe1_gun.pt kopyalar (önce, garanti)
  - val ve test setinde mAP / precision / recall raporlar
  - birkaç test görselinde tahmin kaydeder
Pin-memory/CUDA "resource already mapped" hatasından kaçınmak için workers=0.

Çalıştır:  python scripts/eval_gun.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(r"C:\active_projects\VisionCar")
DATA = ROOT / "datasets" / "ev_charger" / "data.yaml"
BEST = ROOT / "runs" / "detect" / "kademe1_gun" / "weights" / "best.pt"
MODELS_DIR = ROOT / "models"
RUN = ROOT / "runs" / "detect"
NAME = "kademe1_gun"


def report(metrics, split: str) -> None:
    b = metrics.box
    print(f"\n=== {split.upper()} metrikleri ===")
    print(f"  precision : {b.mp:.4f}")
    print(f"  recall    : {b.mr:.4f}")
    print(f"  mAP50     : {b.map50:.4f}")
    print(f"  mAP50-95  : {b.map:.4f}")


def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dst = MODELS_DIR / "kademe1_gun.pt"
    shutil.copy(BEST, dst)
    print(f">>> En iyi ağırlık kopyalandı: {dst}")

    model = YOLO(str(BEST))

    val_m = model.val(data=str(DATA), split="val", device=0, workers=0,
                      project=str(RUN), name=f"{NAME}_val", exist_ok=True)
    report(val_m, "val")

    test_m = model.val(data=str(DATA), split="test", device=0, workers=0,
                       project=str(RUN), name=f"{NAME}_test", exist_ok=True)
    report(test_m, "test")

    test_images = ROOT / "datasets" / "ev_charger" / "test" / "images"
    sample = sorted(test_images.glob("*"))[:8]
    if sample:
        model.predict(source=[str(p) for p in sample], save=True, conf=0.25,
                      device=0, project=str(RUN), name=f"{NAME}_pred",
                      exist_ok=True, verbose=False)
        print(f"\n>>> Örnek tahminler: {RUN / (NAME + '_pred')}")


if __name__ == "__main__":
    main()
