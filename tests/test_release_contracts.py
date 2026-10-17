import copy
import io
import json
import socket
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import fetch_firmware_details as ffd
from sources import SYNC_HANDLERS, common, tplink, apple, atomos, bambu, dji, godox, sony


def release(version='1.2.0', date='2026-01-01'):
    return {'version': version, 'released_time': date, 'release_note': {'en': ''}, 'active': True}


class ReleaseContractTests(unittest.TestCase):
    def test_all_registered_sources_share_the_contract(self):
        fixtures = Path(__file__).parent / 'fixtures'
        cases = [
            ('apple_support', apple, {'kind': 'ios'}, (fixtures / 'apple_100100.html').read_bytes()),
            ('atomos_support', atomos, {'article_id': 'NinjaVArticle'}, (fixtures / 'atomos_ninjav.html').read_bytes()),
            ('bambu_wiki', bambu, {'series': 'P1'}, (fixtures / 'bambu_wiki.html').read_bytes()),
            ('dji_downloads', dji, {}, (fixtures / 'dji_pocket4p.html').read_bytes()),
            ('godox_listing', godox, {'title_contains': 'V860IIS'}, b'<div class="item"><div class="tit">V860IIS Firmware <span>V1.2</span></div><div class="text">Release Date 2026-01-01</div></div></body>'),
            ('sony_cscs', sony, {'mdl': 'ILCE-1M2'}, b"<script>config={, ver: '2.0'}</script><p>2026-01-01</p>"),
            ('tplink_downloads', tplink, {'model': 'Deco BE65', 'hardware_version': 'V2'}, b'Deco BE65(EU)_V2_1.2.0 Build 20250101 Published Date: 2026-01-01'),
        ]
        self.assertEqual({kind for kind, *_ in cases} | {'static'}, set(SYNC_HANDLERS))
        for kind, module, options, html in cases:
            source = {'type': kind, 'url': 'https://example.com/downloads', **options}
            def fetch(url, timeout):
                return (fixtures / 'dji_pocket4p.pdf').read_bytes() if '.pdf' in url else html
            with self.subTest(kind=kind), patch.object(module, 'fetch_bytes', side_effect=fetch):
                result = ffd.process_device('device', 'Osmo Pocket 4P', source, 1)
                self.assertEqual(result['status'], 'ok', result['reason'])
                common.validate_releases(result['releases'], source)
                self.assertTrue(result['releases'][0]['evidence']['source_url'].startswith('https://'))
        result = ffd.process_device('manual', 'Manual', {'type': 'static', 'release': release('App-managed', '')}, 1)
        self.assertEqual(result['status'], 'ok')

    def test_invalid_output_tries_fallback_without_mutating_input(self):
        invalids = [None, {}, [None], [release() | {'active': 'false'}],
                    [release() | {'version': 1.2}], [release() | {'version': ''}],
                    [release() | {'released_time': '2026-02-30'}],
                    [release() | {'released_time': ''}],
                    [release() | {'release_note': {}}],
                    [release() | {'confidence': float('inf')}],
                    [release() | {'confidence': True}],
                    [release() | {'evidence': {}}],
                    [release() | {'evidence': {'type': 'listing', 'text': '', 'source_url': 'file:///tmp/test'}}]]
        fallback = {'type': 'static', 'release': release()}
        source = {'type': 'dji_downloads', 'fallback_source': fallback}
        for invalid in invalids:
            before = copy.deepcopy(invalid)
            with self.subTest(invalid=invalid), patch.object(ffd, 'sync_device', side_effect=[invalid, [release()]]):
                result = ffd.process_device('camera', 'Camera', source, 1)
                self.assertEqual(result['status'], 'ok')
                self.assertTrue(result['used_fallback'])
                self.assertIn('Parser contract:', result['fallback_reason'])
                self.assertEqual(invalid, before)

    def test_date_and_empty_policies(self):
        common.validate_releases([release(date='')], {'type': 'static'})
        common.validate_releases([release(date='')], {'type': 'atomos_support'})
        for allow_empty in (False, True):
            with patch.object(ffd, 'sync_device', return_value=[]):
                result = ffd.process_device('device', 'Device', {'type': 'dji_downloads', 'allow_empty': allow_empty}, 1)
            self.assertEqual(result['status'], 'ok_empty' if allow_empty else 'no_entries')
        with self.assertRaisesRegex(ValueError, 'version_pattern'):
            common.validate_releases([release('wrong')], {'type': 'sony_cscs'})

    def test_normalization_does_not_modify_notes(self):
        raw = release() | {'release_note': {'fr': 'Bonjour'}}
        before = copy.deepcopy(raw)
        self.assertEqual(common.normalize_release(raw)['release_note'], {'en': ''})
        self.assertEqual(raw, before)

    def test_retryable_http_statuses_and_wrapped_errors(self):
        for code in (*sorted(common.RETRYABLE_HTTP), 400, 401, 403, 404):
            with self.subTest(code=code):
                error = urllib.error.HTTPError('https://example.com', code, 'temporary failure', {}, None)
                for exc in (error, urllib.error.URLError(error)):
                    self.assertEqual(ffd.is_transient_network_error(exc), code in common.RETRYABLE_HTTP)
                with patch.object(ffd, 'sync_device', side_effect=error):
                    result = ffd.process_device('camera', 'Camera', {'type': 'sony_cscs'}, 1)
                expected = 'transient_error' if code in common.RETRYABLE_HTTP else 'error'
                self.assertEqual(result['status'], expected)
                if code in common.RETRYABLE_HTTP:
                    self.assertFalse(ffd.should_fail_on_source_regression(result['status'], result['reason']))
                error.close()
        self.assertTrue(ffd.is_transient_network_error(urllib.error.URLError(socket.gaierror('DNS'))))

    def test_atomic_write_preserves_data_on_partial_write_and_replace_failure(self):
        def interrupted(payload, out, **kwargs):
            out.write('{"partial":')
            raise OSError('disk full')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'devices.json'
            original = '{"last_good": true}\n'
            path.write_text(original)
            for target, failure in [('sources.common.json.dump', interrupted), ('sources.common.os.fsync', OSError('flush failed')), ('pathlib.Path.replace', OSError('replace failed'))]:
                with self.subTest(target=target), patch(target, side_effect=failure):
                    with self.assertRaises(OSError):
                        common.write_json_atomic(path, {'new': True})
                self.assertEqual(path.read_text(), original)
                self.assertEqual(list(Path(directory).iterdir()), [path])
            common.write_json_atomic(path, {'new': True})
            self.assertEqual(json.loads(path.read_text()), {'new': True})
            self.assertTrue(path.read_text().endswith('\n'))

    def test_allowed_correction_deactivates_higher_history(self):
        current = [release('2.0'), release('0.5')]
        before = copy.deepcopy(current)
        source = {'allow_regression': True}
        accepted, _, merged = ffd.prepare_release_update(current, [release('1.0')], source)
        self.assertTrue(accepted)
        self.assertEqual(common.get_latest_active_release(merged)['version'], '1.0')
        self.assertFalse(next(r for r in merged if r['version'] == '2.0')['active'])
        self.assertTrue(next(r for r in merged if r['version'] == '0.5')['active'])
        self.assertEqual(current, before)
        _, _, again = ffd.prepare_release_update(merged, [release('1.0')], source)
        self.assertEqual(again, merged)

    def test_tplink_builds_survive_history_and_legacy_migration(self):
        legacy = release() | {'release_note': {'en': 'Build: 20250101'},
                              'evidence': {'type': 'tplink_download_item', 'text': '', 'source_url': 'https://www.tp-link.com/'}}
        source = {'type': 'tplink_downloads'}
        incoming = release('1.2.0 Build 20250101')
        accepted, _, merged = ffd.prepare_release_update([legacy], [incoming], source)
        self.assertTrue(accepted)
        self.assertEqual(len(merged), 1)
        newer = release('1.2.0 Build 20250102')
        accepted, _, merged = ffd.prepare_release_update(merged, [newer], source)
        self.assertTrue(accepted)
        self.assertEqual(len(merged), 2)
        self.assertEqual(common.get_latest_active_release(merged)['version'], newer['version'])
        accepted, _, _ = ffd.prepare_release_update(merged, [incoming], source)
        self.assertFalse(accepted)
        self.assertEqual(legacy['version'], '1.2.0')

    def test_tplink_parser_selects_newest_build_of_same_version(self):
        html = '''Deco BE65(EU)_V2_1.2.0 Build 20250101
        Published Date: 2026-01-01
        Deco BE65(EU)_V2_1.2.0 Build 20250102
        Published Date: 2026-01-01'''
        source = {'type': 'tplink_downloads', 'url': 'https://www.tp-link.com/download/', 'model': 'Deco BE65', 'hardware_version': 'V2'}
        with patch.object(tplink, 'fetch_bytes', return_value=html.encode()):
            releases = tplink.sync_tplink_downloads(source, 1)
        common.validate_releases(releases, source)
        self.assertEqual(releases[0]['version'], '1.2.0 Build 20250102')

    def test_scan_persists_legacy_build_migration_without_duplicate_history(self):
        legacy = release() | {'release_note': {'en': 'Build: 20250101'},
                              'evidence': {'type': 'tplink_download_item', 'text': '', 'source_url': 'https://www.tp-link.com/'}}
        source = {'type': 'tplink_downloads', 'url': 'https://www.tp-link.com/', 'model': 'Deco BE65', 'hardware_version': 'V2'}
        payload = {'sources': {'device_sources': {'router': source}},
                   'categories': {'network': {'title': 'Network', 'devices': {'router': 'Router'}}},
                   'firmware_index': {'router': {'releases': [legacy]}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'devices.json'
            path.write_text(json.dumps(payload))
            with (patch.object(ffd, 'DATA_FILE', path), patch.object(ffd, 'sync_device', return_value=[common.normalize_release(legacy)]),
                  patch.object(sys, 'argv', ['scan', '--fail-on-regression']),
                  patch.dict(ffd.os.environ, {'GITHUB_STEP_SUMMARY': ''}), patch('sys.stdout', new_callable=io.StringIO)):
                self.assertEqual(ffd.main(), 0)
            releases = json.loads(path.read_text())['firmware_index']['router']['releases']
            self.assertEqual(len(releases), 1)
            self.assertEqual(releases[0]['version'], '1.2.0 Build 20250101')

    def test_strict_scan_keeps_transient_device_and_writes_healthy_update(self):
        payload = {'sources': {'device_sources': {name: {'type': 'sony_cscs', 'mdl': name} for name in ('failed', 'healthy')}},
                   'categories': {'cameras': {'title': 'Cameras', 'devices': {'failed': 'Failed', 'healthy': 'Healthy'}}},
                   'firmware_index': {name: {'releases': [release()]} for name in ('failed', 'healthy')}}
        def sync(name, source, timeout):
            if name == 'Failed':
                raise urllib.error.HTTPError('https://example.com', 503, 'Unavailable', {}, None)
            return [release('2.0')]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'devices.json'
            path.write_text(json.dumps(payload))
            with (patch.object(ffd, 'DATA_FILE', path), patch.object(ffd, 'sync_device', side_effect=sync),
                  patch.object(sys, 'argv', ['scan', '--fail-on-regression']),
                  patch.dict(ffd.os.environ, {'GITHUB_STEP_SUMMARY': ''}), patch('sys.stdout', new_callable=io.StringIO)):
                self.assertEqual(ffd.main(), 0)
            updated = json.loads(path.read_text())
            self.assertEqual(updated['firmware_index']['failed'], payload['firmware_index']['failed'])
            self.assertEqual(common.get_latest_active_release(updated['firmware_index']['healthy']['releases'])['version'], '2.0')
