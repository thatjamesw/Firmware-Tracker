from __future__ import annotations

import re
from typing import Any

from .common import (
    extract_attr,
    fetch_bytes,
    html_to_text,
    make_release_candidate,
    normalize_space,
    parse_human_date_to_iso,
    resolve_release_candidates,
)


def sync_godox_listing(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source["url"]
    title_contains = source.get("title_contains", "").lower()

    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")

    blocks = re.findall(
        r'<div[^>]+class="[^"]*\bitem\b[^"]*"[^>]*>(.*?)(?=<div[^>]+class="[^"]*\bitem\b|</body>|\Z)',
        html,
        re.I | re.S,
    )
    candidates: list[dict[str, Any]] = []

    for block_html in blocks:
        tit_match = re.search(r'<div[^>]+class="[^"]*\btit\b[^"]*"[^>]*>(.*?)</div>', block_html, re.I | re.S)
        text_match = re.search(r'<div[^>]+class="[^"]*\btext\b[^"]*"[^>]*>(.*)', block_html, re.I | re.S)
        tit_html = tit_match.group(1) if tit_match else block_html
        text_html = text_match.group(1) if text_match else block_html
        title = html_to_text(tit_html)
        version_match = re.search(r"<span[^>]*>\s*V?\s*([0-9][0-9A-Za-z.\-]+)\s*</span>", tit_html, re.I)
        if not version_match:
            version_match = re.search(r"\bV(?:ersion)?\s*([0-9][0-9A-Za-z.\-]+)", title, re.I)
        if not version_match:
            continue
        version = version_match.group(1)

        href = ""
        for tag_html in re.findall(r"<a\b[^>]+>", block_html, re.I | re.S):
            class_name = extract_attr(tag_html, "class").lower()
            candidate = extract_attr(tag_html, "href")
            if candidate and ("download" in class_name or re.search(r"\.(?:zip|rar|bin|exe)(?:\?|$)", candidate, re.I)):
                href = candidate
                break
        if href and not href.startswith("http"):
            href = f"https://www.godox.com{href}"

        text = html_to_text(text_html)
        date_match = re.search(r"Release Date\s*([0-9]{4}[-./][0-9]{2}[-./][0-9]{2})", text, re.I)
        release_date = parse_human_date_to_iso(date_match.group(1)) if date_match else ""

        upd_match = re.search(r'Updated Contents</div>\s*<div[^>]+class="[^"]*\bc\b[^"]*"[^>]*>(.*?)</div>', text_html, re.I | re.S)
        note = ""
        if upd_match:
            note = html_to_text(upd_match.group(1))

        if title_contains and title_contains not in title.lower():
            continue

        final_note = note if note else "Official Godox firmware listing"
        if href:
            final_note += f". Download: {href}"
        candidates.append(
            make_release_candidate(
                version=version,
                released_time=release_date,
                note=final_note,
                evidence_type="godox_listing_item",
                evidence_text=title,
                source_url=url,
                confidence=0.88 if release_date else 0.75,
                rank=84,
            )
        )

    return resolve_release_candidates(candidates, source)
