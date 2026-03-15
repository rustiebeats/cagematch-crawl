import re
import logging
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_wrestler_list(soup: BeautifulSoup) -> list[int]:
    """Extract wrestler IDs from a workers index page."""
    ids = []
    for a in soup.select("a[href*='id=2&nr=']"):
        href = a.get("href", "")
        # exclude links with extra page params that aren't plain profiles
        if "page=" in href:
            continue
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


def _parse_height(val: str) -> Optional[float]:
    m = re.search(r"(\d+)\s*cm", val)
    if m:
        return float(m.group(1))
    # fallback: try feet/inches
    m = re.search(r"(\d+)'(\d+)", val)
    if m:
        return round((int(m.group(1)) * 12 + int(m.group(2))) * 2.54, 1)
    return None


def _parse_weight(val: str) -> Optional[float]:
    m = re.search(r"(\d+)\s*kg", val)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*lbs?", val)
    if m:
        return round(int(m.group(1)) * 0.453592, 1)
    return None


def parse_wrestler(wrestler_id: int, soup: BeautifulSoup) -> tuple[dict, list[str]]:
    info = _info_box(soup)
    rating, votes = _parse_rating(soup)

    name_el = soup.select_one(".WorkerName, h1, .HeaderBox h1")
    name = name_el.get_text(strip=True) if name_el else info.get("Name", "")

    height_raw = info.get("Height", "")
    weight_raw = info.get("Weight", "")

    # Gimmicks / aliases
    gimmicks = []
    gimmick_el = soup.select_one(".InformationBoxContents a[href*='id=2&nr=']")
    for row in soup.select(".InformationBoxRow"):
        label_el = row.select_one(".InformationBoxTitle")
        if label_el and "Gimmick" in label_el.get_text():
            value_el = row.select_one(".InformationBoxContents")
            if value_el:
                gimmicks = [g.strip() for g in value_el.get_text(separator="\n").split("\n") if g.strip()]

    data = {
        "id": wrestler_id,
        "name": name,
        "birthday": info.get("Birthday", info.get("Born", "")),
        "birthplace": info.get("Birthplace", info.get("Hometown", "")),
        "gender": info.get("Gender", ""),
        "height_cm": _parse_height(height_raw),
        "weight_kg": _parse_weight(weight_raw),
        "style": info.get("Style", ""),
        "trainers": info.get("Trainer", info.get("Trained by", "")),
        "signature_moves": info.get("Signature moves", ""),
        "rating": rating,
        "votes": votes,
    }
    return data, gimmicks


def parse_wrestler_matches(soup: BeautifulSoup) -> list[dict]:
    """Parse the match history page (page=4) for a wrestler."""
    matches = []
    for row in soup.select("tr.TRow1, tr.TRow2"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        date_text = cells[0].get_text(strip=True) if len(cells) > 0 else ""
        # event link
        event_id = None
        event_a = row.select_one("a[href*='id=1&nr=']")
        if event_a:
            m = re.search(r"nr=(\d+)", event_a.get("href", ""))
            if m:
                event_id = int(m.group(1))
        matches.append({
            "date": date_text,
            "event_id": event_id,
            "result": cells[-1].get_text(strip=True) if cells else "",
        })
    return matches
