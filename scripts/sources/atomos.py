from __future__ import annotations

import re
from typing import Any

from .common import extract_attr, fetch_bytes, html_to_text, make_release_candidate, resolve_release_candidates


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
        r"Current Firmware.*?AtomOS\s*([0-9][0-9A-Za-z.\-]+)",
        html_to_text(article_html),
        re.I | re.S,
    )
    version = current_match.group(1).strip() if current_match else ""
    if not version:
        return []

    release_notes_url = ""
    for tag_html in re.findall(r"<a\b[^>]*>.*?</a>", article_html, re.I | re.S):
        if "release" not in html_to_text(tag_html).lower():
            continue
        href = extract_attr(tag_html, "href")
        if href:
            release_notes_url = href
            break

    released_time = date_from_release_notes_url(release_notes_url) if release_notes_url else ""

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

    return resolve_release_candidates(candidates, source)
