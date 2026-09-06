from __future__ import annotations

import random
import re
import ssl
import threading
import time
from concurrent.futures import Future
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import Any

from bs4 import BeautifulSoup

USER_AGENT = "firmware-tracker-sync/1.0 (+https://github.com/)"
FETCH_RETRIES = 3
FETCH_RETRY_BACKOFF = 1.5


# A session lasts one scan. Futures coalesce concurrent requests, including failures.
_FETCH_LOCK = threading.Lock()
_FETCH_CACHE: dict[str, Future] = {}
_HOST_SLOTS: dict[str, threading.BoundedSemaphore] = {}
_FETCH_METRICS: dict[str, float] = {}
_LOCAL = threading.local()
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}


def configure_fetch(retries: int, retry_backoff: float) -> None:
    """Start a fresh scan; call before starting workers, never during a scan."""
    global FETCH_RETRIES, FETCH_RETRY_BACKOFF
    FETCH_RETRIES = max(0, int(retries))
    FETCH_RETRY_BACKOFF = max(0.1, float(retry_backoff))
    with _FETCH_LOCK:
        _FETCH_CACHE.clear()
        _HOST_SLOTS.clear()
        _FETCH_METRICS.clear()


def _metric(name: str, amount: float = 1) -> None:
    with _FETCH_LOCK:
        _FETCH_METRICS[name] = _FETCH_METRICS.get(name, 0) + amount


def fetch_metrics() -> dict[str, float]:
    with _FETCH_LOCK:
        return {**dict.fromkeys(("requests", "retries", "cache_hits", "bytes_downloaded", "network_seconds"), 0), **_FETCH_METRICS}


@contextmanager
def fetch_budget(seconds: float = 120):
    """Bound network waits/retries across all fallbacks for one device."""
    previous = getattr(_LOCAL, "deadline", None)
    _LOCAL.deadline = time.monotonic() + seconds
    _LOCAL.fetch_seconds = 0.0
    try:
        yield
    finally:
        _LOCAL.deadline = previous


def device_fetch_seconds() -> float:
    return getattr(_LOCAL, "fetch_seconds", 0.0)


def _remaining(timeout: float) -> float:
    deadline = getattr(_LOCAL, "deadline", None)
    remaining = timeout if deadline is None else min(timeout, deadline - time.monotonic())
    if remaining <= 0:
        raise TimeoutError("Device fetch budget exhausted")
    return remaining


def _retry_delay(attempt: int, retry_after: str = "") -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                return max(0.0, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return FETCH_RETRY_BACKOFF * (2**attempt) + random.uniform(0, FETCH_RETRY_BACKOFF)


def _download(url: str, timeout: int) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("Source URL must be HTTP(S)")
    host = parsed.hostname.lower()
    with _FETCH_LOCK:
        slots = _HOST_SLOTS.setdefault(host, threading.BoundedSemaphore(2))
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/pdf,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if host == "dji.com" or host.endswith(".dji.com"):
        headers["Cookie"] = "region=GB; lang=en"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(FETCH_RETRIES + 1):
        retry_after = ""
        if not slots.acquire(timeout=_remaining(timeout)):
            raise TimeoutError("Timed out waiting for vendor request slot")
        started = time.monotonic()
        try:
            _metric("requests")
            with urllib.request.urlopen(req, timeout=_remaining(timeout)) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
                _metric("bytes_downloaded", len(data))
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ValueError("Source response exceeds 32 MiB limit")
                _remaining(timeout)
                return data
        except urllib.error.HTTPError as exc:
            retry_after = str(exc.headers.get("Retry-After", "")) if exc.headers else ""
            exc.close()
            if exc.code not in RETRYABLE_HTTP or attempt >= FETCH_RETRIES:
                raise
        except (urllib.error.URLError, TimeoutError) as exc:
            if isinstance(getattr(exc, "reason", None), (ssl.SSLError, ValueError)) or attempt >= FETCH_RETRIES:
                raise
        finally:
            _metric("network_seconds", time.monotonic() - started)
            slots.release()
        delay = _retry_delay(attempt, retry_after)
        if delay >= _remaining(float("inf")):
            raise TimeoutError("Retry delay exceeds remaining device fetch budget")
        _metric("retries")
        time.sleep(delay)
    raise RuntimeError(f"Failed to fetch URL: {url}")


def fetch_bytes(url: str, timeout: int) -> bytes:
    # Fragments are browser-only and must not cause duplicate downloads.
    url = urllib.parse.urldefrag(url)[0]
    started = time.monotonic()
    with _FETCH_LOCK:
        future = _FETCH_CACHE.get(url)
        owner = future is None
        if owner:
            future = Future()
            _FETCH_CACHE[url] = future
    try:
        if not owner:
            _metric("cache_hits")
            return future.result(timeout=_remaining(timeout))
        try:
            data = _download(url, timeout)
        except Exception as exc:
            future.set_exception(exc)
            raise
        future.set_result(data)
        return data
    finally:
        _LOCAL.fetch_seconds = getattr(_LOCAL, "fetch_seconds", 0.0) + time.monotonic() - started


def parse_html(value: str) -> BeautifulSoup:
    return BeautifulSoup(value, "html.parser")


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def html_to_text(value: str) -> str:
    no_tags = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.I | re.S)
    no_tags = re.sub(r"<[^>]+>", " ", no_tags)
    return normalize_space(unescape(no_tags))


def extract_attr(tag_html: str, attr_name: str) -> str:
    pattern = rf"""\b{re.escape(attr_name)}\s*=\s*(["'])(.*?)\1"""
    match = re.search(pattern, tag_html, re.I | re.S)
    return unescape(match.group(2)).strip() if match else ""


def as_iso_date(date_text: str) -> str:
    clean = date_text.strip().replace(".", "-").replace("/", "-")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", clean)
    if not match:
        return ""
    year, month, day = match.groups()
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return ""


def parse_human_date_to_iso(date_text: str) -> str:
    clean = normalize_space(date_text).replace(",", "")
    for fmt in (
        "%d %b %Y",
        "%d %B %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%Y-%m-%d",
        "%Y.%m.%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(clean, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return as_iso_date(clean)


def version_sort_key(version: str) -> tuple:
    clean = str(version or "").strip().lstrip("Vv")
    if not clean:
        return ()
    parts = re.findall(r"\d+|[A-Za-z]+", clean)
    out = []
    for part in parts:
        if part.isdigit():
            out.append((1, int(part)))
        else:
            out.append((0, part.lower()))
    return tuple(out)


def compare_versions(left: str, right: str) -> int | None:
    left_key = version_sort_key(left)
    right_key = version_sort_key(right)
    if not left_key or not right_key:
        return None
    if left_key == right_key:
        return 0
    return 1 if left_key > right_key else -1


def make_release_candidate(
    *,
    version: str,
    released_time: str = "",
    note: str = "",
    evidence_type: str,
    evidence_text: str,
    source_url: str = "",
    confidence: float = 0.5,
    rank: int = 50,
) -> dict[str, Any]:
    return {
        "version": str(version or "").strip().lstrip("Vv"),
        "released_time": str(released_time or "").strip(),
        "release_note": {"en": str(note or "")},
        "arb": None,
        "active": True,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "rank": int(rank),
        "evidence": {
            "type": str(evidence_type or "unknown"),
            "text": normalize_space(str(evidence_text or ""))[:500],
            "source_url": str(source_url or ""),
        },
    }


def _candidate_contract_errors(candidate: dict[str, Any], source: dict[str, Any] | None) -> list[str]:
    source = source if isinstance(source, dict) else {}
    errors: list[str] = []
    version = str(candidate.get("version") or "")
    released_time = str(candidate.get("released_time") or "")
    pattern = source.get("expected_version_pattern") or default_expected_version_pattern(source)
    if isinstance(pattern, str) and pattern:
        try:
            if not re.fullmatch(pattern, version):
                errors.append("version_pattern")
        except re.error:
            errors.append("invalid_expected_version_pattern")
    requires_date = source.get("requires_date")
    if requires_date is None:
        requires_date = default_requires_date(source)
    if released_time:
        try:
            datetime.fromisoformat(released_time)
        except ValueError:
            errors.append("invalid_date")
    if bool(requires_date) and not released_time:
        errors.append("missing_date")
    return errors


def default_expected_version_pattern(source: dict[str, Any]) -> str:
    source_type = str(source.get("type") or "")
    if source_type == "apple_support":
        kind = str(source.get("kind") or "")
        if kind == "airpods":
            return r"[0-9A-Za-z][0-9A-Za-z.\-]*"
        return r"\d+(?:\.\d+)*(?:[A-Za-z0-9.\-]*)?"
    if source_type in {"dji_downloads", "atomos_support", "bambu_wiki", "godox_listing", "tplink_downloads"}:
        return r"\d+(?:\.\d+)+"
    if source_type == "sony_cscs":
        return r"\d+(?:\.\d+)*"
    return ""


def default_requires_date(source: dict[str, Any]) -> bool:
    if bool(source.get("allow_empty")):
        return False
    return str(source.get("type") or "") in {
        "dji_downloads",
        "sony_cscs",
        "godox_listing",
        "bambu_wiki",
        "tplink_downloads",
    }


def release_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    release = normalize_release(candidate)
    evidence = candidate.get("evidence")
    if isinstance(evidence, dict):
        release["evidence"] = {
            "type": str(evidence.get("type") or ""),
            "text": str(evidence.get("text") or ""),
            "source_url": str(evidence.get("source_url") or ""),
        }
    if "confidence" in candidate:
        release["confidence"] = max(0.0, min(1.0, float(candidate.get("confidence") or 0.0)))
    return release


def resolve_release_candidates(
    candidates: list[dict[str, Any]],
    source: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        version = str(candidate.get("version") or "").strip()
        if not version:
            continue
        errors = _candidate_contract_errors(candidate, source)
        if errors:
            continue
        valid.append(candidate)

    if not valid:
        return []

    valid.sort(
        key=lambda item: (
            float(item.get("confidence") or 0.0),
            int(item.get("rank") or 0),
            version_sort_key(str(item.get("version") or "")),
            str(item.get("released_time") or ""),
        ),
        reverse=True,
    )
    return [release_from_candidate(valid[0])]


def normalize_release(raw: dict[str, Any]) -> dict[str, Any]:
    note = raw.get("release_note")
    if not isinstance(note, dict):
        note = {"en": ""}
    elif "en" not in note:
        note["en"] = ""

    release = {
        "version": str(raw.get("version") or "").lstrip("Vv"),
        "released_time": str(raw.get("released_time") or ""),
        "release_note": {"en": str(note.get("en") or "")},
        "arb": raw.get("arb"),
        "active": bool(raw.get("active", False)),
    }
    if raw.get("date_precision") == "unknown":
        release["date_precision"] = "unknown"
    evidence = raw.get("evidence")
    if isinstance(evidence, dict):
        release["evidence"] = {
            "type": str(evidence.get("type") or ""),
            "text": str(evidence.get("text") or ""),
            "source_url": str(evidence.get("source_url") or ""),
        }
    if "confidence" in raw:
        release["confidence"] = max(0.0, min(1.0, float(raw.get("confidence") or 0.0)))
    return release


def normalize_releases(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_release(r) for r in releases if isinstance(r, dict)]

    def sort_key(item: dict[str, Any]) -> tuple[int, str]:
        date_text = str(item.get("released_time") or "")
        try:
            dt = datetime.fromisoformat(date_text)
            ts = int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            ts = -1
        return (ts, str(item.get("version") or ""))

    normalized.sort(key=sort_key, reverse=True)
    return normalized
