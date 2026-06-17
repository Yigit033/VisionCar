"""VisionCar Sürüm 1.0 MVP — iki modelli kademeli şarj tespiti + görselleştirme.

Kademe:
  1) Araç: COCO yolo11s.pt, classes=[2] (car)
  2) Tabanca: models/kademe1_gun.pt
  3) Karar: tabanca-merkezi araç-kutusu içinde mi (containment) — charge_logic.evaluate
  4) Çift yönlü debounce -> stabil durum (SARJ AKTIF / BEKLENIYOR)
Görsel: kutular + eşleşme çizgisi + durum şeridi + debounce barı.

Çalıştır:
  python -m mvp.run_mvp --video test_video.mp4
  python -m mvp.run_mvp --video test_video.mp4 --show
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

# ÖNEMLİ (Windows): torch/ultralytics, cv2'den ÖNCE import edilmeli. Aksi halde
# OpenCV kendi DLL'lerini önce yükleyip torch'un yanlış cuDNN'i bulmasına yol açar
# ("Could not load symbol cudnnGetLibConfig", exit 127).
from ultralytics import YOLO
import cv2

from mvp.charge_logic import Box, evaluate
from mvp.debounce import DoubleSidedDebounce

ROOT = Path(__file__).resolve().parent.parent

# renkler (BGR)
C_VEHICLE = (235, 160, 70)     # mavi
C_GUN = (70, 170, 235)         # turuncu
C_MATCH = (90, 220, 90)        # yeşil (eşleşmiş)
C_ACTIVE = (80, 210, 100)      # yeşil durum
C_WAIT = (60, 170, 235)        # amber durum
_FONT = cv2.FONT_HERSHEY_DUPLEX


def _boxes_from_result(res, conf_thr: float) -> list[Box]:
    out: list[Box] = []
    if res.boxes is None:
        return out
    for b in res.boxes:
        conf = float(b.conf[0])
        if conf < conf_thr:
            continue
        x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
        out.append(Box(x1, y1, x2, y2, conf))
    return out


def _draw_box(img, box: Box, color, label: str, thick: int = 2) -> None:
    x1, y1, x2, y2 = int(box.x1), int(box.y1), int(box.x2), int(box.y2)
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thick, cv2.LINE_AA)
    if label:
        (tw, th), _ = cv2.getTextSize(label, _FONT, 0.5, 1)
        cv2.rectangle(img, (x1, y1 - th - 6), (x1 + tw + 6, y1), color, -1)
        cv2.putText(img, label, (x1 + 3, y1 - 4), _FONT, 0.5, (15, 15, 15), 1,
                    cv2.LINE_AA)


def _draw_overlay(img, vehicles, guns, decision, status, fps_txt: str) -> None:
    h, w = img.shape[:2]

    # araç kutuları (eşleşen yeşil)
    for vi, vb in enumerate(vehicles):
        matched = vi in decision.matched_vehicles
        _draw_box(img, vb, C_MATCH if matched else C_VEHICLE,
                  f"arac {vb.conf:.2f}", 3 if matched else 2)
    # tabanca kutuları (eşleşen yeşil) + araç merkezine çizgi
    for gi, gb in enumerate(guns):
        matched = gi in decision.matched_guns
        _draw_box(img, gb, C_MATCH if matched else C_GUN,
                  f"tabanca {gb.conf:.2f}", 3 if matched else 2)
    for gi, vi in decision.matches:
        gc = tuple(int(v) for v in guns[gi].center)
        vc = tuple(int(v) for v in vehicles[vi].center)
        cv2.line(img, gc, vc, C_MATCH, 2, cv2.LINE_AA)
        cv2.circle(img, gc, 4, C_MATCH, -1)

    # durum şeridi (üst)
    state_txt = "SARJ AKTIF" if status.active else "BEKLENIYOR"
    state_col = C_ACTIVE if status.active else C_WAIT
    bar_h = 64
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (w, bar_h), (28, 28, 28), -1)
    cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)
    cv2.rectangle(img, (0, 0), (10, bar_h), state_col, -1)
    cv2.putText(img, state_txt, (24, 42), _FONT, 1.1, state_col, 2, cv2.LINE_AA)
    raw_txt = "ham: sarj" if decision.charging else "ham: yok"
    cv2.putText(img, raw_txt, (w - 240, 26), _FONT, 0.6, (210, 210, 210), 1,
                cv2.LINE_AA)
    cv2.putText(img, fps_txt, (w - 240, 50), _FONT, 0.6, (210, 210, 210), 1,
                cv2.LINE_AA)

    # debounce barı (alt)
    _draw_debounce_bar(img, status)


def _draw_debounce_bar(img, status) -> None:
    h, w = img.shape[:2]
    margin = 20
    bx1, bx2 = margin, w - margin
    by2 = h - margin
    by1 = by2 - 22
    # arkaplan
    cv2.rectangle(img, (bx1, by1), (bx2, by2), (45, 45, 45), -1)
    cv2.rectangle(img, (bx1, by1), (bx2, by2), (90, 90, 90), 1)
    # dolum
    frac = status.progress
    fill_w = int((bx2 - bx1) * frac)
    # PASİF iken aktivasyona doğru yeşil dolar; AKTİF iken deaktivasyona (geri sayım) amber
    col = C_ACTIVE if status.progress_mode == "activation" else C_WAIT
    cv2.rectangle(img, (bx1, by1), (bx1 + fill_w, by2), col, -1)
    mode_label = ("AKTIVASYON" if status.progress_mode == "activation"
                  else "DEAKTIVASYON")
    cv2.putText(img, f"debounce [{mode_label}] {int(frac * 100)}%",
                (bx1 + 8, by2 - 5), _FONT, 0.5, (235, 235, 235), 1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser(description="VisionCar v1.0 MVP — sarj tespiti")
    ap.add_argument("--video", default="test_video.mp4")
    ap.add_argument("--vehicle-model", default="yolo11s.pt")
    ap.add_argument("--gun-model", default=str(ROOT / "models" / "kademe1_gun.pt"))
    ap.add_argument("--activation", type=int, default=30)
    ap.add_argument("--deactivation", type=int, default=30)
    ap.add_argument("--veh-conf", type=float, default=0.35)
    ap.add_argument("--gun-conf", type=float, default=0.35)
    ap.add_argument("--device", default=0)
    ap.add_argument("--out", default=str(ROOT / "runs" / "mvp" / "mvp_out.mp4"))
    ap.add_argument("--log-csv", default=str(ROOT / "runs" / "mvp" / "timeline.csv"),
                    help="kare-bazli zaman cizelgesi CSV yolu")
    ap.add_argument("--show", action="store_true", help="canli pencere goster")
    args = ap.parse_args()

    video = Path(args.video)
    if not video.is_absolute():
        video = ROOT / video
    if not video.exists():
        raise SystemExit(f"Video bulunamadi: {video}")

    veh_model = YOLO(args.vehicle_model)
    gun_model = YOLO(args.gun_model)
    debounce = DoubleSidedDebounce(args.activation, args.deactivation)

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise SystemExit(f"Video acilamadi: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (w, h))

    print(f"Video: {video.name}  {w}x{h} @ {fps:.1f}fps, {total} kare")
    print(f"Debounce: activation={args.activation}, deactivation={args.deactivation}")

    csv_path = Path(args.log_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_f = open(csv_path, "w", encoding="utf-8", newline="")
    csv_f.write("frame,t_sec,n_vehicles,n_guns,raw_charging,debounce_active,up,down\n")

    n = 0
    active_frames = 0
    t0 = time.time()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        n += 1

        veh_res = veh_model.predict(frame, classes=[2], conf=args.veh_conf,
                                    device=args.device, verbose=False)[0]
        gun_res = gun_model.predict(frame, conf=args.gun_conf,
                                    device=args.device, verbose=False)[0]
        vehicles = _boxes_from_result(veh_res, args.veh_conf)
        guns = _boxes_from_result(gun_res, args.gun_conf)

        decision = evaluate(vehicles, guns)
        status = debounce.update(decision.charging)
        if status.active:
            active_frames += 1

        csv_f.write(f"{n},{(n-1)/fps:.3f},{len(vehicles)},{len(guns)},"
                    f"{int(decision.charging)},{int(status.active)},"
                    f"{status.up_count},{status.down_count}\n")

        inst_fps = n / (time.time() - t0)
        _draw_overlay(frame, vehicles, guns, decision, status,
                      f"islem: {inst_fps:.1f} fps")
        writer.write(frame)
        if args.show:
            cv2.imshow("VisionCar MVP", frame)
            if cv2.waitKey(1) & 0xFF == 27:  # ESC
                break

    cap.release()
    writer.release()
    csv_f.close()
    if args.show:
        cv2.destroyAllWindows()

    dur = time.time() - t0
    print(f"\nBitti: {n} kare islendi ({n/dur:.1f} fps).")
    print(f"AKTIF kalinan kare: {active_frames}/{n} "
          f"({100*active_frames/max(1,n):.0f}%)")
    print(f"Cikti videosu: {out_path}")
    print(f"Zaman cizelgesi: {csv_path}")


if __name__ == "__main__":
    main()
