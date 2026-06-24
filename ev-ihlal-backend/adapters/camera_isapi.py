"""Kamera adaptörleri.

IsapiCamera  : GERÇEK Hikvision kamera — ISAPI ile snapshot (pull, digest auth).
MockCamera   : kamerasız test için sentetik (etiketli) JPEG üretir.

Faz 1 kuralı: snapshot HER ZAMAN gerçek kameradan çekilir (IsapiCamera). MockCamera
yalnızca kameraya erişilemeyen ortamlarda uçtan uca akışı denemek içindir.
"""
from __future__ import annotations

import io
import logging
import re
import time
from typing import Iterator

import requests
from requests.auth import HTTPDigestAuth

from interfaces import CameraClient
from models import utcnow

log = logging.getLogger("evihlal.camera")

_ALERT_RE = re.compile(rb"<EventNotificationAlert.*?</EventNotificationAlert>",
                       re.DOTALL)
_TYPE_RE = re.compile(r"<eventType>(.*?)</eventType>", re.IGNORECASE)
_STATE_RE = re.compile(r"<eventState>(.*?)</eventState>", re.IGNORECASE)


class IsapiCamera(CameraClient):
    """Hikvision DS-2CD3647G3 (AcuSense) — ISAPI snapshot.

    GET http://<ip>/ISAPI/Streaming/channels/<channel>/picture -> JPEG
    """

    def __init__(self, ip: str, user: str, password: str,
                 channel: str = "101", timeout_sec: float = 5.0) -> None:
        self.ip = ip
        self.user = user
        self.password = password
        self.channel = channel
        self.timeout = timeout_sec

    def _url(self) -> str:
        return f"http://{self.ip}/ISAPI/Streaming/channels/{self.channel}/picture"

    def snapshot(self, station_id: str) -> bytes:
        # NOT: Faz 1 tek kamera. station_id ileride istasyon→kamera eşlemesi için.
        url = self._url()
        resp = requests.get(url, auth=HTTPDigestAuth(self.user, self.password),
                            timeout=self.timeout)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "image" not in ct and not resp.content[:2] == b"\xff\xd8":
            raise RuntimeError(f"ISAPI beklenen JPEG değil (Content-Type={ct!r}).")
        log.info("ISAPI snapshot alındı: %s (%d bayt)", station_id, len(resp.content))
        return resp.content

    # ---- ISAPI alarm/event akışı (kamera olayı -> canlı dinleme) ----
    def event_stream(self) -> Iterator[dict]:
        """alertStream'e bağlanır, EventNotificationAlert bloklarını ayrıştırıp yield eder.

        Bağlantı koparsa otomatik yeniden bağlanır (sonsuz akış). Her olay:
          {"eventType": "fielddetection", "eventState": "active", "raw": "<xml>"}
        """
        url = f"http://{self.ip}/ISAPI/Event/notification/alertStream"
        auth = HTTPDigestAuth(self.user, self.password)
        while True:
            try:
                log.info("ISAPI alarm akışına bağlanılıyor: %s", url)
                with requests.get(url, auth=auth, stream=True,
                                  timeout=(self.timeout, None)) as resp:
                    resp.raise_for_status()
                    buf = b""
                    for chunk in resp.iter_content(chunk_size=1024):
                        if not chunk:
                            continue
                        buf += chunk
                        for m in _ALERT_RE.finditer(buf):
                            block = m.group(0)
                            text = block.decode("utf-8", "ignore")
                            et = _TYPE_RE.search(text)
                            es = _STATE_RE.search(text)
                            yield {
                                "eventType": (et.group(1).strip() if et else ""),
                                "eventState": (es.group(1).strip() if es else "active"),
                                "raw": text,
                            }
                        # işlenen kısmı at (son yarım blok kalsın)
                        last = buf.rfind(b"</EventNotificationAlert>")
                        if last != -1:
                            buf = buf[last + len(b"</EventNotificationAlert>"):]
                        if len(buf) > 1_000_000:      # güvenlik: tampon şişmesin
                            buf = buf[-4096:]
            except Exception as exc:
                log.warning("Alarm akışı koptu (%s) — 3s sonra yeniden bağlanılacak.", exc)
                time.sleep(3.0)


class MockCamera(CameraClient):
    """Sentetik JPEG (istasyon + zaman damgası yazılı). Pillow ile üretir."""

    def __init__(self, size: tuple[int, int] = (1280, 720)) -> None:
        self.size = size

    def snapshot(self, station_id: str) -> bytes:
        from PIL import Image, ImageDraw  # yerel import — yalnızca mock yolunda

        img = Image.new("RGB", self.size, (32, 36, 44))
        d = ImageDraw.Draw(img)
        ts = utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        d.rectangle([0, 0, self.size[0], 64], fill=(20, 22, 28))
        d.text((16, 22), f"[MOCK KAMERA]  istasyon={station_id}", fill=(235, 235, 235))
        d.text((16, self.size[1] - 30), ts, fill=(180, 180, 180))
        # basit bir "araç" dikdörtgeni — kanıt görseli demosu
        d.rectangle([self.size[0]//2 - 220, self.size[1]//2 - 90,
                     self.size[0]//2 + 220, self.size[1]//2 + 110],
                    outline=(120, 170, 235), width=4)
        d.text((self.size[0]//2 - 200, self.size[1]//2 - 80),
               "park eden arac (sentetik)", fill=(150, 190, 240))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()


def build_camera(settings) -> CameraClient:
    """Config'e göre kamera adaptörünü seç (mock ↔ gerçek tek satır)."""
    if settings.camera_mode == "mock":
        log.warning("CAMERA_MODE=mock — sentetik görsel kullanılıyor (gerçek kamera değil).")
        return MockCamera()
    return IsapiCamera(
        ip=settings.camera_ip, user=settings.camera_user,
        password=settings.camera_password, channel=settings.camera_channel,
        timeout_sec=settings.camera_timeout_sec,
    )
