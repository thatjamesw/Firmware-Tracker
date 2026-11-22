from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from .common import fetch_bytes, make_release_candidate, parse_html, resolve_release_candidates

OTA_HEADING = re.compile(r"(?:OTA\s+)?V(\d+\.\d+\.\d+)\s*[-–]\s*(\w+\s+\d{4})", re.I)
BUILD_LINE = re.compile(r"(?:Systemversion|Multimediaversjon)\s*:\s*(\d+(?:\.\d+)+)", re.I)


def sync_byd_release_notes(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source["url"]
    page = parse_html(fetch_bytes(url, timeout).decode("utf-8", errors="replace"))
    heading = page.find("h1")
    if not heading or not re.search(r"\bBYD\s+Sealion\s+7\b", heading.get_text(" ", strip=True), re.I):
        return []

    host = urlsplit(url).hostname
    market = "Denmark" if host in {"bydauto.dk", "www.bydauto.dk"} else "Norway"
    candidates = []
    for heading in (page.find("main") or page).find_all(["h2", "h3", "h4", "p"]):
        title = heading.get_text(" ", strip=True)
        match = OTA_HEADING.fullmatch(title)
        if not match:
            continue
        note = f"BYD {market} lists this OTA release for {match[2]}. Rollout varies by market and vehicle."
        for sibling in heading.find_next_siblings(limit=3):
            text = sibling.get_text(" ", strip=True)
            if OTA_HEADING.fullmatch(text):
                break
            build = BUILD_LINE.fullmatch(text)
            if build:
                note += f" Multimedia build: {build[1]}."
                break
        candidates.append(make_release_candidate(
            version=match[1],
            note=note,
            evidence_type="byd_ota_release_heading",
            evidence_text=title,
            source_url=url,
            confidence=0.95,
        ))
    return resolve_release_candidates(candidates, source)
