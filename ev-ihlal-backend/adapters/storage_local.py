"""Yerel object storage — Faz 1. Görseller bir klasöre yazılır.

Arayüz (ObjectStorage) Faz 2'de S3'e (boto3) geçmeye hazırdır: put/get/delete/exists
aynı kalır, yalnızca bu sınıf S3StorageWithBoto3 ile değişir.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from interfaces import ObjectStorage

log = logging.getLogger("evihlal.storage")


class LocalObjectStorage(ObjectStorage):
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # key içinde alt klasör olabilir (ör. "ST-01/2026.../uuid.jpg")
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError("Geçersiz storage key (path traversal).")
        return p

    def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        log.info("Görsel yazıldı: %s (%d bayt)", key, len(data))
        return f"file://{p.as_posix()}"

    def get_bytes(self, key: str) -> Optional[bytes]:
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()
            log.info("Görsel silindi (retention): %s", key)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()
