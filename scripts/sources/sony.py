from __future__ import annotations

import re
import urllib.parse
from html import unescape
from typing import Any

from .common import fetch_bytes


def sync_sony_cscs(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    mdl = source["mdl"]
    lang = source.get("lang", "en")
    area = source.get("area", "us")
    url = (
        "https://support.d-imaging.sony.co.jp/www/cscs/firm/"
        f"?mdl={urllib.parse.quote(mdl)}&lang={urllib.parse.quote(lang)}&area={urllib.parse.quote(area)}"
    )

    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")

    ver_match = re.search(r",ver:\s*'([^']+)'", html)
    if not ver_match:
        ver_match = re.search(rf"firm_{re.escape(mdl)}_([^']+)'\s*\+\s*'_download'", html)
    version = ver_match.group(1).strip() if ver_match else ""

    date_matches = re.findall(r"ver_date'>[^0-9]*(\d{4}-\d{2}-\d{2})", html)
    release_date = date_matches[0] if date_matches else ""

    dl_match = re.search(r'data-url="([^"]+)"', html)
    dl_url = unescape(dl_match.group(1)) if dl_match else ""

    if not version:
        return []

    note = "Official Sony firmware page"
    if dl_url:
        note += f". Download: {dl_url}"

    return [
        {
            "version": version,
            "released_time": release_date,
            "release_note": {"en": note},
            "arb": None,
            "active": True,
        }
    ]
