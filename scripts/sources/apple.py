from __future__ import annotations

import re
from typing import Any

from .common import fetch_bytes, parse_human_date_to_iso


def sync_apple_support(source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    kind = str(source.get("kind") or "").lower()
    url = source.get("url")
    if not isinstance(url, str) or not url:
        return []

    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")

    if kind in {"ios", "macos", "watchos"}:
        phrase_map = {
            "ios": r"The latest version of iOS and iPadOS is\s+([0-9][0-9A-Za-z.\-]*)",
            "macos": r"The latest version of macOS is\s+([0-9][0-9A-Za-z.\-]*)",
            "watchos": r"The latest version of watchOS is\s+([0-9][0-9A-Za-z.\-]*)",
        }
        row_map = {
            "ios": r"iOS\s+([0-9][0-9A-Za-z.\-]*)",
            "macos": r"macOS[^0-9<]*\s+([0-9][0-9A-Za-z.\-]*)",
            "watchos": r"watchOS\s+([0-9][0-9A-Za-z.\-]*)",
        }

        latest_match = re.search(phrase_map[kind], html, re.I)
        latest_version = latest_match.group(1).strip().rstrip(".") if latest_match else ""
        if not latest_version:
            return []

        latest_release_date = ""
        row_pattern = re.compile(
            rf"<tr[^>]*>.*?<p class=\"gb-paragraph\">(?:<a[^>]*>)?[^<]*{row_map[kind]}[^<]*?(?:</a>)?</p>.*?<p class=\"gb-paragraph\">([0-9]{{1,2}}\s+[A-Za-z]{{3,9}}\s+[0-9]{{4}})</p>",
            re.I | re.S,
        )
        for row_match in row_pattern.finditer(html):
            row_version = row_match.group(1).strip()
            row_date = parse_human_date_to_iso(row_match.group(2))
            if row_version == latest_version and row_date:
                latest_release_date = row_date
                break

        if not latest_release_date:
            published_match = re.search(
                r"Published Date:\s*</span>\s*&nbsp;\s*<time[^>]*>([^<]+)</time>",
                html,
                re.I | re.S,
            )
            if published_match:
                latest_release_date = parse_human_date_to_iso(published_match.group(1))

        return [
            {
                "version": latest_version,
                "released_time": latest_release_date,
                "release_note": {"en": f"Official Apple support latest {kind} version listing."},
                "arb": None,
                "active": True,
            }
        ]

    if kind == "airpods":
        model = str(source.get("model") or "").strip()
        if not model:
            return []

        model_match = re.search(rf"{re.escape(model)}\s*:\s*([0-9A-Za-z.]+)", html, re.I)
        version = model_match.group(1).strip() if model_match else ""
        if not version:
            return []

        published_match = re.search(
            r"Published Date:\s*</span>\s*&nbsp;\s*<time[^>]*>([^<]+)</time>",
            html,
            re.I | re.S,
        )
        release_date = parse_human_date_to_iso(published_match.group(1)) if published_match else ""

        return [
            {
                "version": version,
                "released_time": release_date,
                "release_note": {"en": f"Official Apple AirPods firmware matrix listing for {model}."},
                "arb": None,
                "active": True,
            }
        ]

    return []
