const {defineConfig} = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/browser',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: 2,
  reporter: 'list',
  use: {baseURL: 'http://127.0.0.1:8765', trace: 'retain-on-failure'},
  projects: [
    {name: 'desktop', use: {browserName: 'chromium', viewport: {width: 1280, height: 900}}},
    {name: 'mobile', use: {browserName: 'chromium', viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true}}
  ],
  webServer: {
    command: 'python3 -m http.server 8765 --bind 127.0.0.1 --directory docs',
    url: 'http://127.0.0.1:8765',
    reuseExistingServer: false
  }
});
