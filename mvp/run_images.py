"""VisionCar MVP — TEK GÖRSEL(ler) üzerinde kademeli test.

Video yerine bir veya birden çok resim alır; iki modeli (araç + tabanca) çalıştırır,
containment kararını verir (tabanca-merkezi araç-kutusu içinde mi) ve anotasyonlu
kopyayı kaydeder. Tek karede zamansal debounce anlamlı olmadığı için karar
doğrudan containment'tır: KONNEKTOR TAKILI / TAKILI DEGIL.

Kullanım:
  python -m mvp.run_images resim1.jpg resim2.png
  python -m mvp.run_images "C:\\yol\\klasor"          # klasördeki tüm resimler
  python -m mvp.run_images foto.jpg --gun-conf 0.20
"""
from __future__ import annotations

import argparse
from pathlib import Path

# torch/ultralytics, cv2'den ÖNCE (Windows cuDNN DLL çakışması) — run_mvp ile aynı sıra
from mvp.run_mvp import (ROOT, C_VEHICLE, C_GUN, C_MATCH, C_ACTIVE, C_WAIT,
                         _FONT, _boxes_from_result, _draw_box, YOLO, cv2)
from mvp.charge_logic import evaluate

IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def gather(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        pp = Path(p)
        if not pp.is_absolute():
            pp = ROOT / pp
        if pp.is_dir():
            out += [q for q in sorted(pp.iterdir()) if q.suffix.lower() in IMG_EXT]
        elif pp.exists():
            out.append(pp)
        else:
            print(f"  ! bulunamadi: {pp}")
    return out


def annotate(img, vehicles, guns, decision) -> None:
    h, w = img.shape[:2]
    for vi, vb in enumerate(vehicles):
        m = vi in decision.matched_vehicles
        _draw_box(img, vb, C_MATCH if m else C_VEHICLE, f"arac {vb.conf:.2f}",
                  3 if m else 2)
    for gi, gb in enumerate(guns):
        m = gi in decision.matched_guns
        _draw_box(img, gb, C_MATCH if m else C_GUN, f"tabanca {gb.conf:.2f}",
                  3 if m else 2)
    for gi, vi in decision.matches:
        gc = tuple(int(v) for v in guns[gi].center)
        vc = tuple(int(v) for v in vehicles[vi].center)
        cv2.line(img, gc, vc, C_MATCH, 2, cv2.LINE_AA)
        cv2.circle(img, gc, 4, C_MATCH, -1)

    txt = "KONNEKTOR TAKILI" if decision.charging else "TAKILI DEGIL"
    col = C_ACTIVE if decision.charging else C_WAIT
    bar = 56
    ov = img.copy()
    cv2.rectangle(ov, (0, 0), (w, bar), (28, 28, 28), -1)
    cv2.addWeighted(ov, 0.6, img, 0.4, 0, img)
    cv2.rectangle(img, (0, 0), (10, bar), col, -1)
    cv2.putText(img, txt, (24, 38), _FONT, 1.0, col, 2, cv2.LINE_AA)
    cv2.putText(img, f"arac:{len(vehicles)} tabanca:{len(guns)}",
                (w - 230, 34), _FONT, 0.6, (210, 210, 210), 1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser(description="MVP — tek gorsel testi")
    ap.add_argument("images", nargs="+", help="resim dosyalari veya klasor")
    ap.add_argument("--vehicle-model", default="yolo11s.pt")
    ap.add_argument("--gun-model", default=str(ROOT / "models" / "kademe1_gun.pt"))
    ap.add_argument("--veh-conf", type=float, default=0.35)
    ap.add_argument("--gun-conf", type=float, default=0.25)
    ap.add_argument("--device", default=0)
    ap.add_argument("--out-dir", default=str(ROOT / "runs" / "mvp" / "images"))
    args = ap.parse_args()

    files = gather(args.images)
    if not files:
        raise SystemExit("Test edilecek resim bulunamadi.")

    veh_model = YOLO(args.vehicle_model)
    gun_model = YOLO(args.gun_model)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{len(files)} resim test ediliyor...\n")
    for f in files:
        img = cv2.imread(str(f))
        if img is None:
            print(f"  ! okunamadi: {f.name}")
            continue
        veh = _boxes_from_result(
            veh_model.predict(img, classes=[2], conf=args.veh_conf,
                              device=args.device, verbose=False)[0], args.veh_conf)
        gun = _boxes_from_result(
            gun_model.predict(img, conf=args.gun_conf, device=args.device,
                              verbose=False)[0], args.gun_conf)
        dec = evaluate(veh, gun)
        annotate(img, veh, gun, dec)
        dst = out_dir / f"{f.stem}_mvp.png"
        cv2.imwrite(str(dst), img)
        verdict = "TAKILI" if dec.charging else "takili degil"
        print(f"  {f.name:40s} arac={len(veh)} tabanca={len(gun)} "
              f"-> {verdict}  ({dst.name})")

    print(f"\nAnotasyonlu cikti: {out_dir}")


if __name__ == "__main__":
    main()
