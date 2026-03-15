import re
import logging
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_title_list(soup: BeautifulSoup) -> list[int]:
    """Extract title IDs from a title history index page."""
    ids = []
    for a in soup.select("a[href*='id=5&nr=']"):
        href = a.get("href", "")
        m = re.search(r"nr=(\d+)", href)
        if m:
            ids.append(int(m.group(1)))
    return list(dict.fromkeys(ids))


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


def _extract_promotion_id(soup: BeautifulSoup) -> Optional[int]:
    for a in soup.select("a[href*='id=8&nr=']"):
        href = a.get("href", "")
        m = re.search(r"nr=(\d+)", href)
        if m:
            return int(m.group(1))
    return None


def parse_title(title_id: int, soup: BeautifulSoup) -> dict:
    info = _info_box(soup)
    rating, votes = _parse_rating(soup)
    promotion_id = _extract_promotion_id(soup)

    name_el = soup.select_one("h1, .HeaderBox h1, .TitleName")
    if not name_el:
        name_el = soup.select_one("title")
    name = name_el.get_text(strip=True) if name_el else info.get("Title", "")

    status = info.get("Status", "")

    return {
        "id": title_id,
        "name": name,
        "promotion_id": promotion_id,
        "status": status,
        "rating": rating,
        "votes": votes,
    }


def parse_title_reigns(title_id: int, soup: BeautifulSoup) -> list[dict]:
    """Parse title reign rows from a title detail page."""
    reigns = []
    reign_number = 0

    for row in soup.select("tr.TRow1, tr.TRow2"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        wrestler_a = row.select_one("a[href*='id=2&nr=']")
        if not wrestler_a:
            continue

        wrestler_m = re.search(r"nr=(\d+)", wrestler_a.get("href", ""))
        if not wrestler_m:
            continue
        wrestler_id = int(wrestler_m.group(1))

        reign_number += 1
        texts = [c.get_text(strip=True) for c in cells]

        date_won = texts[0] if len(texts) > 0 else ""
        date_lost = texts[2] if len(texts) > 2 else ""
        days_text = texts[3] if len(texts) > 3 else ""
        location = texts[4] if len(texts) > 4 else ""

        days = None
        days_m = re.search(r"(\d+)", days_text)
        if days_m:
            days = int(days_m.group(1))

        reigns.append({
            "title_id": title_id,
            "wrestler_id": wrestler_id,
            "reign_number": reign_number,
            "date_won": date_won,
            "date_lost": date_lost,
            "days": days,
            "location": location,
        })

    return reigns
