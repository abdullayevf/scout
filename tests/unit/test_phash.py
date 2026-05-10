from pathlib import Path

import respx
from httpx import Response

from apps.shared.enrichment.images import compute_phash, download_and_phash


def test_compute_phash_deterministic():
    h1 = compute_phash(Path("tests/fixtures/sample.jpg").read_bytes())
    h2 = compute_phash(Path("tests/fixtures/sample.jpg").read_bytes())
    assert h1 == h2 and len(h1) == 16


@respx.mock
def test_download_and_phash(tmp_path):
    img_bytes = Path("tests/fixtures/sample.jpg").read_bytes()
    respx.get("https://example.test/img.jpg").mock(
        return_value=Response(200, content=img_bytes)
    )
    saved_path, h = download_and_phash(
        "https://example.test/img.jpg", storage_dir=str(tmp_path)
    )
    assert saved_path.endswith(".jpg")
    assert len(h) == 16
