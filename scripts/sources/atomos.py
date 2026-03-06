from __future__ import annotations

import re
from html import unescape
from typing import Any

from .common import fetch_bytes


def date_from_release_notes_url(url: str) -> str:
    path_match = re.search(r"/(\d{4})/(\d{2})/", url)
    if path_match:
        return f"{path_match.group(1)}-{path_match.group(2)}-01"
    return ""


def sync_atomos_support(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source.get("url")
    article_id = source.get("article_id", "NinjaVArticle")
    if not isinstance(url, str) or not url:
        return []
    if not isinstance(article_id, str) or not article_id:
        return []

    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")
    article_match = re.search(
        rf'<div class="support-product-article\s*" id="{re.escape(article_id)}">(.*?)</div>\s*</div>\s*</div>\s*</div>',
        html,
        re.I | re.S,
    )
    if not article_match:
        start_match = re.search(rf'<div class="support-product-article\s*" id="{re.escape(article_id)}">', html, re.I)
        if not start_match:
            return []
        rest = html[start_match.start() :]
        end_match = re.search(r'<div class="support-product-article\s*" id="[^"]+">', rest[1:], re.I)
        article_html = rest if not end_match else rest[: end_match.start() + 1]
    else:
        article_html = article_match.group(1)

    current_match = re.search(
        r'Current Firmware</h2>.*?<span class="text-lg">\s*AtomOS\s*([0-9][0-9.]+)\s*</span>',
        article_html,
        re.I | re.S,
    )
    version = current_match.group(1).strip() if current_match else ""
    if not version:
        return []

    release_notes_match = re.search(
        r'<a href="([^"]+)"[^>]*>\s*<span[^>]*>\s*Download Release\s*Notes\s*</span>',
        article_html,
        re.I | re.S,
    )
    release_notes_url = unescape(release_notes_match.group(1)).strip() if release_notes_match else ""

    released_time = date_from_release_notes_url(release_notes_url) if release_notes_url else ""

    note = f"Official Atomos {article_id} firmware listing."
    if release_notes_url:
        note += f" Release notes: {release_notes_url}"

    return [
        {
            "version": version,
            "released_time": released_time,
            "release_note": {"en": note},
            "arb": None,
            "active": True,
        }
    ]
