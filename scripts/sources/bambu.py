from __future__ import annotations

import re
from typing import Any

from .common import fetch_bytes, html_to_text, make_release_candidate, parse_html, resolve_release_candidates


def sync_bambu_wiki(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source.get("url")
    series = str(source.get("series") or "P1").upper()
    if not isinstance(url, str) or not url:
        return []

    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")

    candidates: list[dict[str, Any]] = []
    pattern = re.compile(rf"\b{re.escape(series)}\s+series\s+Version\s+([0-9.]+)\s*\((\d{{8}})\)", re.I)
    for heading in parse_html(html).find_all(["h2", "h3"]):
        match = pattern.search(html_to_text(str(heading)))
        if not match:
            continue
        version, yyyymmdd = match.groups()
        date_iso = f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
        title = match.group(0)
        candidates.append(
            make_release_candidate(
                version=version.strip(),
                released_time=date_iso,
                note=f"Official Bambu Lab Wiki {series} release history. Entry: {title}.",
                evidence_type="bambu_wiki_heading",
                evidence_text=title,
                source_url=url,
                confidence=0.9,
                rank=88,
            )
        )

    return resolve_release_candidates(candidates, source)
