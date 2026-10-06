#!/usr/bin/env python3
"""Script to scrape Google smart speaker and display firmware versions.

Fetches https://support.google.com/googlehome/answer/7365257?hl=en, parses the latest
production and preview firmware versions, and writes them to custom_components/google_home/firmware_versions.json.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from bs4 import BeautifulSoup

_LOGGER = logging.getLogger(__name__)

URL = "https://support.google.com/googlehome/answer/7365257?hl=en"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_and_parse_firmwares() -> dict[str, dict[str, dict[str, str]]]:
    """Fetch and parse firmware versions from Google Home support documentation."""
    req = urllib.request.Request(URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")

    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, dict[str, dict[str, str]]] = {
        "production": {},
        "preview": {},
    }

    current_section: str | None = None
    for elem in soup.find_all(["h2", "table"]):
        if elem.name == "h2":
            text = elem.get_text(strip=True).lower()
            if "preview" in text:
                current_section = "preview"
            elif "production" in text:
                current_section = "production"
            else:
                current_section = None
        elif elem.name == "table" and current_section:
            for tr in elem.find_all("tr"):
                tds = tr.find_all(["td", "th"])
                if len(tds) < 2:
                    continue
                lines = [
                    line.strip() for line in tds[0].stripped_strings if line.strip()
                ]
                if len(lines) >= 2 and "firmware" not in lines[0].lower():
                    dev_name = lines[0]
                    version = lines[1]
                    notes = " ".join(tds[1].stripped_strings)
                    if re.match(r"^[0-9]+(\.[0-9]+)+", version):
                        result[current_section][dev_name] = {
                            "firmware_version": version,
                            "release_notes": notes,
                        }

    if not result["production"]:
        raise ValueError(
            "Scraping failed: No production firmware versions could be parsed from Google support page."
        )

    return result


def main() -> int:
    """Run firmware scraping script."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        data = fetch_and_parse_firmwares()
        out_payload = {
            "updated_at": datetime.now(UTC).isoformat(),
            "source": URL,
            **data,
        }

        output_path = (
            Path(__file__).resolve().parent.parent.parent
            / "custom_components"
            / "google_home"
            / "firmware_versions.json"
        )
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(out_payload, f, indent=2, ensure_ascii=False)
            f.write("\n")

        _LOGGER.info(
            "Successfully scraped and updated firmware versions: %s devices found.",
            len(data["production"]),
        )
        return 0
    except Exception as exc:
        _LOGGER.error("Failed to scrape firmware versions: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
