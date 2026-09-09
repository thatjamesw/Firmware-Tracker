#!/usr/bin/env python3
"""Validate device form inputs, preview one source, and prepare a repository change."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fetch_firmware_details import (
    DATA_FILE, list_tracked_devices, prepare_release_update, process_device, validate_payload_schema,
)
from sources import SOURCE_VENDOR
from sources.common import configure_fetch

VENDOR_DOMAINS = {
    "dji_downloads": ("dji.com",),
    "sony_cscs": ("sony.com", "sony.co.uk", "sony.co.jp"),
    "godox_listing": ("godox.com",),
    "apple_support": ("apple.com",),
    "atomos_support": ("atomos.com",),
    "bambu_wiki": ("bambulab.com",),
    "tplink_downloads": ("tp-link.com",),
}
DEFAULT_CATEGORIES = {
    "sony_cscs": "Cameras", "atomos_support": "Cameras", "godox_listing": "Lighting",
    "apple_support": "Apple", "bambu_wiki": "3D Printer", "tplink_downloads": "Networking",
}


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def clean(value, label: str, limit: int = 300) -> str:
    value = str(value or "").strip()
    if len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be a single line of at most {limit} characters")
    return value


def infer_type(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for kind, domains in VENDOR_DOMAINS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return kind
    raise ValueError("This vendor is not supported automatically. Choose static for a manual entry.")


def validate_source(source: dict) -> None:
    kind = source.get("type")
    if kind not in SOURCE_VENDOR:
        raise ValueError("Unknown source type")
    url = source.get("url") or source.get("page_url", "")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an official HTTPS support/download page without credentials")
    if kind != "static":
        host = parsed.hostname.lower()
        if not any(host == d or host.endswith("." + d) for d in VENDOR_DOMAINS[kind]):
            raise ValueError(f"Use an official {SOURCE_VENDOR[kind]} domain for this source")
    fields = {
        "sony_cscs": ("mdl",), "godox_listing": ("title_contains",),
        "apple_support": ("kind",),
        "bambu_wiki": ("series",), "tplink_downloads": ("model", "hardware_version"),
    }
    for field in fields.get(kind, ()):
        if not source.get(field):
            raise ValueError(f"{kind} needs {field}; fill in the model or variant field")
    if kind == "atomos_support" and not (source.get("model") or source.get("article_id")):
        raise ValueError("atomos_support needs model; use the exact product heading, for example Ninja V")
    if kind == "apple_support":
        if source["kind"] not in {"ios", "macos", "watchos", "airpods"}:
            raise ValueError("Apple variant must be ios, macos, watchos, or airpods")
        if source["kind"] == "airpods" and not source.get("model"):
            raise ValueError("AirPods needs the exact model name from Apple's firmware matrix")


def build_source(form: dict, name: str, existing: dict | None = None) -> dict:
    existing = existing or {}
    url = form.get("source_url") or existing.get("url") or existing.get("page_url", "")
    kind = form.get("source_type", "auto")
    if kind in {"", "auto"}:
        kind = existing.get("type") or infer_type(url)
    source = copy.deepcopy(existing) if kind == existing.get("type") else {"type": kind}
    source["type"] = kind
    if form.get("source_url") or not existing:
        source["page_url"] = url
        if kind != "static":
            source["url"] = url
        # A new URL replaces the old feed, including its old fallback routes.
        source.pop("fallback_sources", None)
        source.pop("fallback_source", None)
    model, variant = form.get("model", ""), form.get("variant", "")
    if kind == "dji_downloads":
        source["model"] = model or source.get("model") or re.sub(r"^DJI\s+", "", name, flags=re.I)
    elif kind == "sony_cscs":
        query_model = parse_qs(urlparse(url).query).get("mdl", [""])[0]
        source["mdl"] = model or source.get("mdl") or query_model
        source.setdefault("lang", "en")
        source.setdefault("area", "us")
    elif kind == "godox_listing":
        source["title_contains"] = model or source.get("title_contains", "")
    elif kind == "apple_support":
        source["kind"] = variant.lower() or source.get("kind") or (name.lower() if name.lower() in {"ios", "macos", "watchos"} else "airpods")
        if source["kind"] == "airpods":
            source["model"] = model or source.get("model") or name
    elif kind == "atomos_support":
        product_model = model or source.get("model")
        if product_model:
            source["model"] = product_model
        elif not variant and not source.get("article_id"):
            source["model"] = re.sub(r"^Atomos\s+", "", name, flags=re.I)
        if variant:
            source["article_id"] = variant
    elif kind == "bambu_wiki":
        source["series"] = variant.upper() or source.get("series", "")
    elif kind == "tplink_downloads":
        source["model"] = model or source.get("model", "")
        source["hardware_version"] = variant.upper() or source.get("hardware_version", "")
    elif kind == "static":
        release = source.setdefault("release", {"version": "", "released_time": "", "release_note": {"en": ""}, "active": True, "arb": None})
        if form.get("manual_version"):
            release["version"] = form["manual_version"]
        if form.get("manual_note"):
            release["release_note"] = {"en": form["manual_note"]}
        if not release["version"]:
            raise ValueError("Static entries need a manual version or status, e.g. App-managed")
    empty_policy = form.get("empty_policy", "keep")
    if empty_policy not in {"keep", "allow", "reject", ""}:
        raise ValueError("Unknown empty-result policy")
    if empty_policy in {"allow", "reject"}:
        source["allow_empty"] = empty_policy == "allow"
    validate_source(source)
    return source


def update_health(payload: dict, device_id: str, result: dict | None) -> None:
    """Refresh only this device; do not count another scan for untouched devices."""
    status = payload["sources"].get("sync_status")
    if not status:
        return
    health = status.setdefault("device_health", {})
    health.pop(device_id, None)
    for key in ("issues", "transient_issues"):
        status[key] = [i for i in status.get(key, []) if i.get("device_id") != device_id]
    status["issue_streaks"] = {k: v for k, v in status.get("issue_streaks", {}).items() if not k.endswith(":" + device_id)}
    if result:
        health[device_id] = {
            "vendor": result["vendor"], "status": result["status"],
            "last_success_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "consecutive_failures": 0, "last_error_type": "", "last_error_reason": "",
        }
    counts = dict.fromkeys(status.get("health_counts", {}), 0)
    for device in health.values():
        counts[device["status"]] = counts.get(device["status"], 0) + 1
    status["health_counts"] = counts
    status["max_issue_streak_days"] = max(status["issue_streaks"].values(), default=0)
    for vendor in list(status.get("vendor_health", {})):
        members = [d for d in health.values() if d.get("vendor") == vendor]
        if not members:
            del status["vendor_health"][vendor]
            continue
        entry = status["vendor_health"][vendor]
        entry["issues"] = [i for i in status["issues"] if i.get("vendor") == vendor]
        entry["ok_count"] = sum(d["status"] in {"ok", "ok_empty"} for d in members)
        entry["transient_count"] = sum(d["status"] == "transient_error" for d in members)
        entry["status"] = "issue" if entry["issues"] else ("transient_issue" if entry["transient_count"] else "ok")
        if entry["status"] == "ok":
            entry["consecutive_failures"] = 0
            entry["last_error_type"] = ""


def apply_change(payload: dict, form: dict, checker=process_device) -> tuple[dict, dict]:
    form = {k: clean(v, k, 2000 if k == "manual_note" else 300) for k, v in form.items()}
    updated = copy.deepcopy(payload)
    tracked = list_tracked_devices(updated)
    action = form.get("action", "add")
    if action not in {"add", "update", "remove"}:
        raise ValueError("Action must be add, update, or remove")
    name = form.get("name", "")
    device_id = form.get("device_id") or (slug(name) if action == "add" else "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", device_id):
        raise ValueError("Supply a device ID (letters, digits, underscores, hyphens); adding can generate it from the name")
    if action == "add" and (device_id in tracked or device_id in updated["sources"]["device_sources"] or device_id in updated["firmware_index"]):
        raise ValueError(f"Device ID {device_id} already exists; use update")
    if action != "add" and device_id not in tracked:
        raise ValueError(f"Unknown device ID: {device_id}")
    name = name or tracked.get(device_id, "")
    if not name:
        raise ValueError("A device name is required")
    old_category = next((key for key, c in updated["categories"].items() if device_id in c["devices"]), None)
    if action == "remove":
        del updated["categories"][old_category]["devices"][device_id]
        updated["sources"]["device_sources"].pop(device_id, None)
        updated["firmware_index"].pop(device_id, None)
        update_health(updated, device_id, None)
        report = {"action": action, "device_id": device_id, "name": name, "status": "removed"}
    else:
        existing = copy.deepcopy(updated["sources"]["device_sources"].get(device_id))
        if existing and existing.get("type") == "dji_downloads":
            existing.setdefault("model", re.sub(r"^DJI\s+", "", tracked[device_id], flags=re.I))
        source = build_source(form, name, existing)
        category = form.get("category") or old_category or DEFAULT_CATEGORIES.get(source["type"], "Cameras")
        category_id = next((key for key, c in updated["categories"].items() if category.lower() in {key.lower(), c["title"].lower()}), slug(category))
        if not category_id:
            raise ValueError("Category must contain letters or numbers")
        result = checker(device_id, name, source, 20)
        if result["status"] not in {"ok", "ok_empty"}:
            raise ValueError(f"Source check failed ({result['status']}): {result['reason']}. No files changed.")
        current = updated["firmware_index"].get(device_id, {}).get("releases", [])
        accepted, reason, releases = prepare_release_update(current, result["releases"], result.get("used_source", source), result["status"])
        if not accepted:
            raise ValueError(f"Source check rejected: {reason}. No files changed.")
        if old_category:
            del updated["categories"][old_category]["devices"][device_id]
        updated["categories"].setdefault(category_id, {"title": category, "devices": {}})["devices"][device_id] = name
        updated["sources"]["device_sources"][device_id] = source
        updated["firmware_index"][device_id] = {"releases": releases}
        update_health(updated, device_id, result)
        report = {"action": action, "device_id": device_id, "name": name, "category": category_id, "source": source, "status": result["status"], "detected_releases": result["releases"]}
    validate_payload_schema(updated)
    return updated, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--form-json", type=Path, help="Read form inputs from JSON; otherwise use DEVICE_FORM_JSON")
    parser.add_argument("--data-file", type=Path, default=DATA_FILE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    form = json.loads(args.form_json.read_text() if args.form_json else os.environ.get("DEVICE_FORM_JSON", "{}"))
    original = args.data_file.read_text(encoding="utf-8")
    payload = json.loads(original)
    validate_payload_schema(payload)
    configure_fetch(2, 1.5)
    updated, report = apply_change(payload, form)
    rendered = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    print(rendered)
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write(f"device_id={report['device_id']}\naction={report['action']}\n")
    if not args.dry_run:
        if args.data_file.read_text(encoding="utf-8") != original:
            raise ValueError("Device data changed during the source check; retry against the latest file")
        temporary = args.data_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(updated, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        temporary.replace(args.data_file)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
