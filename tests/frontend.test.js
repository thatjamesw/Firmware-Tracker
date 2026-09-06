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

test('release notes are escaped and empty metadata omitted', () => {
  const markup = app().releaseMarkup({version:'1.0', active:true, release_note:{en:'<script>alert(1)</script>'}, arb:null});
  assert.ok(markup.includes('&lt;script&gt;'));
  assert.ok(!markup.includes('<script>'));
  assert.ok(!markup.includes('Anti-rollback'));
});
