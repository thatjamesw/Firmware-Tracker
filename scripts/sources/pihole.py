from __future__ import annotations

import json
import re
from typing import Any

from .common import fetch_bytes, make_release_candidate, resolve_release_candidates

RELEASES_URL = re.compile(r"https://github\.com/pi-hole/(pi-hole|web|FTL)/releases/?", re.I)


def sync_pihole_releases(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    match = RELEASES_URL.fullmatch(source["url"])
    if not match:
        raise ValueError("Use the official GitHub releases page for Pi-hole Core, Web or FTL")

    repo = match[1]
    api_url = f"https://api.github.com/repos/pi-hole/{repo}/releases/latest"
    release = json.loads(fetch_bytes(api_url, timeout))
    if release["draft"] or release["prerelease"]:
        return []
    tag = release["tag_name"]
    return resolve_release_candidates([make_release_candidate(
        version=tag,
        released_time=release["published_at"].split("T", 1)[0],
        note="See the official GitHub release for the full changelog.",
        evidence_type="pihole_github_release",
        evidence_text=tag,
        source_url=api_url,
        confidence=0.99,
    )], source)
