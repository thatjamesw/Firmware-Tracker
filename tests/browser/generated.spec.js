const {test, expect} = require('@playwright/test');

test('generated assets load and render devices', async ({page}) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await page.getByRole('button', {name:'All devices', exact:true}).click();
  await expect(page.locator('tbody tr').first()).toBeVisible();
  await expect(page.locator('#firmware-status-coverage')).toHaveText(/\S/);
  expect(errors).toEqual([]);
});
