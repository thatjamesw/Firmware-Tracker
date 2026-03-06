from __future__ import annotations

import re
from html import unescape
from typing import Any

from .common import as_iso_date, fetch_bytes, normalize_space


def sync_godox_listing(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source["url"]
    title_contains = source.get("title_contains", "").lower()

    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")

    blocks = re.findall(r'<div class="item">\s*<div class="tit">(.*?)</div>\s*<div class="text">(.*?)</div>\s*</div>', html, re.S)
    parsed: list[dict[str, Any]] = []

    for tit_html, text_html in blocks:
        title = normalize_space(unescape(re.sub(r"<[^>]+>", " ", tit_html)))
        version_match = re.search(r"<span>\s*V?([0-9][0-9A-Za-z.]+)\s*</span>", tit_html, re.I)
        if not version_match:
            version_match = re.search(r"V\s*([0-9][0-9A-Za-z.]+)", title)
        if not version_match:
            continue
        version = version_match.group(1)

        href_match = re.search(r'<a href="([^"]+)" class="download">', tit_html)
        href = unescape(href_match.group(1)).strip() if href_match else ""
        if href and not href.startswith("http"):
            href = f"https://www.godox.com{href}"

        date_match = re.search(r'Release Date</div>\s*<div class="c">([^<]+)</div>', text_html)
        release_date = as_iso_date(date_match.group(1)) if date_match else ""

        upd_match = re.search(r'Updated Contents</div>\s*<div class="c">(.*?)</div>', text_html, re.S)
        note = ""
        if upd_match:
            note = normalize_space(unescape(re.sub(r"<[^>]+>", " ", upd_match.group(1))))

        parsed.append(
            {
                "title": title,
                "version": version,
                "released_time": release_date,
                "download_url": href,
                "note": note,
            }
        )

    if title_contains:
        parsed = [item for item in parsed if title_contains in item["title"].lower()]

    if not parsed:
        return []

    parsed.sort(key=lambda item: (item["released_time"], item["version"]), reverse=True)
    latest = parsed[0]

    note = latest["note"] if latest["note"] else "Official Godox firmware listing"
    if latest["download_url"]:
        note += f". Download: {latest['download_url']}"

    return [
        {
            "version": latest["version"],
            "released_time": latest["released_time"],
            "release_note": {"en": note},
            "arb": None,
            "active": True,
        }
    ]
