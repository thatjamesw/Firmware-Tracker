from __future__ import annotations

from typing import Any


def sync_static(source: dict[str, Any], _timeout: int | None = None) -> list[dict[str, Any]]:
    release = source.get("release")
    if not isinstance(release, dict):
        return []
    return [release]
