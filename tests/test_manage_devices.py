import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from manage_devices import apply_change, build_source, infer_type


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.payload = {'sources': {'device_sources': {}}, 'categories': {'cameras': {'title': 'Cameras', 'devices': {}}}, 'firmware_index': {}}
        self.form = {'action': 'add', 'name': 'Osmo Pocket 4P', 'source_url': 'https://www.dji.com/global/downloads/products/osmo-pocket-4p'}
        self.checker = Mock(return_value={'status': 'ok', 'reason': '', 'vendor': 'dji', 'releases': [{'version': '01.01.71.31', 'released_time': '2026-09-03', 'active': True, 'release_note': {'en': ''}}]})

    def test_add_detects_vendor_generates_id_and_checks_source(self):
        original = copy.deepcopy(self.payload)
        updated, report = apply_change(self.payload, self.form, self.checker)
        self.assertEqual(report['device_id'], 'osmo_pocket_4p')
        self.assertEqual(updated['categories']['cameras']['devices']['osmo_pocket_4p'], 'Osmo Pocket 4P')
        self.assertEqual(updated['sources']['device_sources']['osmo_pocket_4p']['model'], 'Osmo Pocket 4P')
        self.assertEqual(self.payload, original)
        self.checker.assert_called_once()

    def test_duplicate_add_rejected(self):
        updated, _ = apply_change(self.payload, self.form, self.checker)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            apply_change(updated, self.form, self.checker)

    def test_update_preserves_source_options_and_history(self):
        updated, _ = apply_change(self.payload, self.form, self.checker)
        updated['sources']['device_sources']['osmo_pocket_4p']['allow_empty'] = True
        self.checker.return_value['releases'][0]['version'] = '01.02.00.00'
        revised, report = apply_change(updated, {'action': 'update', 'device_id': 'osmo_pocket_4p', 'name': 'My Pocket', 'category': 'Travel'}, self.checker)
        self.assertEqual(len(revised['firmware_index']['osmo_pocket_4p']['releases']), 2)
        self.assertTrue(revised['sources']['device_sources']['osmo_pocket_4p']['allow_empty'])
        self.assertEqual(revised['categories']['travel']['devices']['osmo_pocket_4p'], 'My Pocket')

    def test_source_failure_leaves_input_untouched(self):
        before = copy.deepcopy(self.payload)
        self.checker.return_value.update(status='error', reason='Bad PDF')
        with self.assertRaisesRegex(ValueError, 'Source check failed'):
            apply_change(self.payload, self.form, self.checker)
        self.assertEqual(self.payload, before)

    def test_remove_cleans_device_maps_and_does_not_fetch(self):
        updated, _ = apply_change(self.payload, self.form, self.checker)
        self.checker.reset_mock()
        removed, report = apply_change(updated, {'action': 'remove', 'device_id': 'osmo_pocket_4p'}, self.checker)
        self.assertNotIn('osmo_pocket_4p', removed['firmware_index'])
        self.assertNotIn('osmo_pocket_4p', removed['sources']['device_sources'])
        self.assertNotIn('osmo_pocket_4p', removed['categories']['cameras']['devices'])
        self.checker.assert_not_called()

    def test_update_requires_known_explicit_id(self):
        with self.assertRaises(ValueError):
            apply_change(self.payload, {'action': 'update', 'name': 'Missing'}, self.checker)

    def test_mismatched_vendor_domain_is_rejected_before_fetch(self):
        self.form.update(source_url='https://dji.com.evil.example/downloads', source_type='dji_downloads')
        with self.assertRaisesRegex(ValueError, 'official'):
            apply_change(self.payload, self.form, self.checker)
        self.checker.assert_not_called()

    def test_required_vendor_fields_explain_missing_input(self):
        with self.assertRaisesRegex(ValueError, 'hardware_version'):
            build_source({'source_url': 'https://www.tp-link.com/nordic/support/download/deco-be65/', 'model': 'Deco BE65'}, 'Deco BE65')

    def test_explicit_variants_for_supported_vendors(self):
        cases = [
            ('https://www.sony.com/support/', 'ILCE-1M2', '', 'mdl', 'ILCE-1M2'),
            ('https://www.godox.com/firmware/', 'V860IIS Firmware', '', 'title_contains', 'V860IIS Firmware'),
            ('https://www.atomos.com/product-support/', '', 'NinjaVArticle', 'article_id', 'NinjaVArticle'),
            ('https://wiki.bambulab.com/history/', '', 'p1', 'series', 'P1'),
            ('https://www.tp-link.com/support/', 'Deco BE65', 'v2', 'hardware_version', 'V2'),
            ('https://support.apple.com/100100', '', 'ios', 'kind', 'ios'),
        ]
        for url, model, variant, field, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(build_source({'source_url': url, 'model': model, 'variant': variant}, 'Device')[field], expected)

    def test_static_entry_needs_explicit_status(self):
        form = {'source_url': 'https://example.com/support', 'source_type': 'static', 'manual_version': 'App-managed'}
        self.assertEqual(build_source(form, 'Lamp')['release']['version'], 'App-managed')

    def test_downgrade_blocks_update(self):
        updated, _ = apply_change(self.payload, self.form, self.checker)
        self.checker.return_value['releases'][0]['version'] = '00.01.00.00'
        with self.assertRaisesRegex(ValueError, 'older latest version'):
            apply_change(updated, {'action': 'update', 'device_id': 'osmo_pocket_4p'}, self.checker)

    def test_renaming_legacy_dji_keeps_original_model_match(self):
        updated, _ = apply_change(self.payload, self.form, self.checker)
        del updated['sources']['device_sources']['osmo_pocket_4p']['model']
        revised, _ = apply_change(updated, {'action': 'update', 'device_id': 'osmo_pocket_4p', 'name': 'Travel Camera'}, self.checker)
        self.assertEqual(revised['sources']['device_sources']['osmo_pocket_4p']['model'], 'Osmo Pocket 4P')
