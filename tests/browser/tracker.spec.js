const {test, expect} = require('@playwright/test');
const data = require('../fixtures/browser-devices.json');
const latest = releases => releases.filter(r => r.active).sort((a,b) => b.version.localeCompare(a.version, undefined, {numeric:true}))[0];
const baseline = Object.fromEntries(Object.entries(data.firmware_index).map(([id, entry]) => [id, latest(entry.releases)?.version]).filter(([,version]) => version));

test.beforeEach(async ({page}) => {
  // Stable browser fixtures let management PRs add/remove real devices freely.
  const config = structuredClone(data.config);
  config.source_sync_status.last_run_utc = new Date().toISOString();
  for (const health of Object.values(config.source_sync_status.device_health)) health.last_success_utc = config.source_sync_status.last_run_utc;
  for (const [file, name, value] of [
    ['categories.js', 'CATEGORIES', data.categories],
    ['index.js', 'FIRMWARE_INDEX', data.firmware_index],
    ['config.js', 'TRACKER_CONFIG', config]
  ]) {
    await page.route(`**/devices/${file}`, route => route.fulfill({contentType:'application/javascript', body:`const ${name} = ${JSON.stringify(value)};`}));
  }
});

async function seedUnseen(page) {
  await page.addInitScript(snapshot => {
    localStorage.setItem('firmware_tracker_seen_versions_v1', JSON.stringify(snapshot));
  }, {...baseline, osmo_pocket_4p: '0.0', sony_a1ii: '0.0'});
}

test('search, category and empty state work together', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', {name:'Firmware Tracker', exact:true})).toBeVisible();
  await expect(page.getByRole('link', {name:'Manage devices on GitHub'})).toHaveAttribute('href', /actions\/workflows\/manage-devices.yml$/);
  await page.getByLabel('Search devices', {exact:true}).fill('pOcKeT');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody')).toContainText('Osmo Pocket 4P');
  await page.getByLabel('Category', {exact:true}).selectOption('platforms');
  await expect(page.getByRole('heading', {name:'No matching devices'})).toBeVisible();
  await page.getByRole('button', {name:'Clear filters'}).click();
  await expect(page.locator('tbody tr')).toHaveCount(Object.values(data.config.device_source_types).filter(type => type !== 'static').length);
  await expect(page.getByLabel('Search devices', {exact:true})).toBeFocused();
  expect(errors).toEqual([]);
});

test('sort controls are accessible on desktop and mobile', async ({page}, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Sort by', {exact:true}).selectOption('date:desc');
  const firstDate = await page.locator('tbody tr').first().locator('[data-label="Released"]').textContent();
  expect(firstDate).not.toBe('Unknown');
  await expect(page.locator('tbody tr').last().locator('[data-label="Released"]')).toHaveText('Unknown');
  if (testInfo.project.name === 'desktop') {
    await page.getByRole('button', {name:'Sort by device', exact:true}).focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('th[aria-sort="ascending"]')).toContainText('Device');
    await page.keyboard.press('Enter');
    await expect(page.locator('th[aria-sort="descending"]')).toContainText('Device');
    await expect(page.getByRole('button', {name:'Sort by device', exact:true})).toBeFocused();
  } else {
    await page.getByLabel('Sort by', {exact:true}).selectOption('name:desc');
    await expect(page.getByLabel('Sort by', {exact:true})).toHaveValue('name:desc');
  }
});

test('dialog prioritizes latest release and restores focus on Escape', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button', {name:'Release history for Osmo Pocket 4P', exact:true}).click();
  const dialog = page.getByRole('dialog', {name:'Osmo Pocket 4P'});
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button', {name:'Close', exact:true})).toBeFocused();
  await expect(dialog.getByRole('link', {name:'Open official download page'})).toHaveCount(1);
  await expect(dialog.locator('.latest-release')).toContainText('01.01.71.31');
  await expect(dialog).not.toContainText('ARB:');
  await expect(dialog.locator('details')).not.toHaveAttribute('open');
  await dialog.locator('summary').click();
  await expect(dialog.locator('details')).toHaveAttribute('open');
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button', {name:'Release history for Osmo Pocket 4P', exact:true})).toBeFocused();
});

test('modal keeps keyboard focus inside its controls', async ({page}) => {
  await page.goto('/');
  await page.getByRole('button', {name:'Release history for Osmo Pocket 4P', exact:true}).click();
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => document.getElementById('modal').contains(document.activeElement))).toBe(true);
  }
});

test('mark one device seen preserves filters and other unseen releases', async ({page}) => {
  await seedUnseen(page);
  await page.goto('/');
  await expect(page.locator('#firmware-status-title')).toHaveText('2 unseen releases');
  await page.getByLabel('Unseen releases only').check();
  await page.getByRole('button', {name:'Release history for Osmo Pocket 4P', exact:true}).click();
  await page.getByRole('button', {name:'Mark as seen', exact:true}).click();
  await page.getByRole('button', {name:'Close', exact:true}).click();
  await expect(page.getByLabel('Unseen releases only')).toBeChecked();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('#firmware-status-title')).toHaveText('1 unseen release');
  await expect(page.getByLabel('Search devices', {exact:true})).toBeFocused();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('firmware_tracker_seen_versions_v1')));
  expect(saved.osmo_pocket_4p).toBe('01.01.71.31');
  expect(saved.sony_a1ii).toBe('0.0');
  await page.getByRole('button', {name:'Mark all as seen'}).click();
  await expect(page.locator('#firmware-status-title')).toHaveText('No unseen releases');
  await expect(page.getByRole('heading', {name:'No matching devices'})).toBeVisible();
});

test('fresh generation cannot hide stale source checks', async ({page}) => {
  await page.route('**/devices/config.js', async route => {
    const config = structuredClone(data.config);
    config.generated_at_utc = new Date().toISOString();
    config.source_sync_status.last_run_utc = '2020-01-01T10:00:00Z';
    config.source_sync_status.device_health.osmo_pocket_4p.last_success_utc = '2020-01-01T10:00:00Z';
    await route.fulfill({contentType:'application/javascript', body:`const TRACKER_CONFIG = ${JSON.stringify(config)};`});
  });
  await page.goto('/');
  await expect(page.locator('#firmware-status-meta')).toContainText('2020');
  await expect(page.locator('#firmware-status-meta')).toContainText('Check overdue');
  const row = page.locator('tbody tr').filter({hasText:'Osmo Pocket 4P'});
  await expect(row).toContainText('Check overdue');
});

test('viewport has no horizontal overflow and history remains usable', async ({page}, testInfo) => {
  await seedUnseen(page);
  await page.goto('/');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({path: testInfo.outputPath('table.png'), animations:'disabled'});
  await page.getByRole('button', {name:'Release history for Osmo Pocket 4P', exact:true}).click();
  expect(await page.evaluate(() => document.getElementById('modal').scrollWidth <= document.getElementById('modal').clientWidth)).toBe(true);
  await page.screenshot({path: testInfo.outputPath('history.png'), animations:'disabled'});
  await page.getByRole('button', {name:'Close', exact:true}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
});
