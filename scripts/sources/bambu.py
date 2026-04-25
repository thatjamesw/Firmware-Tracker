from __future__ import annotations

import re
from typing import Any

from .common import fetch_bytes, html_to_text, make_release_candidate, resolve_release_candidates


def sync_bambu_wiki(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source.get("url")
    series = str(source.get("series") or "P1").upper()
    if not isinstance(url, str) or not url:
        return []

    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")

    matches = re.findall(
        rf"<h[23][^>]*>\s*.*?({re.escape(series)}\s*series\s*(?:Version|version)\s*([0-9.]+)\s*\((\d{{8}})\)).*?</h[23]>",
        html,
        re.I | re.S,
    )
    if not matches:
        return []

    candidates: list[dict[str, Any]] = []
    for full_title, version, yyyymmdd in matches:
        date_iso = f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
        title = html_to_text(full_title)
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
