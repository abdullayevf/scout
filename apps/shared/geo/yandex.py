import os
from dataclasses import dataclass

import httpx
from sqlalchemy import select

from apps.shared.db import session_scope
from apps.shared.models import GeocodeCache


@dataclass(frozen=True)
class GeocodeResult:
    lat: float | None
    lng: float | None
    matched_text: str | None


def _normalize_query(q: str) -> str:
    return " ".join(q.lower().split())


def geocode(query: str) -> GeocodeResult:
    norm = _normalize_query(query)
    with session_scope() as s:
        row = s.execute(
            select(GeocodeCache).where(GeocodeCache.query_norm == norm)
        ).scalar_one_or_none()
        if row is not None:
            return GeocodeResult(row.lat, row.lng, row.matched_text)

    api_key = os.environ.get("YANDEX_GEOCODE_API_KEY", "")
    r = httpx.get(
        "https://geocode-maps.yandex.ru/1.x/",
        params={
            "apikey": api_key,
            "format": "json",
            "geocode": query,
            "lang": "ru_RU",
            "results": 1,
        },
        timeout=10.0,
    )
    r.raise_for_status()
    data = r.json()
    feats = (
        data.get("response", {})
        .get("GeoObjectCollection", {})
        .get("featureMember", [])
    )
    if not feats:
        result = GeocodeResult(None, None, None)
    else:
        obj = feats[0]["GeoObject"]
        lng_str, lat_str = obj["Point"]["pos"].split()
        result = GeocodeResult(
            lat=float(lat_str),
            lng=float(lng_str),
            matched_text=obj["metaDataProperty"]["GeocoderMetaData"]["text"],
        )
    with session_scope() as s:
        s.add(
            GeocodeCache(
                query_norm=norm,
                lat=result.lat,
                lng=result.lng,
                matched_text=result.matched_text,
                raw_response=data,
            )
        )
    return result
