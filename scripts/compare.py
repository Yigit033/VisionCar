"""İki etiketi yan yana koyan karşılaştırma görseli üretir.

Hocaya "ölç ve göster" anlatımı için: ör. gölge vs doğrudan güneş, ya da
gölgelik öncesi/sonrası. data/report_shots içindeki ilgili snapshot'ları bulur,
aynı yüksekliğe getirip yan yana birleştirir ve başlık şeritleri ekler.

Kullanım:
  python scripts/compare.py golge dogrudan_gunes
  python scripts/compare.py golge dogrudan_gunes --raw --out data/report_shots/karsilastirma.png

Etiket yerine doğrudan bir dosya yolu da verebilirsiniz.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config as cfg_mod

_FONT = cv2.FONT_HERSHEY_DUPLEX


def find_shot(token: str, report_dir: Path, use_raw: bool) -> Optional[Path]:
    """Token bir dosya yoluysa onu, değilse o etiketin en yeni snapshot'ını bul."""
    p = Path(token)
    if p.exists() and p.is_file():
        return p
    suffix = "_raw.png" if use_raw else "_annotated.png"
    matches = sorted(report_dir.glob(f"{token}_*{suffix}"),
                     key=lambda q: q.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def caption_panel(img: np.ndarray, text: str, height: int) -> np.ndarray:
    """Görseli verilen yüksekliğe ölçekle ve altına başlık şeridi ekle."""
    h, w = img.shape[:2]
    scale = height / float(h)
    img = cv2.resize(img, (max(1, int(w * scale)), height),
                     interpolation=cv2.INTER_AREA)
    band_h = max(44, height // 12)
    band = np.full((band_h, img.shape[1], 3), 28, dtype=np.uint8)
    fs = max(0.7, img.shape[1] / 900.0)
    th = max(1, int(round(fs * 1.4)))
    (tw, _), _ = cv2.getTextSize(text, _FONT, fs, th)
    tx = max(10, (img.shape[1] - tw) // 2)
    cv2.putText(band, text, (tx, int(band_h * 0.66)), _FONT, fs,
                (235, 235, 235), th, cv2.LINE_AA)
    return np.vstack([img, band])


def main() -> int:
    cfg = cfg_mod.load_config()
    report_dir = cfg_mod.resolve_path(
        cfg.get("report", {}).get("output_dir", "data/report_shots"))

    ap = argparse.ArgumentParser(description="İki etiketi yan yana karşılaştır.")
    ap.add_argument("left", help="sol etiket veya dosya yolu")
    ap.add_argument("right", help="sağ etiket veya dosya yolu")
    ap.add_argument("--raw", action="store_true",
                    help="annotated yerine ham görselleri kullan")
    ap.add_argument("--out", default=None, help="çıktı yolu")
    ap.add_argument("--height", type=int, default=720, help="panel yüksekliği")
    args = ap.parse_args()

    left = find_shot(args.left, report_dir, args.raw)
    right = find_shot(args.right, report_dir, args.raw)
    if left is None:
        print(f"HATA: '{args.left}' için görsel bulunamadı ({report_dir})")
        return 1
    if right is None:
        print(f"HATA: '{args.right}' için görsel bulunamadı ({report_dir})")
        return 1

    li = cv2.imread(str(left))
    ri = cv2.imread(str(right))
    if li is None or ri is None:
        print("HATA: görseller okunamadı.")
        return 1

    lp = caption_panel(li, args.left, args.height)
    rp = caption_panel(ri, args.right, args.height)
    # yükseklikleri eşitle (başlık şeridi farklı olabilir)
    H = max(lp.shape[0], rp.shape[0])
    def pad(a):
        if a.shape[0] < H:
            a = np.vstack([a, np.full((H - a.shape[0], a.shape[1], 3), 28, np.uint8)])
        return a
    lp, rp = pad(lp), pad(rp)
    divider = np.full((H, 4, 3), 60, dtype=np.uint8)
    combined = np.hstack([lp, divider, rp])

    out = Path(args.out) if args.out else (
        report_dir / f"karsilastirma_{args.left}_vs_{args.right}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), combined)
    print(f"Karşılaştırma görseli üretildi: {out}")
    print(f"  sol : {left.name}")
    print(f"  sağ : {right.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
