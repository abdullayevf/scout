"""OLX list-page and detail-page parser.

Parses OLX category list pages and individual detail pages into structured
dataclasses.

Selectors are chosen against the current OLX DOM (as of 2026-05).  The page
uses CSS-in-JS (emotion) which injects ``<style data-emotion>`` tags directly
inside many elements — we strip those before reading text so that CSS noise
does not pollute field values.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from selectolax.parser import HTMLParser, Node

OLX_BASE = "https://www.olx.uz"


@dataclass(frozen=True)
class ListCard:
    source_listing_id: str
    url: str
    title: str
    price_raw: str | None
    location_text: str | None
    posted_at_text: str | None


def parse_list_page(html: str) -> list[ListCard]:
    """Parse an OLX category list page into cards.

    The page structure (2026-05):

    * Each listing lives in an element with ``data-testid="l-card"`` and
      carries its OLX numeric ID in the ``id`` attribute.
    * Inside, ``data-testid="ad-card-title"`` wraps an ``<a>`` then an
      ``<h4>`` with the title text.
    * ``data-testid="ad-price"`` is a ``<p>`` whose *direct* text node
      contains the price (subsequent ``<style>`` and ``<span>`` children
      carry CSS and secondary labels — we ignore them).
    * ``data-testid="location-date"`` is a ``<p>`` with combined
      "Location - date" text.
    """
    tree = HTMLParser(html)
    cards: list[ListCard] = []

    for card_el in tree.css('[data-testid="l-card"]'):
        # --- source_listing_id ------------------------------------------
        source_listing_id = card_el.attributes.get("id", "")

        # --- URL + fallback id extraction --------------------------------
        title_container = card_el.css_first('[data-testid="ad-card-title"]')
        if title_container is None:
            continue
        title_a = title_container.css_first("a")
        if title_a is None:
            continue

        href = title_a.attributes.get("href") or ""
        if not href:
            continue
        url = urljoin(OLX_BASE, href.split("?")[0])

        # If the card had no numeric id, derive it from the URL slug
        if not source_listing_id and "-ID" in url:
            source_listing_id = url.rstrip("/").split("-ID")[-1].split(".")[0]

        # --- title -------------------------------------------------------
        h4 = title_container.css_first("h4")
        title = h4.text(strip=True) if h4 else title_a.text(strip=True)

        # --- price -------------------------------------------------------
        price_raw = _price_text(card_el)

        # --- location / date (OLX packs both into one node) --------------
        location_text = _first_direct_text(card_el, '[data-testid="location-date"]')
        posted_at_text = location_text  # refined later by detail-page parser

        cards.append(
            ListCard(
                source_listing_id=source_listing_id,
                url=url,
                title=title,
                price_raw=price_raw,
                location_text=location_text,
                posted_at_text=posted_at_text,
            )
        )

    return cards


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _price_text(card_el: Node) -> str | None:
    """Extract the numeric price text from the ad-price element.

    OLX embeds ``<style data-emotion>`` tags directly inside the ``<p>``
    element, followed by optional ``<span>`` children ("Договорная", etc.).
    We iterate child nodes and return the **first non-empty direct text
    node** which contains the numeric amount or currency string.  If the
    element has no direct text node (price is purely "Договорная" in a
    span), we fall back to the first span's text.
    """
    price_el = card_el.css_first('[data-testid="ad-price"]')
    if price_el is None:
        return None

    # Walk direct children looking for a text node
    for node in price_el.iter(include_text=True):
        tag = getattr(node, "tag", None)
        if tag == "-text":
            t = node.text().strip() if node.text() else ""
            if t:
                return t

    # Fallback: first span (e.g. "Договорная")
    span = price_el.css_first("span")
    if span:
        t = span.text(strip=True)
        if t:
            return t

    return None


def _first_direct_text(card_el: Node, selector: str) -> str | None:
    """Return stripped text from the first element matching *selector*,
    ignoring any embedded ``<style>`` children.
    """
    el = card_el.css_first(selector)
    if el is None:
        return None
    # The location-date <p> has no inline style children so plain text() works,
    # but we decompose any style nodes defensively.
    for style in el.css("style"):
        style.decompose()
    txt = el.text(strip=True)
    return txt if txt else None


# ---------------------------------------------------------------------------
# Detail page
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DetailPage:
    """Parsed fields from an OLX listing detail page."""

    source_listing_id: str | None
    url: str | None
    title: str
    description_raw: str
    price_raw: str | None
    currency_raw: str | None
    location_text: str | None
    rooms: int | None
    floor: int | None
    total_floors: int | None
    posted_at_text: str | None
    images: list[str] = field(default_factory=list)
    raw_phone_text: str | None = None  # only present if statically embedded; usually None


def parse_detail_page(html: str) -> DetailPage:
    """Parse an OLX listing detail page into a :class:`DetailPage`.

    Strategy (2026-05 DOM):

    1. Extract structured data from the JSON-LD ``<script>`` block that OLX
       embeds in every listing page.  This gives us title, description, URL,
       SKU (listing ID), images, price, currency, and area name reliably.
    2. Fall back to ``data-cy`` / ``data-testid`` DOM selectors for fields not
       present in JSON-LD (posted_at, floor, rooms, raw phone).
    3. Rooms and floor info are parsed from the
       ``[data-testid="ad-parameters-container"]`` ``<p>`` elements.
    """
    tree = HTMLParser(html)

    # ------------------------------------------------------------------ #
    # 1. JSON-LD structured data (most reliable source)
    # ------------------------------------------------------------------ #
    ld: dict = {}
    for script in tree.css("script"):
        t = script.text() or ""
        if '"@type":"Product"' in t or '"@type": "Product"' in t:
            try:
                ld = json.loads(t)
                break
            except json.JSONDecodeError:
                pass

    offers: dict = ld.get("offers", {})
    area: dict = offers.get("areaServed", {})

    # Title
    title_ld = ld.get("name", "")

    # Description
    description_ld = ld.get("description", "")

    # URL + source listing ID
    url_ld = ld.get("url") or None
    source_listing_id_ld = ld.get("sku") or None

    # Images — JSON-LD image field is a list of CDN URLs
    images_ld: list[str] = ld.get("image", [])
    if isinstance(images_ld, str):
        images_ld = [images_ld]

    # Price / currency
    price_raw_ld: str | None = None
    price_val = offers.get("price")
    if price_val is not None:
        price_raw_ld = str(price_val)
    currency_raw_ld: str | None = offers.get("priceCurrency") or None

    # Location
    location_ld: str | None = area.get("name") or None

    # ------------------------------------------------------------------ #
    # 2. DOM fallbacks for fields not in JSON-LD
    # ------------------------------------------------------------------ #

    # Title fallback
    if not title_ld:
        title_ld = _strip_styles_text(tree, '[data-cy="offer_title"]') or ""

    # Description fallback — strip the "Описание" header that OLX adds
    if not description_ld:
        raw_desc = _strip_styles_text(tree, '[data-cy="ad_description"]') or ""
        # OLX prepends "Описание" as a heading inside the same element
        if raw_desc.startswith("Описание"):
            raw_desc = raw_desc[8:].lstrip()
        description_ld = raw_desc

    # Price fallback
    if price_raw_ld is None:
        price_el = tree.css_first('[data-testid="ad-price-container"]')
        if price_el:
            h3 = price_el.css_first("h3")
            if h3:
                for s in h3.css("style"):
                    s.decompose()
                price_raw_ld = h3.text(strip=True) or None

    # Posted-at
    posted_at_text = _strip_styles_text(tree, '[data-testid="ad-posted-at"]')

    # ------------------------------------------------------------------ #
    # 3. Parameters block — rooms, floor, total_floors
    # ------------------------------------------------------------------ #
    rooms: int | None = None
    floor: int | None = None
    total_floors: int | None = None

    params_el = tree.css_first('[data-testid="ad-parameters-container"]')
    if params_el:
        for p in params_el.css("p"):
            for s in p.css("style"):
                s.decompose()
            txt = p.text(strip=True)
            if not txt:
                continue
            low = txt.lower()
            if "количество комнат" in low:
                rooms = _extract_int(txt)
            elif "этажность дома" in low:
                total_floors = _extract_int(txt)
            elif low.startswith("этаж:") or low.startswith("этаж "):
                floor = _extract_int(txt)

    # ------------------------------------------------------------------ #
    # 4. Images fallback — scan img tags with OLX CDN domain
    # ------------------------------------------------------------------ #
    if not images_ld:
        for img in tree.css("img"):
            src = img.attributes.get("src") or img.attributes.get("data-src") or ""
            if "apollo.olxcdn.com" in src or "olx.uz" in src:
                if src not in images_ld:
                    images_ld.append(src)

    # ------------------------------------------------------------------ #
    # 5. source_listing_id fallback — derive from URL slug
    # ------------------------------------------------------------------ #
    if not source_listing_id_ld and url_ld and "-ID" in url_ld:
        source_listing_id_ld = url_ld.rstrip("/").split("-ID")[-1].split(".")[0]

    return DetailPage(
        source_listing_id=source_listing_id_ld,
        url=url_ld,
        title=title_ld,
        description_raw=description_ld,
        price_raw=price_raw_ld,
        currency_raw=currency_raw_ld,
        location_text=location_ld,
        rooms=rooms,
        floor=floor,
        total_floors=total_floors,
        posted_at_text=posted_at_text,
        images=list(images_ld),
        raw_phone_text=None,
    )


# ---------------------------------------------------------------------------
# Detail-page helpers
# ---------------------------------------------------------------------------


def _strip_styles_text(tree: HTMLParser, selector: str) -> str | None:
    """Return text from the first element matching *selector* after stripping
    embedded ``<style>`` children (OLX emotion CSS injection).
    """
    el = tree.css_first(selector)
    if el is None:
        return None
    for style in el.css("style"):
        style.decompose()
    txt = el.text(strip=True)
    return txt if txt else None


def _detect_currency(price_raw: str | None) -> str | None:
    """Detect ISO currency code from a raw price string.

    Examples::

        >>> _detect_currency("1 200 USD")
        'USD'
        >>> _detect_currency("4 500 000 сум")
        'UZS'
        >>> _detect_currency(None)
        None
    """
    if price_raw is None:
        return None
    low = price_raw.lower()
    if "usd" in low or "$" in low or "у.е" in low:  # noqa: RUF001
        return "USD"
    if "uzs" in low or "сум" in low or "сўм" in low:
        return "UZS"
    return None


def _extract_int(text: str | None) -> int | None:
    """Extract the first integer from *text*.

    Examples::

        >>> _extract_int("Количество комнат: 2")
        2
        >>> _extract_int(None)
        None
    """
    if not text:
        return None
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _extract_floor_pair(text: str | None) -> tuple[int | None, int | None]:
    """Extract a floor/total-floors pair from strings like "3/10" or "Этаж: 3 из 10".

    Returns ``(floor, total_floors)``.

    Examples::

        >>> _extract_floor_pair("3/10")
        (3, 10)
        >>> _extract_floor_pair("Этаж: 3")
        (3, None)
        >>> _extract_floor_pair(None)
        (None, None)
    """
    if not text:
        return None, None
    m = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"\d+", text)
    if m:
        return int(m.group()), None
    return None, None
