import logging
import math
import os
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.shared.db import session_scope
from apps.shared.models import GeocodeCache

log = logging.getLogger(__name__)

# Tashkent bbox: SW corner ~ (lng 69.10, lat 41.16), NE ~ (lng 69.50, lat 41.40).
# Yandex bbox param order: lng,lat~lng,lat. `rspn=1` makes it a hard constraint.
TASHKENT_BBOX = "69.10,41.16~69.50,41.40"

# Uzbekistan rough envelope used to sanity-check coordinates before routing.
UZ_LAT_MIN, UZ_LAT_MAX = 37.0, 46.0
UZ_LNG_MIN, UZ_LNG_MAX = 55.0, 74.0


def _in_uzbekistan(lat: float, lng: float) -> bool:
    return UZ_LAT_MIN <= lat <= UZ_LAT_MAX and UZ_LNG_MIN <= lng <= UZ_LNG_MAX


@dataclass(frozen=True)
class GeocodeResult:
    lat: float | None
    lng: float | None
    matched_text: str | None


def _normalize_query(q: str) -> str:
    return " ".join(q.lower().split())


def geocode(query: str, bbox: str | None = TASHKENT_BBOX) -> GeocodeResult:
    cache_key = f"{_normalize_query(query)}|{bbox or ''}"
    with session_scope() as s:
        row = s.execute(
            select(GeocodeCache).where(GeocodeCache.query_norm == cache_key)
        ).scalar_one_or_none()
        if row is not None:
            return GeocodeResult(row.lat, row.lng, row.matched_text)

    api_key = os.environ.get("YANDEX_GEOCODE_API_KEY", "")
    params = {
        "apikey": api_key,
        "format": "json",
        "geocode": query,
        "lang": "ru_RU",
        "results": 1,
    }
    if bbox:
        params["bbox"] = bbox
        params["rspn"] = 1
    r = httpx.get(
        "https://geocode-maps.yandex.ru/1.x/",
        params=params,
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
                query_norm=cache_key,
                lat=result.lat,
                lng=result.lng,
                matched_text=result.matched_text,
                raw_response=data,
            )
            .on_conflict_do_nothing(index_elements=["query_norm"])
        )
        s.execute(stmt)
    return result


def _haversine_minutes(
    origin_lat: float, origin_lng: float,
    dest_lat: float, dest_lng: float,
    mode: str,
) -> int:
    R = 6371.0
    phi1 = math.radians(origin_lat)
    phi2 = math.radians(dest_lat)
    dphi = math.radians(dest_lat - origin_lat)
    dlam = math.radians(dest_lng - origin_lng)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    km = 2 * R * math.asin(math.sqrt(a))
    avg_speed = {"walk": 5.0, "car": 30.0, "public": 18.0}.get(mode, 20.0)
    return max(1, int((km / avg_speed) * 60))


def route_minutes(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    mode: str = "car",
) -> int | None:
    """Return travel time in minutes using Yandex Routing API, haversine fallback.

    Returns None if either endpoint sits outside Uzbekistan — that almost always
    means geocoding produced a garbage hit (e.g. matching a venue name to a
    same-named place on another continent) and any "route" would be meaningless.
    """
    if not (_in_uzbekistan(origin_lat, origin_lng) and _in_uzbekistan(dest_lat, dest_lng)):
        log.warning(
            "route_minutes: coords outside UZ envelope, refusing route "
            "origin=(%s,%s) dest=(%s,%s)",
            origin_lat, origin_lng, dest_lat, dest_lng,
        )
        return None

    _MODE_MAP = {"car": "driving", "public": "transit", "walk": "walking"}
    yandex_mode = _MODE_MAP.get(mode, "driving")

    api_key = os.environ.get("YANDEX_ROUTING_API_KEY", "")
    if api_key:
        try:
            r = httpx.get(
                "https://api.routing.yandex.net/v2/route",
                params={
                    "apikey": api_key,
                    "waypoints": f"{origin_lat},{origin_lng}|{dest_lat},{dest_lng}",
                    "mode": yandex_mode,
                    "lang": "ru_RU",
                },
                timeout=10.0,
            )
            r.raise_for_status()
            data = r.json()
            legs = data.get("route", {}).get("legs", [])
            if legs:
                duration = legs[0].get("duration")
                if isinstance(duration, dict):
                    duration_s = int(duration.get("value", 0))
                else:
                    duration_s = int(duration or 0)
                if duration_s > 0:
                    return max(1, duration_s // 60)
        except Exception as exc:
            log.warning("yandex routing API failed (%s), using haversine fallback", exc)

    return _haversine_minutes(origin_lat, origin_lng, dest_lat, dest_lng, mode)
