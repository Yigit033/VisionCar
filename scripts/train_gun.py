"""Kademe-1 'charging gun' dedektörü — YOLO11s transfer learning.

- base: yolo11s.pt (COCO-pretrained)
- data: datasets/ev_charger/data.yaml (tek sınıf: charging gun)
- eğitim sonrası val + test metrikleri (mAP / precision / recall)
- birkaç test görselinde tahmin kaydı
- en iyi ağırlık -> models/kademe1_gun.pt

Çalıştır:  python scripts/train_gun.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(r"C:\active_projects\VisionCar")
DATA = ROOT / "datasets" / "ev_charger" / "data.yaml"
MODELS_DIR = ROOT / "models"
RUN_NAME = "kademe1_gun"


def report(metrics, split: str) -> None:
    b = metrics.box
    print(f"\n=== {split.upper()} metrikleri ===")
    print(f"  mAP50     : {b.map50:.4f}")
    print(f"  mAP50-95  : {b.map:.4f}")
    print(f"  precision : {b.mp:.4f}")
    print(f"  recall    : {b.mr:.4f}")


def main():
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    model = YOLO("yolo11s.pt")  # yoksa otomatik indirilir

    print(">>> Eğitim başlıyor (epochs=100, patience=25, batch=-1, imgsz=640, device=0)")
    model.train(
        data=str(DATA),
        epochs=100,
        patience=25,
        batch=-1,            # GPU'ya göre otomatik batch
        imgsz=640,
        device=0,            # CUDA
        # Bu makine RAM açısından dar (13.7 GB). Çok sayıda DataLoader işçisi
        # her biri torch+cv2 DLL'lerini ayrı süreçte yükleyip "commit" belleğini
        # taşırıyordu (page file çok küçük hatası). 2 işçi güvenli ve yeterli.
        workers=2,
        project=str(ROOT / "runs" / "detect"),
        name=RUN_NAME,
        exist_ok=True,
    )
    save_dir = Path(model.trainer.save_dir)
    best = save_dir / "weights" / "best.pt"
    print(f"\n>>> Eğitim bitti. En iyi ağırlık: {best}")

    # En iyi ağırlıkla değerlendir
    best_model = YOLO(str(best))
    val_metrics = best_model.val(data=str(DATA), split="val",
                                 project=str(ROOT / "runs" / "detect"),
                                 name=f"{RUN_NAME}_val", exist_ok=True)
    report(val_metrics, "val")
    test_metrics = best_model.val(data=str(DATA), split="test",
                                  project=str(ROOT / "runs" / "detect"),
                                  name=f"{RUN_NAME}_test", exist_ok=True)
    report(test_metrics, "test")

    # Birkaç test görselinde tahmin kaydet
    test_images = ROOT / "datasets" / "ev_charger" / "test" / "images"
    sample = sorted(test_images.glob("*"))[:8]
    if sample:
        best_model.predict(
            source=[str(p) for p in sample],
            save=True, conf=0.25, device=0,
            project=str(ROOT / "runs" / "detect"),
            name=f"{RUN_NAME}_pred", exist_ok=True,
        )
        print(f"\n>>> Örnek tahminler kaydedildi: "
              f"{ROOT / 'runs' / 'detect' / (RUN_NAME + '_pred')}")

    # En iyi ağırlığı models/ altına kopyala
    dst = MODELS_DIR / "kademe1_gun.pt"
    shutil.copy(best, dst)
    print(f"\n>>> En iyi ağırlık kopyalandı: {dst}")


if __name__ == "__main__":
    main()
