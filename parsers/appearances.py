import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def parse_appearances_page(soup: BeautifulSoup) -> list[dict]:
    """
    Parse one page of a wrestler's match history (?id=2&nr=X&page=4&pageNum=N).
    Returns list of {"date": "DD/MM/YYYY", "promotion_name": str}.
    """
    rows = []
    for row in soup.select("tr.TRow1, tr.TRow2"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        date_text = cells[1].get_text(strip=True)
        if not re.match(r"\d{2}\.\d{2}\.\d{4}", date_text):
            continue
        date = date_text.replace(".", "/")  # DD.MM.YYYY → DD/MM/YYYY

        # One row may have multiple promotions — emit one entry per promotion link.
        # Promotion ID comes from nr= in the href (reliable; gif src can have date suffixes).
        promo_links = row.select("a[href*='id=8&nr=']")
        if promo_links:
            for promo_a in promo_links:
                href = promo_a.get("href", "")
                m = re.search(r"nr=(\d+)", href)
                if not m:
                    continue
                promotion_id = int(m.group(1))
                img = promo_a.find("img")
                if img:
                    promotion_name = img.get("title") or img.get("alt") or ""
                else:
                    promotion_name = promo_a.get_text(strip=True)
                rows.append({"date": date, "promotion_id": promotion_id, "promotion_name": promotion_name})
        else:
            promotion_name = cells[2].get_text(strip=True)
            if not promotion_name:
                continue
            rows.append({"date": date, "promotion_id": None, "promotion_name": promotion_name})
    return rows


def has_rows(soup: BeautifulSoup) -> bool:
    return bool(soup.select_one("tr.TRow1, tr.TRow2"))
