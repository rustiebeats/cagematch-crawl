import re
import logging
from typing import Optional
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_event_list(soup: BeautifulSoup) -> list[int]:
    """Extract event IDs from an event listing page."""
    ids = []
    for a in soup.select("a[href*='id=1&nr=']"):
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


def parse_event(event_id: int, soup: BeautifulSoup) -> dict:
    info = _info_box(soup)
    rating, votes = _parse_rating(soup)
    promotion_id = _extract_promotion_id(soup)

    name_el = soup.select_one(".EventHeaderLogo, h1, .HeaderBox h1, .EventName")
    if not name_el:
        name_el = soup.select_one("title")
    name = name_el.get_text(strip=True) if name_el else info.get("Event", "")

    return {
        "id": event_id,
        "name": name,
        "date": info.get("Date", ""),
        "promotion_id": promotion_id,
        "venue": info.get("Arena", info.get("Venue", "")),
        "location": info.get("Location", info.get("City", "")),
        "rating": rating,
        "votes": votes,
    }


def parse_event_promotions(soup: BeautifulSoup) -> list[dict]:
    """
    Return list of {"promotion_id": int, "promotion_name": str} from the
    "Promotion:" InformationBoxRow on an event detail page.
    Returns [] if the field is absent or has no parseable links.
    """
    for row in soup.select(".InformationBoxRow"):
        label_el = row.select_one(".InformationBoxTitle")
        if not label_el or label_el.get_text(strip=True).rstrip(":") != "Promotion":
            continue
        contents_el = row.select_one(".InformationBoxContents")
        if not contents_el:
            return []
        promos = []
        for a in contents_el.select("a[href*='id=8&nr=']"):
            href = a.get("href", "")
            m = re.search(r"nr=(\d+)", href)
            if m:
                promos.append({
                    "promotion_id": int(m.group(1)),
                    "promotion_name": a.get_text(strip=True),
                })
        return promos
    return []


def parse_event_matches(event_id: int, soup: BeautifulSoup) -> list[dict]:
    """
    Parse embedded match rows from an event detail page.
    Returns list of match dicts each with 'participants' list.
    """
    matches = []
    match_order = 0

    for row in soup.select("tr.TRow1, tr.TRow2, .MatchCard, .Match"):
        cells = row.find_all("td")
        if not cells:
            continue
        match_order += 1

        # Try to detect match type and result from cell text
        match_type = ""
        result = ""
        duration = ""

        full_text = row.get_text(separator="|", strip=True)

        # Duration pattern: MM:SS
        dur_m = re.search(r"\b(\d{1,2}:\d{2})\b", full_text)
        if dur_m:
            duration = dur_m.group(1)

        participants = []
        wrestler_links = row.select("a[href*='id=2&nr=']")
        for i, a in enumerate(wrestler_links):
            href = a.get("href", "")
            m = re.search(r"nr=(\d+)", href)
            if m:
                wrestler_id = int(m.group(1))
                participants.append({
                    "wrestler_id": wrestler_id,
                    "team": str(i + 1),
                    "outcome": "",
                })

        if not participants:
            continue

        matches.append({
            "event_id": event_id,
            "match_order": match_order,
            "match_type": match_type,
            "result": result,
            "duration": duration,
            "participants": participants,
        })

    return matches
