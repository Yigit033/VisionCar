# EV İhlal Backend — Faz 1 (yerel, uçtan uca)

EV şarj istasyonlarında **gereksiz işgali** tespit eden çok-istasyonlu ürünün backend'i.

**Çekirdek senaryo:** Araç şarj yerinin belirlenmiş bölgesinde **+** telemetri "şarj
olmuyor" diyor **+** 1–2 dakika geçti → o anın resmini (kanıt) yakala, kaydet, yetkiliye bildir.

> **Önemli ayrım:** doluluğu **kamera** görür; "şarj alıyor mu?" bilgisi **telemetriden**
> (ground truth) gelir, CV'den değil.

Bu klasör (`ev-ihlal-backend/`) eski YOLO/CV işlerinden bağımsızdır.

## Tasarım ilkesi: her dış bağımlılık bir arayüz arkasında

`interfaces.py` tüm dış sistemleri soyut sözleşmeyle tanımlar. Faz 1 mock/yerel,
Faz 2/3 gerçek implementasyonlar **aynı arayüzü** uygular — orkestrasyon değişmez.

| Bağımlılık | Arayüz | Faz 1 (şimdi) | Faz 2/3 (sonra) |
|---|---|---|---|
| Kamera | `CameraClient` | `IsapiCamera` (gerçek ISAPI snapshot) / `MockCamera` | aynı |
| Telemetri | `TelemetryProvider` | `MockTelemetry` | OCPP / CSMS API / Modbus |
| Depolama | `ObjectStorage` | `LocalObjectStorage` (klasör) | S3 (boto3) |
| Olay DB | `EventStore` | `SqliteEventStore` | Postgres vb. |
| Bildirim | `Notifier` | `LogNotifier` | e-posta/SMS/push/webhook |
| Merkez | `Uplink` | `LocalUplink` (no-op) | gerçek bulut uplink |

Seçim tek yerde: `app.py > Container`. Mock ↔ gerçek **tek satırda** takılıp çıkar.

## Kurulum

```bash
cd ev-ihlal-backend
pip install -r requirements.txt
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
# .env içine CAMERA_PASSWORD'ü girin (sır koda gömülmez, .env .gitignore'da)
```

## Çalıştırma

```bash
# Gerçek kamerayla (CAMERA_MODE=isapi, .env'de IP/şifre):
python app.py

# Kamerasız demo (sentetik kanıt görseli):
#   .env'de CAMERA_MODE=mock yapın ya da ortam değişkeniyle geçin
CAMERA_MODE=mock GRACE_PERIOD_SEC=10 python app.py
```

Pano: **http://127.0.0.1:8090/** (olaylar + kanıt küçük görselleri).

### Olay tetikleme (Faz 1)

Gerçek kamera ISAPI alarm stream'i bir **seam** olarak bırakıldı
(`CameraClient.event_stream`). Faz 1'de olay manuel/sim tetiklenir; **snapshot her
hâlükârda gerçek kameradan** çekilir:

```bash
# İşgal olayı -> grace_period geri sayımı -> süre dolunca telemetri sorgusu
curl -X POST localhost:8090/api/events/occupancy      -H "Content-Type: application/json" -d "{\"station_id\":\"ST-01\"}"

# Demo: geri sayımı atla, hemen değerlendir
curl -X POST localhost:8090/api/events/occupancy/now  -H "Content-Type: application/json" -d "{\"station_id\":\"ST-01\"}"

# Mock telemetriyi ayarla (demo): bir istasyonu 'şarj oluyor' yap -> ihlal olmaz
curl -X POST localhost:8090/api/telemetry/mock        -H "Content-Type: application/json" -d "{\"station_id\":\"ST-01\",\"status\":\"CHARGING\"}"
```

## İş akışı (orkestrasyon — `orchestration.py`)

1. İşgal olayı gelir (manuel/sim tetik; ileride ISAPI alarm).
2. O istasyon için `GRACE_PERIOD_SEC` geri sayımı (zaten sayıyorsa yeni tetik yok sayılır).
3. Süre dolunca **telemetri** (ground truth) sorulur.
4. Durum `NON_VIOLATION_STATUSES` içindeyse (ör. `CHARGING`, `PREPARING`): olay sessizce
   kapanır, **bildirim yok**.
5. Aksi halde **İHLAL**: gerçek kameradan snapshot → storage → olay DB'ye yazılır (outbox)
   → bildirim → merkeze forward kuyruğu.

## Senior detaylar (baştan gömülü)

- **Kimlik:** her olayda `station_id` + `detected_at`.
- **Oturum (occupancy session) modeli:** bir işgal = tek olay. Araç girişinden çıkışına
  kadar TEK oturum açılır; oturum açıkken tekrar tetik yeni olay üretmez (spam yok).
  Hedef `VACANCY_GRACE_SEC` boyunca dönmezse oturum kapanır → **yeni gelen araç YENİ olay**
  üretir. (Eski zaman-tabanlı debounce'un "A çıkıp B girince B'yi yutma" hatası böyle çözüldü.)
  `REPEAT_NOTIFY_SEC>0` ise aynı oturumda o aralıkla süregelen-ihlal re-kanıtı üretilir.
- **Store-and-forward:** olay **önce yerele** yazılır (DB = outbox), sonra `Forwarder`
  uplink ile merkeze gönderir; hata olursa retry'lanır. Faz 2'de uplink kopsa olaylar
  birikir, bağlantı gelince iletilir.
- **KVKK / retention:** araç görüntüsü kişisel veridir. `RETENTION_DAYS`'ten eski **görseller
  otomatik silinir**, DB kaydı anonimleşir (`RETENTION_PURGED`); olay kaydı (istatistik) kalır.
- **Telemetri durum-makinesi:** ihlal salt "akım=0" değil, **duruma** bağlı (`ChargingStatus`).
- **Config/secrets:** tüm ayar `config.py`'de; kamera şifresi `.env`/ortam değişkeninden,
  koda gömülü değil.

## Modüller

```
config.py            tüm ayarlar (.env/ortam değişkeni)
models.py            ChargingStatus, ViolationEvent, EventState
interfaces.py        dış bağımlılık arayüzleri (ABC)
adapters/            telemetry_mock · camera_isapi(+Mock) · storage_local ·
                     event_store_sqlite · notifier_log · uplink_local
orchestration.py     ViolationEngine (timer + debounce + ihlal kararı)
forwarder.py         store-and-forward worker
retention.py         KVKK görsel temizliği
app.py               FastAPI: DI (Container) + endpoint'ler + arka plan döngüleri
dashboard.py         pano (HTML)
scripts/smoke_test.py uçtan uca test (kamerasız)
```

## Test (kamerasız uçtan uca)

```bash
python scripts/smoke_test.py
```

Faz 1 kabul kriterlerini doğrular: ihlal→kanıt+DB+bildirim; şarj var→ihlal yok;
debounce→tek kayıt; store-and-forward→FORWARDED; retention→görsel silinir/anonimleşir.

## Kamera (referans)

- Hikvision DS-2CD3647G3 (AcuSense), yerel IP `192.168.137.1`, kullanıcı `admin`
  (şifre `.env`), **digest** auth.
- Snapshot (ISAPI): `GET http://<ip>/ISAPI/Streaming/channels/101/picture` → JPEG.
- RTSP (gerekirse): `rtsp://<user>:<pass>@<ip>:554/Streaming/Channels/101`.
- Kamera tarafı kural (Intrusion Detection, hedef Vehicle/Human) zaten kurulu; bu backend
  olayı alıp işler.

## Kapsam dışı (ŞİMDİ yapma)

Faz 2 (gerçek bulut + S3 + kameranın internetten buluta ulaşması) ve Faz 3 (gerçek OCPP/
Modbus telemetri) **şimdi yapılmaz** — yalnızca arayüzler onlara hazır bırakıldı.
