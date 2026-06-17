"""ev_charger dataset'inde sadece 'charging gun' sınıfını tut.

Kaynak sınıflar: 0='charging', 1='charging gun', 2='not charging'
Hedef: yalnızca 'charging gun' kalsın, id 0'a remap edilsin.

  - train/valid/test'teki tüm label .txt dosyalarında 0 ve 2 id'li satırları sil.
  - kalan (eski id 1) satırları 0'a remap et.
  - data.yaml -> nc: 1, names: ['charging gun'].
  - HİÇBİR görsel silinmez. Tüm boxları gidip boşalan label dosyaları boş .txt
    olarak bırakılır (YOLO'da bu = negatif/arka plan örneği).

Çalıştır:  python scripts/filter_classes.py
"""
from __future__ import annotations

import glob
import os
import shutil

ROOT = r"C:\active_projects\VisionCar\datasets\ev_charger"
KEEP_OLD_ID = "1"          # 'charging gun'
NEW_ID = "0"
SPLITS = ("train", "valid", "test")


def filter_labels():
    stats = {}
    for split in SPLITS:
        lbl_dir = os.path.join(ROOT, split, "labels")
        txts = glob.glob(os.path.join(lbl_dir, "*.txt"))
        kept_boxes = 0
        removed_boxes = 0
        emptied = 0          # bu filtrede sıfır kutuya düşen dosya
        total_files = len(txts)
        for t in txts:
            with open(t, "r", encoding="utf-8") as f:
                lines = [l for l in f if l.strip()]
            new_lines = []
            for l in lines:
                parts = l.split()
                cid = parts[0]
                if cid == KEEP_OLD_ID:
                    parts[0] = NEW_ID
                    new_lines.append(" ".join(parts))
                    kept_boxes += 1
                else:
                    removed_boxes += 1
            if not new_lines:
                emptied += 1
            with open(t, "w", encoding="utf-8") as f:
                f.write("\n".join(new_lines) + ("\n" if new_lines else ""))
        stats[split] = dict(files=total_files, kept_boxes=kept_boxes,
                            removed_boxes=removed_boxes, emptied=emptied)
    return stats


def update_data_yaml():
    path = os.path.join(ROOT, "data.yaml")
    shutil.copy(path, path + ".bak")
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    out = []
    for l in lines:
        s = l.strip()
        if s.startswith("nc:"):
            out.append("nc: 1\n")
        elif s.startswith("names:"):
            out.append("names: ['charging gun']\n")
        else:
            out.append(l)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)


def main():
    print("Label dosyaları filtreleniyor (sadece 'charging gun' tutuluyor)...")
    stats = filter_labels()
    update_data_yaml()
    print("data.yaml güncellendi (yedek: data.yaml.bak)\n")
    for split, s in stats.items():
        print(f"{split}: {s['files']} label dosyası | tutulan gun kutusu="
              f"{s['kept_boxes']} | silinen kutu={s['removed_boxes']} | "
              f"etiketsiz kalan görsel={s['emptied']}")


if __name__ == "__main__":
    main()
