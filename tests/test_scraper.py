import io
import sys
import threading
import time
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sources import common, dji, apple, atomos
from fetch_firmware_details import prepare_release_update

FIXTURES = Path(__file__).parent / 'fixtures'


class FetchTests(unittest.TestCase):
    def setUp(self):
        common.configure_fetch(2, 0.1)

    def tearDown(self):
        common.configure_fetch(3, 1.5)

    def test_concurrent_requests_share_one_download(self):
        entered, release = threading.Event(), threading.Event()
        def download(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return b'page'
        with patch.object(common, '_download', side_effect=download) as request:
            with ThreadPoolExecutor(3) as pool:
                first = pool.submit(common.fetch_bytes, 'https://example.com/shared', 3)
                self.assertTrue(entered.wait(2))
                others = [pool.submit(common.fetch_bytes, 'https://example.com/shared#section', 3) for _ in range(2)]
                release.set()
                self.assertEqual([f.result() for f in [first, *others]], [b'page'] * 3)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(common.fetch_metrics()['cache_hits'], 2)

    def test_shared_download_wait_respects_timeout_and_device_budget(self):
        for timeout, budget in [(0.03, 5), (5, 0.03)]:
            with self.subTest(timeout=timeout, budget=budget):
                common.configure_fetch(2, 0.1)
                entered, release = threading.Event(), threading.Event()

                def download(*args):
                    entered.set()
                    release.wait(2)
                    return b'page'

                with patch.object(common, '_download', side_effect=download) as request:
                    with ThreadPoolExecutor(1) as pool:
                        owner = pool.submit(common.fetch_bytes, 'https://example.com/shared', 5)
                        try:
                            self.assertTrue(entered.wait(2))
                            with common.fetch_budget(budget), self.assertRaises(TimeoutError):
                                common.fetch_bytes('https://example.com/shared', timeout)
                            self.assertFalse(owner.done())
                        finally:
                            release.set()
                        self.assertEqual(owner.result(timeout=2), b'page')
                    # A waiter's timeout must not cancel or poison the shared result.
                    self.assertEqual(common.fetch_bytes('https://example.com/shared', 5), b'page')
                    self.assertEqual(request.call_count, 1)

    def test_permanent_http_errors_are_not_retried_and_failures_are_shared(self):
        for code in (400, 401, 403, 404, 410):
            with self.subTest(code=code):
                common.configure_fetch(2, 0.1)
                error = urllib.error.HTTPError('https://example.com', code, 'error', {}, io.BytesIO())
                with patch.object(common.urllib.request, 'urlopen', side_effect=error) as request, patch.object(common.time, 'sleep') as sleep:
                    for _ in range(2):
                        with self.assertRaises(urllib.error.HTTPError):
                            common.fetch_bytes('https://example.com', 5)
                    self.assertEqual(request.call_count, 1)
                    sleep.assert_not_called()

    def test_retry_after_is_honored_and_metrics_record_success(self):
        error = urllib.error.HTTPError('https://example.com', 429, 'slow down', {'Retry-After': '2'}, io.BytesIO())
        with patch.object(common.urllib.request, 'urlopen', side_effect=[error, io.BytesIO(b'ok')]) as request, patch.object(common.time, 'sleep') as sleep:
            self.assertEqual(common.fetch_bytes('https://example.com', 5), b'ok')
            sleep.assert_called_once_with(2.0)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(common.fetch_metrics()['bytes_downloaded'], 2)
            self.assertEqual(common.fetch_metrics()['retries'], 1)

    def test_retry_delay_does_not_exceed_device_budget(self):
        error = urllib.error.HTTPError('https://example.com', 503, 'unavailable', {'Retry-After': '60'}, io.BytesIO())
        with common.fetch_budget(0.1), patch.object(common.urllib.request, 'urlopen', side_effect=error), patch.object(common.time, 'sleep') as sleep:
            with self.assertRaises(TimeoutError):
                common.fetch_bytes('https://example.com', 5)
            sleep.assert_not_called()

    def test_oversized_response_is_rejected(self):
        with patch.object(common, 'MAX_RESPONSE_BYTES', 4), patch.object(common.urllib.request, 'urlopen', return_value=io.BytesIO(b'12345')):
            with self.assertRaisesRegex(ValueError, 'limit'):
                common.fetch_bytes('https://example.com', 5)

    def test_cache_resets_between_scans(self):
        with patch.object(common, '_download', return_value=b'ok') as request:
            common.fetch_bytes('https://example.com', 5)
            common.configure_fetch(0, 1)
            common.fetch_bytes('https://example.com', 5)
            self.assertEqual(request.call_count, 2)

    def test_per_host_concurrency_limit(self):
        lock = threading.Lock()
        active = peak = 0
        def open_url(*args, **kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return io.BytesIO(b'ok')
        with patch.object(common.urllib.request, 'urlopen', side_effect=open_url):
            with ThreadPoolExecutor(6) as pool:
                list(pool.map(lambda i: common.fetch_bytes(f'https://example.com/{i}', 5), range(6)))
        self.assertEqual(peak, 2)


class RobustParserTests(unittest.TestCase):
    def test_dji_real_pdf_extracts_camera_not_app_or_accessory_versions(self):
        releases = dji.parse_dji_release_pdf((FIXTURES / 'dji_pocket4p.pdf').read_bytes(), 'Osmo Pocket 4P')
        self.assertEqual(releases[0]['version'], '01.01.71.31')
        self.assertEqual(releases[0]['released_time'], '2026-09-03')
        self.assertGreater(len(releases), 1)
        self.assertIn('Google Drive, OneDrive', releases[0]['release_note']['en'])
        self.assertNotIn('2.11.8', [r['version'] for r in releases])

    def test_dji_modern_markup_and_pdf_fallback(self):
        html = (FIXTURES / 'dji_pocket4p.html').read_text()
        items = dji.parse_dji_release_note_items(html)
        self.assertEqual(len(items), 1)
        self.assertIn('/RN/', items[0]['href'])
        good = (FIXTURES / 'dji_pocket4p.pdf').read_bytes()
        with patch.object(dji, 'pick_dji_release_notes_pdfs', return_value=['/bad.pdf', items[0]['href']]), patch.object(dji, 'fetch_bytes', side_effect=[html.encode(), b'not a PDF', good]) as fetch:
            releases = dji.sync_dji_downloads('Osmo Pocket 4P', {'url': 'https://www.dji.com/global/downloads/products/osmo-pocket-4p'}, 5)
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(releases[0]['version'], '01.01.71.31')
        self.assertEqual(releases[0]['evidence']['source_url'], items[0]['href'])

    def test_dji_attributes_classes_and_query_strings_can_change(self):
        html = """<li data-id='x' class='extra groups-download-item'>
        <div class='other groups-item-name'><b>DJI Mini 5 Pro</b> - Release Notes</div>
        <a class='download-file' href='/RN/notes.pdf?download=1'>PDF</a></li>"""
        self.assertEqual(dji.pick_dji_release_notes_pdf(dji.parse_dji_release_note_items(html), 'Mini 5 Pro'), '/RN/notes.pdf?download=1')

    def test_apple_latest_phrase_can_contain_inline_tags(self):
        html = '<p>The latest version of <b>iOS</b> is <span>26.6.1</span>.</p><table><tr><td>iOS 26.6.1</td><td>17 August 2026</td></tr></table>'
        with patch.object(apple, 'fetch_bytes', return_value=html.encode()):
            releases = apple.sync_apple_support({'type': 'apple_support', 'kind': 'ios', 'url': 'https://support.apple.com/test'}, 5)
        self.assertEqual(releases[0]['version'], '26.6.1')
        self.assertEqual(releases[0]['released_time'], '2026-08-17')

    def test_atomos_article_is_isolated_and_upload_month_is_not_a_date(self):
        html = """<section id='NinjaVArticle' class='changed'><div><h2>Current Firmware</h2><p>AtomOS <b>11.19.00</b></p><a href='/2026/04/notes.html'>Release notes</a></div></section><div id='Other'>Current Firmware AtomOS 99.0</div>"""
        with patch.object(atomos, 'fetch_bytes', return_value=html.encode()):
            releases = atomos.sync_atomos_support({'type': 'atomos_support', 'url': 'https://www.atomos.com/product-support/', 'article_id': 'NinjaVArticle'}, 5)
        self.assertEqual(releases[0]['version'], '11.19.00')
        self.assertEqual(releases[0]['released_time'], '')

    def test_invalid_calendar_dates_rejected(self):
        for value in ('2026-02-30', '2026-13-01', '2025-02-29'):
            self.assertEqual(common.as_iso_date(value), '')
            candidate = common.make_release_candidate(version='1.0', released_time=value, evidence_type='test', evidence_text='test')
            self.assertEqual(common.resolve_release_candidates([candidate], {}), [])

    def test_guardrail_runs_before_metadata_merge(self):
        release = lambda v, d: {'version': v, 'released_time': d, 'active': True, 'release_note': {'en': ''}}
        current = [release('2.0', '2026-05-01')]
        accepted, reason, merged = prepare_release_update(current, [release('1.0', '2026-01-01')], {})
        self.assertFalse(accepted)
        self.assertEqual(merged, current)
        accepted, _, _ = prepare_release_update(current, [release('2.0', '')], {'type': 'apple_support', 'kind': 'ios'})
        self.assertFalse(accepted)
        accepted, _, merged = prepare_release_update(current, [], {'allow_empty': True}, 'ok_empty')
        self.assertTrue(accepted)
        self.assertEqual(merged, current)

    def test_explicit_unknown_date_does_not_restore_fabricated_history_date(self):
        prior = [{"version": "11.19.00", "released_time": "2026-04-01", "active": True, "release_note": {"en": ""}}]
        incoming = [{**prior[0], "released_time": "", "date_precision": "unknown"}]
        accepted, _, releases = prepare_release_update(prior, incoming, {"type": "atomos_support"})
        self.assertTrue(accepted)
        self.assertEqual(releases[0]["released_time"], "")

    def test_dji_filename_fallback_survives_all_class_name_changes(self):
        html = '<article><a href="/RN/DJI_Osmo_Pocket_4P_Release_Notes_en.pdf">Download</a></article>'
        items = dji.parse_dji_release_note_items(html)
        self.assertIsNotNone(dji.pick_dji_release_notes_pdf(items, "Osmo Pocket 4P"))
        self.assertIsNone(dji.pick_dji_release_notes_pdf(items, "Osmo Pocket 4"))
