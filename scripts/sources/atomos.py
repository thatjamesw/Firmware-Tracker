from __future__ import annotations

import re
from typing import Any

from urllib.parse import urljoin
from urllib.error import HTTPError

from .common import fetch_bytes, make_release_candidate, resolve_release_candidates, parse_html


def sync_atomos_support(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source.get("url")
    article_id = source.get("article_id", "NinjaVArticle")
    if not isinstance(url, str) or not url:
        return []
    if not isinstance(article_id, str) or not article_id:
        return []

    try:
        html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code == 403:
            raise RuntimeError(
                "Atomos blocked automated firmware checks (HTTP 403). "
                "Last known firmware is retained; check the official download page manually."
            ) from exc
        raise
    article = parse_html(html).find(id=article_id)
    if article is None:
        return []

    current_match = re.search(
        r"Current Firmware.*?AtomOS\s*([0-9][0-9A-Za-z.\-]+)",
        article.get_text(" ", strip=True),
        re.I | re.S,
    )
    version = current_match.group(1).strip() if current_match else ""
    if not version:
        return []

    release_notes_url = ""
    for link in article.find_all("a", href=True):
        if "release" in link.get_text(" ", strip=True).lower():
            release_notes_url = urljoin(url, str(link["href"]))
            break

    # The upload path only identifies a month; do not fabricate a release day.
    released_time = ""

    candidates = []
    note = f"Official Atomos {article_id} firmware listing."
    if release_notes_url:
        note += f" Release notes: {release_notes_url}"
    candidates.append(
        make_release_candidate(
            version=version,
            released_time=released_time,
            note=note,
            evidence_type="atomos_current_firmware",
            evidence_text=current_match.group(0) if current_match else f"AtomOS {version}",
            source_url=url,
            confidence=0.9 if released_time else 0.82,
            rank=88,
        )
    )

    release_link_match = re.search(r"AtomOS[_\s-]+([0-9][0-9A-Za-z.\-]+)", release_notes_url, re.I)
    if release_link_match:
        candidates.append(
            make_release_candidate(
                version=release_link_match.group(1),
                released_time=released_time,
                note=note,
                evidence_type="atomos_release_notes_url",
                evidence_text=release_notes_url,
                source_url=url,
                confidence=0.72,
                rank=64,
            )
        )

    releases = resolve_release_candidates(candidates, source)
    for release in releases:
        release["date_precision"] = "unknown"
    return releases
