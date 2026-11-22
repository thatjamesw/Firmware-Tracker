from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

from .common import fetch_bytes, make_release_candidate, resolve_release_candidates

RELEASE_FEED_URL = re.compile(
    r"https://sourceforge\.net/projects/asuswrt-merlin/rss\?path=(?:/|%2F)([A-Z0-9_-]+)(?:/|%2F)Release",
    re.I,
)


def sync_merlin_releases(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    url = source["url"]
    feed = RELEASE_FEED_URL.fullmatch(url)
    if not feed:
        raise ValueError("Use the Asuswrt-Merlin RSS feed for the exact model's Release folder")

    model = feed[1].upper()
    package = re.compile(rf"/{model}/Release/{model}_((?:\d+_)?\d+\.\d+_\d+)\.zip")
    root = ElementTree.fromstring(fetch_bytes(url, timeout))
    candidates = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title", "").strip()
        match = package.fullmatch(title)
        if not match:
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", "")).date().isoformat()
        except ValueError:
            continue
        candidates.append(make_release_candidate(
            version=match[1],
            released_time=published,
            note=f"Stable Asuswrt-Merlin release for {model}.",
            evidence_type="merlin_stable_rss",
            evidence_text=title,
            source_url=url,
            confidence=0.99,
        ))
    return resolve_release_candidates(candidates, source)
