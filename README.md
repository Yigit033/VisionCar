# VisionCar — Faz 0: Saha Test Aracı

Bir EV şarj istasyonunda kamerayla şarj durumu tespiti yapacak ürünün ilk aşaması.
Bu repo şu an bir **saha test aracıdır**: çevresel koşulların (güneş / ışık / gece-IR)
görüntü işlemeye etkisini ölçmek için kameradan **tam çözünürlüklü ham kare** çeker,
etiketli olarak kaydeder, seçilen ROI'da basit bir **zamansal LED pulse** tespitini canlı
gösterir ve hocaya sunulacak rapor için **etiketli görseller** üretir.

> Bu bir **alet**, ürün değil. Tam tespit pipeline'ı (araç/konnektör/CNN), Jetson ve
> TensorRT bu fazda **yoktur**.

## Mimari ilkeler

1. **Decoupling.** Tüm görüntü mantığı `core/` içinde, arayüzden tamamen bağımsızdır.
   `core/` hiçbir zaman `api/` veya `web/` import etmez ve headless (arayüzsüz) çalışabilir.
   `api/` çekirdeğin üstünde ince bir kabuktur; `web/` ise `api/` üstünde ince bir istemci.
2. **Ham veri bütünlüğü.** İşleme, kayıt ve rapor görselleri **her zaman** kameradan gelen
   tam çözünürlüklü ham kare üzerinde yapılır. Tarayıcıya giden canlı önizleme bant genişliği
   için küçültülüp sıkıştırılır, **ama bu küçültme asla veri yoluna sızmaz** (küçültme yalnızca
   `api/` katmanında, ayrı bir kopya üzerinde). Önizleme üzerindeki ROI/pulse overlay'i de
   sunucuda değil, tarayıcıda canvas ile çizilir — yani MJPEG akışı sade küçültülmüş ham görüntüdür.

```
web/  (tarayıcı: canvas overlay, ROI seçimi)
  │  HTTP/JSON + MJPEG
api/  (FastAPI: ince kabuk — stream/state/roi/record/snapshot)
  │  doğrudan çağrı
core/ (headless motor: capture · pulse_detector · recorder · report_shots · engine)
```

## Kurulum

```bash
# (önerilir) sanal ortam
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell:  .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Bağımlılıklar minimumdur: `opencv-python`, `fastapi`, `uvicorn`, `numpy`, `pyyaml`.

## Yapılandırma (kimlik bilgileri koda GİRMEZ)

Şablonu kopyalayın ve kendi değerlerinizi girin:

```bash
cp config.example.yaml config.yaml      # PowerShell: Copy-Item config.example.yaml config.yaml
```

`config.yaml` **`.gitignore`'dadır** — şifre/URL repoya girmez. Kamera şifresini üç yoldan
biriyle verebilirsiniz:

1. `config.yaml` içinde `rtsp_url`'e doğrudan yazın (dosya gitignore'da).
2. `rtsp_url` içinde `{password}` bırakın, şifreyi ortam değişkeninden okutun:
   ```bash
   set VISIONCAR_RTSP_PASSWORD=...        # PowerShell:  $env:VISIONCAR_RTSP_PASSWORD="..."
   ```
3. Tüm URL'i ezin: `set VISIONCAR_RTSP_URL=rtsp://admin:...@192.168.137.1:554/Streaming/Channels/101`

Kamera: Hikvision DS-2CD3647G3-LIZSUY/SL — ana akış `.../Channels/101`, alt akış `102`.

**Kamerasız deneme:** `config.yaml`'da `camera.fallback_source` alanına bir video dosyası
yolu (veya webcam indeksi, ör. `0`) verirseniz, RTSP açılamadığında çekirdek bu kaynağa
düşer. Böylece kamera olmadan da tüm arayüz ve pipeline çalışır.

## Çalıştırma

### 1) Önce headless çekirdeği kanıtlayın (kamera gerekmez)

```bash
python scripts/test_core.py
```

Sentetik bir "yanıp sönen LED" videosu üretir ve şunları doğrular: capture tam çözünürlük
+ FPS okur; pulse detektörü yanıp sönen ROI'de **pulse var**, sabit kutuda **pulse yok** der;
recorder kayıpsız tam çözünürlüklü PNG + `metadata.json` yazar; report_shots raw + annotated
PNG + `index.csv` üretir. Hepsi geçerse `TUM TESTLER GECTI` yazar (çıkış kodu 0).

### 2) Web arayüzü + API

```bash
python -m api.server
# veya:  uvicorn api.server:app --host 0.0.0.0 --port 8000
```

Tarayıcıda **http://localhost:8000** açın.

Ekran düzeni:
- **Üstte durum çubuğu:** bağlantı, gerçek çözünürlük, FPS, kayıt durumu, aktif etiket, anlık tespit.
- **Solda canlı önizleme:** MJPEG akışı + üzerine ROI ve pulse overlay'i (canvas).
- **Sağda kontroller:** ROI temizle, koşul etiketi girişi, kayıt başlat/durdur, snapshot.
- **Altta galeri:** son üretilen rapor görselleri.

### Kullanım akışı

1. **ROI seç:** önizleme üzerinde fareyle LED / şarj portu bölgesini sürükleyin. Seçim
   `config.yaml`'a yazılır ve bir sonraki açılışta yüklenir. "ROI'yi temizle" tüm kareye döner.
2. **Pulse'u gözle:** seçili ROI'da parlaklık zamansal olarak yanıp sönüyorsa overlay
   **PULSE VAR (~Hz)** gösterir. Tespit **parlaklığa** dayanır (renge değil) — gece kamera
   IR moduna geçip renk kaybolsa bile çalışır.
3. **Etiketli kayıt:** koşul etiketi girin (ör. `dogrudan_gunes`, `golge`, `arka_isik`, `gece_ir`),
   "Kaydı başlat" / "Kaydı durdur". Çıktı: `data/recordings/<etiket>_<ts>/` altında tam
   çözünürlüklü kayıpsız PNG kareler + `metadata.json`.
4. **Rapor görseli (snapshot):** tek tıkla `data/report_shots/` altına aynı anda
   `<etiket>_<ts>_raw.png` (ham) ve `<etiket>_<ts>_annotated.png` (başlık şeridi + ROI + tespit)
   üretilir, `index.csv`'ye bir satır eklenir.

### 3) Karşılaştırma görseli

İki etiketi yan yana koyup "ölç ve göster" anlatımı için:

```bash
python scripts/compare.py golge dogrudan_gunes
python scripts/compare.py golge dogrudan_gunes --raw --out data/report_shots/karsilastirma.png
```

Etiket yerine doğrudan bir dosya yolu da verebilirsiniz. Varsayılan olarak her etiketin
**en yeni** snapshot'ı kullanılır.

## Proje yapısı

```
core/                 UI'dan bağımsız saf mantık (headless)
  config.py           yapılandırma + ortam değişkeni ezme + ROI kaydetme
  capture.py          RTSP/video yakalama, tam çözünürlük + FPS, reconnect
  pulse_detector.py   ROI'da zamansal (parlaklık tabanlı) pulse tespiti
  recorder.py         etiketli ham kare (kayıpsız PNG) + metadata kaydı
  report_shots.py     raw + annotated rapor görseli + index.csv
  engine.py           capture+pulse+recorder+report'u birleştiren orkestratör
api/
  server.py           FastAPI: stream(MJPEG)/state/roi/record/snapshot + statik web
web/
  index.html · style.css · app.js   şık, sade tek-ekran arayüz
scripts/
  test_core.py        headless çekirdek kanıt testi (kamera gerekmez)
  compare.py          iki etiketten yan yana karşılaştırma görseli
data/
  recordings/         (gitignore) etiketli ham kayıtlar
  report_shots/       (gitignore) rapor görselleri + index.csv
```

## Pulse tespiti nasıl çalışır

Son N karelik kayan pencerede ROI'nin ortalama parlaklığı (gri-tonlama) izlenir. Sinyalin
standart sapması bir eşiğin üstündeyse **ve** sinyal ortalama çizgisini yeterince kez geçiyorsa
(yanıp sönme = çok geçiş; tek bir parlaklık sıçraması = pulse değil) "pulse var" denir.
Geçiş sayısı ve pencere süresinden kaba bir frekans (Hz) tahmin edilir. Eşikler
`config.yaml > pulse` altında ayarlanabilir (`window_frames`, `brightness_std_threshold`,
`min_blink_crossings`). Renk kullanılmadığı için gece/IR modunda da geçerlidir.

---

# Sürüm 1.0 MVP — kademeli şarj tespiti (deneysel)

Faz 0'ın ötesinde, ilk uçtan uca tespit iskeleti `mvp/` altındadır. **Kademe:**
araç tespiti (COCO `yolo11s.pt`, `classes=[2]`) → tabanca/konnektör tespiti
(`models/kademe1_gun.pt`) → **containment kararı** (tabanca-kutusu MERKEZİ araç-kutusu
içinde mi — IoU değil) → çift yönlü debounce → durum (ŞARJ AKTİF / BEKLENİYOR).

Karar mantığı (`mvp/charge_logic.py`, `mvp/debounce.py`) görselleştirmeden bağımsızdır.

## Kurulum (ek ağır bağımlılıklar)

```bash
pip install -r requirements-ml.txt
# torch/torchvision'ı CUDA sürümünüzle EŞLEŞTİREREK kurun (bkz. requirements-ml.txt notu)
```

## Çalıştırma

```bash
# Video üzerinde (anotasyonlu çıktı + kare-bazlı timeline.csv üretir)
python -m mvp.run_mvp --video test_video.mp4
python -m mvp.run_mvp --video test_video.mp4 --gun-conf 0.20 --activation 15

# Tek/çoklu görsel veya klasör üzerinde
python -m mvp.run_images foto.jpg
python -m mvp.run_images "C:\yol\resim_klasoru" --gun-conf 0.20
```

Çıktılar `runs/mvp/` altına yazılır (git'e dahil değildir).

## Model eğitimi (kademe-1: charging gun)

`scripts/train_gun.py` YOLO11s'i `datasets/ev_charger/data.yaml` üzerinde transfer
learning ile eğitir; `scripts/eval_gun.py` val/test metriklerini üretir ve en iyi
ağırlığı `models/kademe1_gun.pt`'ye kopyalar. Dataset ve `runs/` git'e dahil değildir.

```bash
python scripts/train_gun.py     # GPU (device=0) gerektirir
python scripts/eval_gun.py
```

## Repoya dahil OLMAYANLAR (.gitignore)

`config.yaml` (kimlik bilgisi), `data/`, `datasets/`, `runs/`, video dosyaları ve
indirilebilir COCO backbone ağırlıkları (`yolo11s.pt` vb. ultralytics otomatik indirir)
repoda tutulmaz. Kendi eğittiğimiz `models/kademe1_gun.pt` ise proje çıktısı olarak repoda kalır.

