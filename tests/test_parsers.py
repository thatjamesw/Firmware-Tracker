import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_firmware_details as ffd  # noqa: E402
from sources import apple as apple_source  # noqa: E402
from sources import atomos as atomos_source  # noqa: E402
from sources import bambu as bambu_source  # noqa: E402


class ParserTests(unittest.TestCase):
    def test_bambu_wiki_parser_extracts_latest(self) -> None:
        html = (FIXTURES_DIR / "bambu_wiki.html").read_text(encoding="utf-8")
        original_fetch = bambu_source.fetch_bytes
        try:
            bambu_source.fetch_bytes = lambda _url, timeout: html.encode("utf-8")
            releases = ffd.sync_bambu_wiki(
                {"url": "https://wiki.bambulab.com/en/p1/manual/p1p-firmware-release-history", "series": "P1"},
                timeout=5,
            )
        finally:
            bambu_source.fetch_bytes = original_fetch

        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["version"], "01.09.01.00")
        self.assertEqual(releases[0]["released_time"], "2026-01-14")

    def test_atomos_parser_extracts_current(self) -> None:
        html = (FIXTURES_DIR / "atomos_ninjav.html").read_text(encoding="utf-8")
        original_fetch = atomos_source.fetch_bytes
        try:
            atomos_source.fetch_bytes = lambda _url, timeout: html.encode("utf-8")
            releases = ffd.sync_atomos_support(
                {"url": "https://www.atomos.com/product-support/", "article_id": "NinjaVArticle"},
                timeout=5,
            )
        finally:
            atomos_source.fetch_bytes = original_fetch

        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["version"], "11.18.00")
        self.assertEqual(releases[0]["released_time"], "2025-11-01")

    def test_apple_ios_parser_extracts_latest_and_release_date(self) -> None:
        html = (FIXTURES_DIR / "apple_100100.html").read_text(encoding="utf-8")
        original_fetch = apple_source.fetch_bytes
        try:
            apple_source.fetch_bytes = lambda _url, timeout: html.encode("utf-8")
            releases = ffd.sync_apple_support(
                {"url": "https://support.apple.com/en-us/100100", "kind": "ios"},
                timeout=5,
            )
        finally:
            apple_source.fetch_bytes = original_fetch

        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["version"], "26.3.1")
        self.assertEqual(releases[0]["released_time"], "2026-03-04")

    def test_apple_airpods_parser_extracts_latest_and_published_date(self) -> None:
        html = (FIXTURES_DIR / "apple_106340.html").read_text(encoding="utf-8")
        original_fetch = apple_source.fetch_bytes
        try:
            apple_source.fetch_bytes = lambda _url, timeout: html.encode("utf-8")
            releases = ffd.sync_apple_support(
                {"url": "https://support.apple.com/106340", "kind": "airpods", "model": "AirPods Pro 3"},
                timeout=5,
            )
        finally:
            apple_source.fetch_bytes = original_fetch

        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["version"], "8B34")
        self.assertEqual(releases[0]["released_time"], "2026-01-13")

    def test_devices_json_conforms_to_schema(self) -> None:
        payload = json.loads((ROOT / "data" / "devices.json").read_text(encoding="utf-8"))
        # Raises on validation failure.
        ffd.validate_payload_schema(payload)


if __name__ == "__main__":
    unittest.main()
