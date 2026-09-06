from __future__ import annotations

import io
import re
import urllib.error
import urllib.parse
from typing import Any

from pypdf import PdfReader

from .common import (
    as_iso_date, fetch_bytes, make_release_candidate, normalize_releases,
    normalize_space, parse_html, resolve_release_candidates,
)


def parse_dji_release_note_items(downloads_html: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    soup = parse_html(downloads_html)
    for block in soup.select('.groups-download-item, [class*="document-item___"]'):
        title = block.select_one('.groups-item-name, [class*="document-name___"]')
        name = title.get_text(" ", strip=True) if title else block.get_text(" ", strip=True)
        if "release notes" not in name.lower():
            continue
        for link in block.select("a[href]"):
            href = str(link["href"]).strip()
            if urllib.parse.urlparse(href).path.lower().endswith(".pdf"):
                items.append({"name": normalize_space(name), "href": href})

    # A filename is useful fallback evidence when vendors rename layout classes.
    known = {item["href"] for item in items}
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        filename = urllib.parse.unquote(urllib.parse.urlparse(href).path.rsplit("/", 1)[-1])
        if href not in known and re.search(r"release[_ -]+notes.*\.pdf$", filename, re.I):
            items.append({"name": filename[:-4].replace("_", " "), "href": href})
            known.add(href)
    return items


def pick_dji_release_notes_pdf(items: list[dict[str, str]], device_name: str) -> str | None:
    urls = pick_dji_release_notes_pdfs(items, device_name)
    return urls[0] if urls else None


def pick_dji_release_notes_pdfs(items: list[dict[str, str]], device_name: str) -> list[str]:
    if not items:
        return []

    device_norm = normalize_space(device_name).lower()
    scored: list[tuple[int, str]] = []
    for item in items:
        name_norm = normalize_space(item["name"]).lower()
        score = 0
        if name_norm.startswith(f"dji {device_norm} - release notes"):
            score += 100
        elif name_norm.startswith(f"{device_norm} - release notes"):
            score += 90
        elif re.search(rf"(?<!\w){re.escape(device_norm)}(?!\w)", name_norm) and "release notes" in name_norm:
            score += 50

        if any(token in name_norm for token in ["remote controller", "goggles", "motion", "rc "]):
            score -= 40

        if score > 0:
            scored.append((score, item["href"]))

    if not scored:
        return []

    scored.sort(key=lambda pair: pair[0], reverse=True)
    ordered: list[str] = []
    seen = set()
    for _, href in scored:
        if href in seen:
            continue
        seen.add(href)
        ordered.append(href)
    return ordered


def parse_dji_release_pdf(pdf_bytes: bytes, device_name: str) -> list[dict[str, Any]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    text = text.replace("’", "'").replace("：", ":")

    date_matches = list(re.finditer(r"Date\s*:\s*(\d{4}[.-]\d{1,2}[.-]\d{1,2})", text))
    sections: list[tuple[str, str]] = []
    if date_matches:
        for idx, match in enumerate(date_matches):
            start = match.start()
            end = date_matches[idx + 1].start() if idx + 1 < len(date_matches) else len(text)
            sections.append((match.group(1), text[start:end]))
    else:
        sections.append(("", text))

    device_pattern = re.escape(device_name)
    version_token = r"(\d+(?:\.\d+){2,3})"
    version_patterns = [
        rf"{device_pattern}\s+Firmware\s*:\s*[Vv]?{version_token}",
        rf"Aircraft\s+Firmware\s*:\s*[Vv]?{version_token}",
        rf"(?m)^\s*Firmware(?:\s+Version)?\s*:\s*[Vv]?{version_token}",
    ]

    releases: list[dict[str, Any]] = []
    for raw_date, section in sections:
        version = ""
        for pattern in version_patterns:
            match = re.search(pattern, section, re.I)
            if match:
                version = match.group(1)
                break
        if not version:
            continue

        note = ""
        whats_new_match = re.search(r"What's New\s*(.*?)(?:\n\s*Notes\s*:|\Z)", section, re.I | re.S)
        if whats_new_match:
            note_block = whats_new_match.group(1)
            # Join wrapped lines inside each bullet instead of dropping continuations.
            bullets = re.split(r"(?m)(?=^\s*[•-]\s)", note_block)
            note = "\n".join(normalize_space(bullet) for bullet in bullets if normalize_space(bullet))

        releases.extend(
            resolve_release_candidates(
                [make_release_candidate(
                    version=version,
                    released_time=as_iso_date(raw_date),
                    note=note,
                    evidence_type="dji_release_notes_pdf",
                    evidence_text=section[:500],
                    source_url="",
                    confidence=0.9,
                    rank=88,
                )],
                {"type": "dji_downloads"},
            )
        )

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for rel in releases:
        deduped[(rel["version"], rel["released_time"])] = rel

    return normalize_releases(list(deduped.values()))


def sync_dji_downloads(device_name: str, source: dict[str, Any], timeout: int) -> list[dict[str, Any]]:
    debug = bool(source.get("_debug"))
    debug_prefix = str(source.get("_debug_prefix") or "[debug dji]")

    url = source["url"]
    if debug:
        print(f"{debug_prefix} dji page fetch url={url}")
    html = fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")
    items = parse_dji_release_note_items(html)
    if debug:
        print(f"{debug_prefix} dji release-note items={len(items)}")
    rn_pdfs = pick_dji_release_notes_pdfs(items, str(source.get("model") or device_name))
    if debug:
        print(f"{debug_prefix} dji candidate pdfs={len(rn_pdfs)}")
        for idx, rn_pdf in enumerate(rn_pdfs[:5], start=1):
            print(f"{debug_prefix} dji pdf[{idx}]={rn_pdf}")
    if not rn_pdfs:
        return []
    last_exc: Exception | None = None
    last_non_404_exc: Exception | None = None
    saw_fetch_error = False
    all_fetch_errors_were_404 = True
    for rn_pdf in rn_pdfs:
        try:
            if debug:
                print(f"{debug_prefix} dji fetching pdf={rn_pdf}")
            rn_pdf = urllib.parse.urljoin(url, rn_pdf)
            pdf_bytes = fetch_bytes(rn_pdf, timeout=timeout)
            releases = parse_dji_release_pdf(pdf_bytes, str(source.get("model") or device_name))
            for release in releases:
                release.setdefault("evidence", {})["source_url"] = rn_pdf
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if debug:
                print(f"{debug_prefix} dji pdf fetch failed: {exc}")
            saw_fetch_error = True
            if not (isinstance(exc, urllib.error.HTTPError) and exc.code == 404):
                all_fetch_errors_were_404 = False
                last_non_404_exc = exc
            continue
        if debug:
            print(f"{debug_prefix} dji pdf parsed releases={len(releases)}")
        if releases:
            return releases
    # Some DJI pages occasionally keep stale release-note links; treat 404-only PDF failures as no entries.
    if saw_fetch_error and all_fetch_errors_were_404:
        return []
    if last_non_404_exc:
        raise last_non_404_exc
    if last_exc:
        raise last_exc
    return []
