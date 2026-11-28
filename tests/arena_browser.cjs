const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require('playwright');

const base = 'http://127.0.0.1:5080';
const screenshots = process.env.ARENA_SCREENSHOTS;
const metrics = [];
const errors = [];

async function waitForServer(url) {
  const deadline = Date.now() + 12000;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Arena server did not start');
}

function startServer(port, cwd, legacy = false) {
  const code = `import server; server.PORT=${port}; ` +
    (legacy ? '' : 'server.AUCTION_COUNTDOWN_SECONDS=4; server.AUCTION_INTERMISSION_SECONDS=0.15; ') +
    'import asyncio; asyncio.run(server.main())';
  return spawn('python', ['-u', '-c', code], {cwd, stdio: 'inherit'});
}

async function snap(page, name) {
  if (screenshots) await page.screenshot({path: path.join(screenshots, name + '.png')});
}

async function openPage(browser, width) {
  const context = await browser.newContext({viewport: {width, height: 900}, reducedMotion: 'reduce'});
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(String(error)));
  page.on('dialog', dialog => {
    errors.push(dialog.message());
    dialog.dismiss();
  });
  await page.addInitScript(() => {
    window.arenaMetrics = {lcp: 0, cls: 0};
    new PerformanceObserver(entries => {
      window.arenaMetrics.lcp = entries.getEntries().at(-1).startTime;
    }).observe({type: 'largest-contentful-paint', buffered: true});
    new PerformanceObserver(entries => {
      for (const entry of entries.getEntries()) {
        if (!entry.hadRecentInput) window.arenaMetrics.cls += entry.value;
      }
    }).observe({type: 'layout-shift', buffered: true});
  });
  return {context, page};
}

async function game(browser, width) {
  const {context: hc, page: host} = await openPage(browser, width);
  const {context: gc, page: guest} = await openPage(browser, width);
  const stage = '#arena-stage.active';
  try {
    await Promise.all([host.goto(base), guest.goto(base)]);
    await host.locator('#open-create-modal-btn').click();
    assert.match(await host.locator('#ticket-purse-select').innerText(), /\$100/);
    await host.getByRole('button', {name: 'Marvel MCU', exact: true}).click();
    await host.getByRole('button', {name: 'Tear off stub to create auction room'}).press('Enter');
    await host.locator('#arena-lobby.active').waitFor();
    const code = await host.locator('#lobby-code-display').textContent();
    await guest.locator('#open-join-modal-btn').click();
    await guest.getByRole('textbox', {name: 'Enter 8-character room code'}).fill(code.replace('-', ''));
    await guest.getByRole('button', {name: 'Tear off stub to join existing room'}).press('Enter');
    await guest.locator('#arena-lobby.active').waitFor();
    await host.locator('#ready-toggle-btn').click();
    await guest.locator('#ready-toggle-btn').click();
    await host.locator('#start-game-btn').click();
    await Promise.all([host.locator(stage).waitFor(), guest.locator(stage).waitFor()]);
    await host.locator('#custom-bid-input').fill('5');
    const sample = Date.now();
    await host.locator('#submit-bid-btn').click();
    await host.waitForFunction(() => document.querySelector('#current-bid-amount').textContent === '5');
    metrics.push({width, bidRoundTripMs: Date.now() - sample});
    await guest.locator('#custom-bid-input').fill('6');
    await guest.locator('#submit-bid-btn').click();
    await host.waitForFunction(() => document.querySelector('#current-bid-amount').textContent === '6');

    const hostId = await host.evaluate(() => sessionStorage.getItem('pkmn_auction_session_id'));
    const guestId = await guest.evaluate(() => sessionStorage.getItem('pkmn_auction_session_id'));
    const hostPersistentId = await host.evaluate(() => localStorage.getItem('pkmn_auction_session_id'));
    const guestPersistentId = await guest.evaluate(() => localStorage.getItem('pkmn_auction_session_id'));
    await Promise.all([host.reload(), guest.reload()]);
    await Promise.all([host.locator(stage).waitFor(), guest.locator(stage).waitFor()]);
    assert.equal(await host.evaluate(() => sessionStorage.getItem('pkmn_auction_session_id')), hostId);
    assert.equal(await guest.evaluate(() => sessionStorage.getItem('pkmn_auction_session_id')), guestId);
    assert.equal(await host.evaluate(() => localStorage.getItem('pkmn_auction_session_id')), hostPersistentId);
    assert.equal(await guest.evaluate(() => localStorage.getItem('pkmn_auction_session_id')), guestPersistentId);
    assert.equal(await host.locator('#current-bid-amount').textContent(), '6');
    assert.ok(await host.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await snap(host, `auction-${width}`);

    await host.waitForFunction(() => document.querySelector('#bid-pool-done').textContent.startsWith('LOT 2 /'));
    assert.equal(await guest.locator('#my-bar-purse').textContent(), '$94');
    await host.locator('#custom-bid-input').fill('2');
    await host.locator('#submit-bid-btn').click();
    await host.waitForFunction(() => document.querySelector('#current-bid-amount').textContent === '2');
    await hc.setOffline(true);
    await host.evaluate(() => gameState.ws.close());
    await host.locator('#connection-status').waitFor();
    await hc.setOffline(false);
    await host.waitForFunction(() => document.querySelector('#connection-status').hidden);

    for (let round = 3; round <= 16; round++) {
      for (const page of [host, guest]) {
        await page.waitForFunction(number => document.querySelector('#bid-pool-done').textContent.startsWith(`LOT ${number} /`), round);
      }
      await Promise.all([host.locator('#btn-skip-character').click(), guest.locator('#btn-skip-character').click()]);
    }
    await Promise.all([host.locator('#arena-results.active').waitFor(), guest.locator('#arena-results.active').waitFor()]);
    assert.match(await host.locator('#battle-champion-banner').textContent(), /Champion/);
    assert.match(await host.locator('#mvp-character-franchise').textContent(), /damage/);
    assert.ok(await host.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await snap(host, `results-${width}`);
    await host.locator('#btn-rematch').click();
    await guest.locator('#btn-rematch-accept').click();
    await host.locator(stage).waitFor();
    assert.equal(await host.locator('#my-bar-purse').textContent(), '$100');
    assert.equal(await host.locator('#my-team-count-display').textContent(), '0/6');
  } finally {
    await Promise.all([hc.close(), gc.close()]);
  }
}

async function run() {
  if (screenshots) await fs.mkdir(screenshots, {recursive: true});
  const primary = startServer(5080, process.cwd());
  const baseline = process.env.ARENA_BASELINE_DIR;
  const comparison = baseline ? startServer(5081, baseline, true) : null;
  try {
    await waitForServer(base);
    const browser = await chromium.launch({
      executablePath: process.env.CHROMIUM_PATH,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    });
    try {
      if (comparison) {
        await waitForServer('http://127.0.0.1:5081/');
        const {context, page} = await openPage(browser, 1440);
        const beforeErrors = [];
        page.removeAllListeners('pageerror');
        page.on('pageerror', error => beforeErrors.push(String(error)));
        await page.goto('http://127.0.0.1:5081/');
        await snap(page, 'landing-before');
        await page.waitForTimeout(350);
        console.log('Baseline page errors', beforeErrors);
        await context.close();
      }
      for (const width of [1920, 1440, 1280, 1024, 768, 390, 360]) {
        const {context, page} = await openPage(browser, width);
        await page.goto(base);
        await page.locator('#open-create-modal-btn').waitFor();
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `overflow at ${width}`);
        if (width === 1440) await snap(page, 'landing-after');
        await page.waitForTimeout(350);
        metrics.push({width, ...(await page.evaluate(() => window.arenaMetrics))});
        await context.close();
      }
      await game(browser, 1440);
      await game(browser, 390);
      assert.deepEqual(errors, []);
      console.log(JSON.stringify(metrics, null, 2));
    } finally {
      await browser.close();
    }
  } finally {
    primary.kill();
    comparison?.kill();
  }
}

run().catch(error => { console.error(error, errors); process.exitCode = 1; });
