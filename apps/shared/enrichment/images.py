import hashlib
import io
from pathlib import Path

import httpx
import imagehash
from PIL import Image


def compute_phash(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    return str(imagehash.phash(img))  # 16-char hex


def download_and_phash(
    url: str, *, storage_dir: str, timeout: float = 15.0
) -> tuple[str, str]:
    r = httpx.get(url, timeout=timeout)
    r.raise_for_status()
    content = r.content
    h_url = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    ext = Path(url.split("?")[0]).suffix.lower() or ".jpg"
    out = Path(storage_dir) / f"{h_url}{ext}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    return (str(out), compute_phash(content))
