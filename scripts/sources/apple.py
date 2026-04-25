from __future__ import annotations

import re
from typing import Any

from .common import fetch_bytes, html_to_text, make_release_candidate, parse_human_date_to_iso, resolve_release_candidates


ROW_RE = re.compile(r"<tr[^>]*>.*?</tr>", re.I | re.S)
DATE_RE = re.compile(r"\b([0-9]{1,2}\s+[A-Za-z]{3,9}\s+[0-9]{4})\b")


def extract_row_release_date(html: str, kind: str, latest_version: str) -> str:
    latest_escaped = re.escape(latest_version)
    token_patterns = {
        "ios": re.compile(rf"\biOS\s+{latest_escaped}(?![0-9A-Za-z.\-])", re.I),
        "macos": re.compile(rf"\bmacOS(?:\s+\w+)?\s+{latest_escaped}(?![0-9A-Za-z.\-])", re.I),
        "watchos": re.compile(rf"\bwatchOS\s+{latest_escaped}(?![0-9A-Za-z.\-])", re.I),
    }
    token_pattern = token_patterns.get(kind)
    if token_pattern is None:
        return ""

    searchable_blocks = ROW_RE.findall(html)
    if not searchable_blocks:
        searchable_blocks = re.findall(r"<li[^>]*>.*?</li>|<p[^>]*>.*?</p>", html, re.I | re.S)

    for block_html in searchable_blocks:
        row_text = html_to_text(block_html)
        if not token_pattern.search(row_text):
            continue
        date_match = DATE_RE.search(row_text)
        if not date_match:
            continue
        date_iso = parse_human_date_to_iso(date_match.group(1))
        if date_iso:
            return date_iso
    return ""


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
        latest_match = re.search(phrase_map[kind], html, re.I)
        latest_version = latest_match.group(1).strip().rstrip(".") if latest_match else ""
        if not latest_version:
            return []

        latest_release_date = extract_row_release_date(html, kind, latest_version)

        # Published date is the article date and can change without a new OS release.
        if not latest_release_date and bool(source.get("fallback_to_published_date")):
            latest_release_date = extract_published_date(html)

        candidates = [
            make_release_candidate(
                version=latest_version,
                released_time=latest_release_date,
                note=f"Official Apple support latest {kind} version listing.",
                evidence_type="apple_latest_phrase",
                evidence_text=latest_match.group(0) if latest_match else f"latest {kind} {latest_version}",
                source_url=url,
                confidence=0.9 if latest_release_date else 0.82,
                rank=90,
            )
        ]
        return resolve_release_candidates(candidates, source)

    if kind == "airpods":
        model = str(source.get("model") or "").strip()
        if not model:
            return []

        model_match = re.search(rf"{re.escape(model)}\s*:\s*([0-9A-Za-z.\-]+)", html_to_text(html), re.I)
        version = model_match.group(1).strip() if model_match else ""
        if not version:
            return []

        release_date = extract_published_date(html)

        return resolve_release_candidates(
            [
                make_release_candidate(
                    version=version,
                    released_time=release_date,
                    note=f"Official Apple AirPods firmware matrix listing for {model}.",
                    evidence_type="apple_airpods_matrix",
                    evidence_text=model_match.group(0) if model_match else f"{model}: {version}",
                    source_url=url,
                    confidence=0.88 if release_date else 0.78,
                    rank=86,
                )
            ],
            source,
        )

    return []


def extract_published_date(html: str) -> str:
    published_patterns = [
        r"Published Date:\s*</span>\s*(?:&nbsp;|\s)*<time[^>]*>([^<]+)</time>",
        r"Published Date:\s*([^<\n]+)",
        r"<time[^>]+datetime=[\"']([^\"']+)[\"']",
    ]
    for pattern in published_patterns:
        match = re.search(pattern, html, re.I | re.S)
        if not match:
            continue
        parsed = parse_human_date_to_iso(html_to_text(match.group(1)))
        if parsed:
            return parsed
    return ""
