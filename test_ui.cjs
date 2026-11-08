// Optional browser check. Requires Playwright; starts its own local test server.
const {chromium} = require('playwright');
const path = require('path');
const {spawn} = require('child_process');
(async () => {
  let browser;
  let server;
  try {
    if (!process.env.CHATMATE_TEST_URL) {
      server = spawn(process.env.PYTHON || 'python', ['-c',
        "from app import app; app.run(host='127.0.0.1', port=5052, debug=False)"], {
        cwd: __dirname, env: {...process.env, CHATMATE_OPERATOR_TOKEN: 'operator-browser-test-credential-123456',
          CHATMATE_SUBMIT_TOKEN: 'submitter-browser-test-credential-123456'}});
      await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Test server did not start.')), 10000);
        server.once('error', error => {clearTimeout(timeout); reject(error);});
        server.once('exit', () => {clearTimeout(timeout); reject(new Error('Test server exited early.'));});
        server.stderr.on('data', data => {if (String(data).includes('Running on')) {clearTimeout(timeout); resolve();}});
      });
    }
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({viewport: {width: 1100, height: 1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.env.CHATMATE_TEST_URL || 'http://127.0.0.1:5052');
    await page.locator('summary').click();
    await page.locator('#operator-token').fill('operator-browser-test-credential-123456');
    await page.locator('#demo').click();
    await page.waitForFunction(() => document.getElementById('suite').value.length === 64);
    await page.locator('#submit-token').fill('submitter-browser-test-credential-123456');
    await page.locator('#submit').click();
    await page.waitForFunction(() => document.querySelector('#conversation h2')?.textContent.startsWith('BLOCK'));
    await page.locator('#code').fill('def add(a, b):\n    return a + b');
    await page.locator('#submit').click();
    await page.waitForFunction(() => document.querySelector('#conversation h2')?.textContent === 'ACCEPT · 12/12 tests passed');
    if (errors.length) throw new Error(errors.join('\n'));
    await page.locator('summary').click();
    await page.screenshot({path: path.join(__dirname, '.chatmate-state', 'ui-desktop.png'), fullPage: true});
    await page.setViewportSize({width: 390, height: 844});
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Mobile layout overflows.');
    await page.screenshot({path: path.join(__dirname, '.chatmate-state', 'ui-mobile.png'), fullPage: true});
    console.log('Browser verification passed: frozen suite, BLOCK, ACCEPT, no script errors, mobile layout.');
  } finally { if (browser) await browser.close(); if (server) server.kill(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
