from __future__ import annotations

import re
import urllib.parse
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


def sync_sony_cscs(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    mdl = source["mdl"]
    lang = source.get("lang", "en")
    area = source.get("area", "us")
    url = (
        "https://support.d-imaging.sony.co.jp/www/cscs/firm/"
        f"?mdl={urllib.parse.quote(mdl)}&lang={urllib.parse.quote(lang)}&area={urllib.parse.quote(area)}"
    )

    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")

    candidates: list[dict[str, Any]] = []
    ver_match = re.search(r",\s*ver\s*:\s*['\"]([^'\"]+)['\"]", html, re.I)
    if not ver_match:
        ver_match = re.search(rf"firm_{re.escape(mdl)}_([^'\"/]+)['\"]?\s*\+\s*['\"]?_download", html, re.I)
    if not ver_match:
        page_text = html_to_text(html)
        ver_match = re.search(r"(?:System Software|Firmware)\s*(?:Version|Ver\.?)\s*([0-9][0-9A-Za-z.\-]*)", page_text, re.I)
    version = ver_match.group(1).strip() if ver_match else ""

    date_matches = re.findall(r"ver_date['\"][^>]*>[^0-9]*(\d{4}[-./]\d{2}[-./]\d{2})", html, re.I)
    if not date_matches:
        date_matches = re.findall(r"\b(\d{4}[-./]\d{2}[-./]\d{2})\b", html_to_text(html))
    release_date = parse_human_date_to_iso(date_matches[0]) if date_matches else ""

    dl_match = re.search(r"<[^>]+\bdata-url\s*=\s*['\"][^>]+>", html, re.I | re.S)
    dl_url = extract_attr(dl_match.group(0), "data-url") if dl_match else ""
    if not dl_url:
        exe_links = re.findall(r"<a\b[^>]+>", html, re.I | re.S)
        for tag_html in exe_links:
            href = extract_attr(tag_html, "href")
            if href and re.search(r"\.(?:exe|dat|dmg|zip)(?:\?|$)", href, re.I):
                dl_url = href
                break

    note = normalize_space("Official Sony firmware page")
    if dl_url:
        note += f". Download: {dl_url}"

    if version:
        candidates.append(
            make_release_candidate(
                version=version,
                released_time=release_date,
                note=note,
                evidence_type="sony_cscs_version",
                evidence_text=ver_match.group(0) if ver_match else f"{mdl} {version}",
                source_url=url,
                confidence=0.9 if release_date else 0.82,
                rank=88,
            )
        )

    for href in re.findall(r"https?://[^\"'\s<>]+", html):
        file_match = re.search(rf"{re.escape(mdl)}V?([0-9][0-9A-Za-z.\-]*)", href, re.I)
        if file_match:
            candidates.append(
                make_release_candidate(
                    version=file_match.group(1),
                    released_time=release_date,
                    note=note,
                    evidence_type="sony_download_filename",
                    evidence_text=href,
                    source_url=url,
                    confidence=0.68,
                    rank=55,
                )
            )

    return resolve_release_candidates(candidates, source)
