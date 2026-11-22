from __future__ import annotations

import re
from typing import Any

from .common import fetch_bytes, make_release_candidate, parse_html, resolve_release_candidates

VERSION_HEADING = re.compile(r"Version\s*:\s*(\d{2}\.\d{2}-\d{2}\.\d{2}\.\d{2})", re.I)


def sync_playstation_support(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source["url"]
    page = parse_html(fetch_bytes(url, timeout).decode("utf-8", errors="replace"))
    candidates = []
    for heading in page.find_all(["h2", "h3", "h4"]):
        title = heading.get_text(" ", strip=True)
        match = VERSION_HEADING.fullmatch(title)
        if not match:
            continue
        next_block = heading.find_next_sibling()
        notes = []
        if next_block and next_block.name in {"ul", "ol"}:
            notes = [item.get_text(" ", strip=True) for item in next_block.find_all("li", recursive=False)]
        candidates.append(make_release_candidate(
            version=match[1],
            note="\n".join(f"• {note}" for note in notes),
            evidence_type="playstation_version_heading",
            evidence_text=title,
            source_url=url,
            confidence=0.95,
        ))
    return resolve_release_candidates(candidates, source)
