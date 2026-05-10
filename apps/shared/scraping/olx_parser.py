"""OLX list-page parser.

Parses an OLX category list page (e.g. arenda-kvartir) into a list of
:class:`ListCard` dataclasses.

Selectors are chosen against the current OLX DOM (as of 2026-05).  The page
uses CSS-in-JS (emotion) which injects ``<style data-emotion>`` tags directly
inside many elements — we strip those before reading text so that CSS noise
does not pollute field values.
"""

from __future__ import annotations

from dataclasses import dataclass
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
