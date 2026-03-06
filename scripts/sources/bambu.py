from __future__ import annotations

import re
from html import unescape
from typing import Any

from .common import fetch_bytes, normalize_space


def sync_bambu_wiki(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source.get("url")
    series = str(source.get("series") or "P1").upper()
    if not isinstance(url, str) or not url:
        return []

    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")

    matches = re.findall(
        r"<h2[^>]*>\s*.*?(P1\s*series\s*(?:Version|version)\s*([0-9.]+)\s*\((\d{8})\)).*?</h2>",
        html,
        re.I | re.S,
    )
    if not matches:
        return []

    candidates: list[dict[str, str]] = []
    for full_title, version, yyyymmdd in matches:
        date_iso = f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
        candidates.append(
            {
                "title": normalize_space(unescape(re.sub(r"<[^>]+>", " ", full_title))),
                "version": version.strip(),
                "released_time": date_iso,
            }
        )

    candidates.sort(key=lambda x: (x["released_time"], x["version"]), reverse=True)
    latest = candidates[0]

    return [
        {
            "version": latest["version"],
            "released_time": latest["released_time"],
            "release_note": {
                "en": f"Official Bambu Lab Wiki {series} release history. Entry: {latest['title']}."
            },
            "arb": None,
            "active": True,
        }
    ]
