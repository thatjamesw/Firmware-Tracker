const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function app() {
  const functions = fs.readFileSync(path.join(__dirname, "../docs/app.js"), "utf8");
  const storage = new Map();
  const context = vm.createContext({
    TRACKER_CONFIG: {},
    localStorage: {getItem: k => storage.get(k) ?? null, setItem: (k,v) => storage.set(k,v)},
    Intl, Date,
  });
  vm.runInContext(functions, context);
  return context;
}
const row = (deviceId, version) => ({deviceId, latest: version ? {version} : null});

test('first visit establishes baseline without notifications', () => {
  const ctx = app();
  assert.equal(ctx.detectNewFirmware([row('camera','1.0')]).newDeviceIds.size, 0);
  assert.equal(ctx.detectNewFirmware([row('camera','1.0')]).hasBaseline, true);
});

test('existing visitor sees the first firmware release for a previously empty device', () => {
  const ctx = app();
  ctx.detectNewFirmware([row('camera','1.0'), row('newCamera', null)]);
  assert.equal(ctx.detectNewFirmware([row('camera','1.0'), row('newCamera','1.0')]).newDeviceIds.has('newCamera'), true);
});

test('marking current versions seen clears notifications', () => {
  const ctx = app();
  ctx.detectNewFirmware([row('camera','1.0')]);
  const detection = ctx.detectNewFirmware([row('camera','2.0')]);
  assert.equal(detection.newDeviceIds.size, 1);
  ctx.saveSeenVersions(detection.current);
  assert.equal(ctx.detectNewFirmware([row('camera','2.0')]).newDeviceIds.size, 0);
});

test('invalid dates remain last for either sort direction', () => {
  const ctx = app();
  const dated = {...row('known','1.0'), deviceName:'Known', latest:{version:'1.0',released_time:'2026-09-03'}};
  const unknown = {...row('unknown','1.0'), deviceName:'Unknown'};
  assert.ok(ctx.compareRows(unknown, dated, 'date', 'asc') > 0);
  assert.ok(ctx.compareRows(unknown, dated, 'date', 'desc') > 0);
});

test('filters combine category, search and unseen state', () => {
  const ctx = app();
  const rows = [{deviceId:'pocket', deviceName:'Osmo Pocket 4P', category:'Cameras', categoryId:'cameras'}, {deviceId:'phone', deviceName:'iOS', category:'Apple', categoryId:'apple'}];
  const state = {query:'POCKET', category:'cameras', unseenOnly:true, unseen:new Set(['pocket'])};
  assert.equal(ctx.filteredRows(rows,state).length, 1);
  assert.equal(ctx.filteredRows(rows,{...state,category:'apple'}).length, 0);
});

test('no successful source check is explicitly unknown', () => {
  const freshness = app().sourceFreshness('unknown');
  assert.equal(freshness.warning, true);
  assert.equal(freshness.label, 'Not checked yet');
});

test('recent source failures warn per device while successful checks remain clear', () => {
  const ctx = app();
  const now = Date.parse('2026-09-06T12:00:00Z');
  for (const status of ['ok', 'ok_empty', 'transient_error', 'error']) {
    ctx.TRACKER_CONFIG.source_sync_status = {device_health: {
      camera: {status, last_success_utc: '2026-09-06T11:00:00Z'}
    }};
    const freshness = ctx.sourceFreshness('camera', now);
    const failed = !['ok', 'ok_empty'].includes(status);
    assert.equal(freshness.warning, failed, status);
    assert.equal(freshness.label, failed ? 'Source issue' : '', status);
    assert.equal(freshness.detail.includes('Latest check failed; stored data is shown.'), failed, status);
  }
});

test('manual fallback shows its verification date without claiming a fresh source check', () => {
  const ctx = app();
  ctx.TRACKER_CONFIG.source_sync_status = {device_health: {
    atomos_ninja_v: {status: 'manual_fallback', last_success_utc: '2026-09-07T07:16:04Z',
      manual_verified_utc: '2026-09-28T10:16:00Z', last_error_reason: 'Atomos returned HTTP 403.'}
  }};
  const freshness = ctx.sourceFreshness('atomos_ninja_v', Date.parse('2026-09-28T12:00:00Z'));
  assert.equal(freshness.label, 'Manually verified');
  assert.equal(freshness.warning, true);
  assert.ok(freshness.detail.includes('HTTP 403'));
  assert.ok(freshness.detail.includes('Official version verified:'));
});

test('release notes are escaped and empty metadata omitted', () => {
  const markup = app().releaseMarkup({version:'1.0', active:true, release_note:{en:'<script>alert(1)</script>'}, arb:null});
  assert.ok(markup.includes('&lt;script&gt;'));
  assert.ok(!markup.includes('<script>'));
  assert.ok(!markup.includes('Anti-rollback'));
});

test('TP-Link build changes notify and choose the newest build', () => {
  const ctx = app();
  const oldVersion = '1.2.0 Build 20250101';
  const newVersion = '1.2.0 Build 20250102';
  ctx.detectNewFirmware([row('router', oldVersion)]);
  const detection = ctx.detectNewFirmware([row('router', newVersion)]);
  assert.equal(detection.newDeviceIds.has('router'), true);
  ctx.saveSeenVersions(detection.current);
  assert.equal(ctx.detectNewFirmware([row('router', newVersion)]).newDeviceIds.size, 0);
  const latest = ctx.getLatestActiveRelease([
    {version: oldVersion, active: true, released_time: '2026-02-01'},
    {version: newVersion, active: true, released_time: '2026-01-01'},
  ]);
  assert.equal(latest.version, newVersion);
});

test('inactive higher versions do not conceal an approved correction', () => {
  assert.equal(app().getLatestActiveRelease([
    {version: '2.0', active: false}, {version: '1.0', active: true},
  ]).version, '1.0');
});


test('metadata corrections do not mark an acknowledged version new', () => {
  const ctx = app();
  ctx.detectNewFirmware([row('camera', '2.0')]);
  const corrected = {...row('camera', '2.0'), latest: {version: '2.0', released_time: '2026-10-26'}};
  assert.equal(ctx.detectNewFirmware([corrected]).newDeviceIds.size, 0);
  assert.equal(ctx.detectNewFirmware([row('camera', '3.0')]).newDeviceIds.size, 1);
});

test('coverage reflects device checks rather than the global scan timestamp', () => {
  const ctx = app();
  const now = Date.parse('2026-11-03T12:00:00Z');
  const current = new Date(now).toISOString();
  ctx.TRACKER_CONFIG.source_sync_status = {last_run_utc: current, device_health: {
    healthy: {status:'ok', last_success_utc:current},
    empty: {status:'ok_empty', last_success_utc:current},
    failed: {status:'error', last_success_utc:current},
    stale: {status:'ok', last_success_utc:'2020-01-01T00:00:00Z'},
    manual: {status:'manual_fallback', last_success_utc:current},
    recent: {status:'ok', last_success_utc:new Date(now - 86400000).toISOString()},
  }};
  const coverage = ctx.sourceCoverage(['healthy','empty','failed','stale','manual','recent','missing'].map(deviceId => ({deviceId})), now);
  assert.equal(coverage.text, '2 devices checked today · 1 checked recently · 1 check overdue · 1 check failed · 1 not checked yet · 1 manually verified');
  assert.equal(coverage.warning, true);
  assert.equal(ctx.sourceCoverage([{deviceId:'healthy'}], now).warning, false);
  assert.equal(ctx.sourceCoverage(['healthy', 'recent', 'manual'].map(deviceId => ({deviceId})), now).warning, false);
});
