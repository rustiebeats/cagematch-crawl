import re
import logging
from typing import Optional
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


def parse_promotion_list(soup: BeautifulSoup) -> list[int]:
    """Extract promotion IDs from a promotions index page."""
    ids = []
    for a in soup.select("a[href*='id=8&nr=']"):
        href = a.get("href", "")
        m = re.search(r"nr=(\d+)", href)
        if m:
            ids.append(int(m.group(1)))
    return list(dict.fromkeys(ids))  # deduplicate, preserve order


def parse_promotion_list_count(soup: BeautifulSoup) -> int:
    """Extract total number of promotions from the index page."""
    text = soup.get_text()
    m = re.search(r"(\d[\d,]*)\s+promotions?", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return 0


def _info_box(soup: BeautifulSoup) -> dict[str, str]:
    result = {}
    for row in soup.select(".InformationBoxRow"):
        label_el = row.select_one(".InformationBoxTitle")
        value_el = row.select_one(".InformationBoxContents")
        if label_el and value_el:
            key = label_el.get_text(strip=True).rstrip(":")
            val = value_el.get_text(separator=" ", strip=True)
            result[key] = val
    return result


def _parse_rating(soup: BeautifulSoup) -> tuple[Optional[float], Optional[int]]:
    rating_el = soup.select_one(".RatingBox .RatingValue")
    votes_el = soup.select_one(".RatingBox .RatingVotes")
    rating = None
    votes = None
    if rating_el:
        try:
            rating = float(rating_el.get_text(strip=True))
        except ValueError:
            pass
    if votes_el:
        m = re.search(r"(\d[\d,]*)", votes_el.get_text())
        if m:
            votes = int(m.group(1).replace(",", ""))
    return rating, votes


def parse_promotion(promotion_id: int, soup: BeautifulSoup) -> dict:
    info = _info_box(soup)
    rating, votes = _parse_rating(soup)

    name_el = soup.select_one(".PromotionHeaderLogo, h1, .HeaderBox h1, .PromotionName")
    if not name_el:
        name_el = soup.select_one("title")
    name = name_el.get_text(strip=True) if name_el else info.get("Name", "")

    return {
        "id": promotion_id,
        "name": name,
        "location": info.get("Location", info.get("Country", "")),
        "years": info.get("Years active", info.get("Active", "")),
        "rating": rating,
        "votes": votes,
    }


def parse_promotion_event_ids(soup: BeautifulSoup) -> list[int]:
    """Extract event IDs from a promotion's event list page."""
    ids = []
    for a in soup.select("a[href*='id=1&nr=']"):
        href = a.get("href", "")
        m = re.search(r"nr=(\d+)", href)
        if m:
            ids.append(int(m.group(1)))
    return list(dict.fromkeys(ids))
