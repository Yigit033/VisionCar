"""Yapılandırma yükleme — config.yaml (yoksa config.example.yaml) + ortam değişkeni ezme.

Kimlik bilgileri koda hardcode EDİLMEZ. Şifre/URL şu sırayla çözülür:
  1. VISIONCAR_RTSP_URL  -> tüm rtsp_url'i ezer
  2. rtsp_url içindeki {password} <- VISIONCAR_RTSP_PASSWORD ile doldurulur
  3. aksi halde config dosyasındaki değer aynen kullanılır
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

# Proje kökü: bu dosya core/config.py -> kök bir üst.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = PROJECT_ROOT / "config.yaml"
_EXAMPLE = PROJECT_ROOT / "config.example.yaml"


def config_path() -> Path:
    """Kullanılacak config dosyasının yolu (gerçek varsa o, yoksa şablon)."""
    return _CONFIG if _CONFIG.exists() else _EXAMPLE


def load_config() -> dict[str, Any]:
    """Config'i yükle ve ortam değişkeni ezmelerini uygula."""
    path = config_path()
    with open(path, "r", encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    cam = cfg.setdefault("camera", {})

    env_url = os.environ.get("VISIONCAR_RTSP_URL")
    if env_url:
        cam["rtsp_url"] = env_url

    url = cam.get("rtsp_url", "")
    if isinstance(url, str) and "{password}" in url:
        pw = os.environ.get("VISIONCAR_RTSP_PASSWORD")
        if pw:
            cam["rtsp_url"] = url.replace("{password}", pw)
        # pw yoksa {password} yer tutucu olduğu gibi kalır; capture katmanı uyarır.

    return cfg


def resolve_path(rel: str) -> Path:
    """Config'teki göreli yolu proje köküne göre mutlak yola çevir."""
    p = Path(rel)
    return p if p.is_absolute() else (PROJECT_ROOT / p)


def save_roi(roi: dict[str, int | None]) -> None:
    """ROI'yi gerçek config.yaml'a yaz (yoksa şablondan türeterek oluştur).

    Sadece roi bölümünü günceller; diğer alanları korur.
    """
    if _CONFIG.exists():
        with open(_CONFIG, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        with open(_EXAMPLE, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    cfg["roi"] = {k: roi.get(k) for k in ("x", "y", "w", "h")}
    with open(_CONFIG, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def redact(cfg: dict[str, Any]) -> dict[str, Any]:
    """Loglamak/göstermek için şifreyi gizlenmiş bir kopya döndür."""
    safe = copy.deepcopy(cfg)
    url = safe.get("camera", {}).get("rtsp_url", "")
    if isinstance(url, str) and "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.split("@", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            creds = f"{user}:****"
        safe["camera"]["rtsp_url"] = f"{scheme}://{creds}@{host}"
    return safe
