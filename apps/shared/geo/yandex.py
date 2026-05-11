import os
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
        stmt = (
            pg_insert(GeocodeCache)
            .values(
                query_norm=norm,
                lat=result.lat,
                lng=result.lng,
                matched_text=result.matched_text,
                raw_response=data,
            )
            .on_conflict_do_nothing(index_elements=["query_norm"])
        )
        s.execute(stmt)
    return result


def route_minutes(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    mode: str = "car",
) -> int | None:
    """Return travel time in minutes from origin to dest.

    Uses a great-circle distance estimate as a fallback for Plan 3 MVP.
    A real Yandex Routing API integration can replace this later.
    """
    import math

    R = 6371.0
    phi1 = math.radians(origin_lat)
    phi2 = math.radians(dest_lat)
    dphi = math.radians(dest_lat - origin_lat)
    dlam = math.radians(dest_lng - origin_lng)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    km = 2 * R * math.asin(math.sqrt(a))
    avg_speed = {"walk": 5.0, "car": 30.0, "public": 18.0}.get(mode, 20.0)
    minutes = int((km / avg_speed) * 60)
    return max(1, minutes)
