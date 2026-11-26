const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const PUBLIC_DIR = path.join(ROOT, 'public');

// Minimal browser-like globals for isolated testing of auction-image-handler.js
function loadImageHandlerModule() {
  const store = new Map();
  global.window = {
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
  };
  global.document = {
    addEventListener: () => {},
    getElementById: () => null,
  };
  delete require.cache[require.resolve(path.join(PUBLIC_DIR, 'auction-image-handler.js'))];
  require(path.join(PUBLIC_DIR, 'auction-image-handler.js'));
  return { window: global.window, store };
}

(async function run() {
  const { window } = loadImageHandlerModule();
  assert.strictEqual(window.AUCTION_IMAGE_OVERRIDE_ENABLED, true, 'Default image override should be true');

  const charizard = { id: 'pkmn_6', national_id: 6, anime_id: 'pokemon', name: 'Charizard', image: '/assets/pokemon/6.png' };
  const luffy = { id: 'one_piece_luffy', anime_id: 'one_piece', name: 'Luffy', image: '/assets/anime/luffy.png' };
  const spidey = { id: 'marvel_spiderman', anime_id: 'marvel', name: 'Spider-Man', image: '/assets/marvel/spiderman.jpg' };

  // 1-3. Pokémon, Anime, Marvel auction card image replacement + local file existence
  const pkmnImg = window.getAuctionDisplayImage(charizard);
  const animeImg = window.getAuctionDisplayImage(luffy);
  const marvelImg = window.getAuctionDisplayImage(spidey);

  assert.strictEqual(pkmnImg, '/assets/auction_display/pokemon/charizard_display.svg');
  assert.strictEqual(animeImg, '/assets/auction_display/anime/luffy_display.svg');
  assert.strictEqual(marvelImg, '/assets/auction_display/marvel/spiderman_display.svg');

  const allDisplayAssets = [
    '/assets/auction_display/pokemon/charizard_display.svg',
    '/assets/auction_display/pokemon/pikachu_display.svg',
    '/assets/auction_display/pokemon/pokemon_default_display.svg',
    '/assets/auction_display/anime/luffy_display.svg',
    '/assets/auction_display/anime/naruto_display.svg',
    '/assets/auction_display/anime/anime_default_display.svg',
    '/assets/auction_display/marvel/spiderman_display.svg',
    '/assets/auction_display/marvel/ironman_display.svg',
    '/assets/auction_display/marvel/marvel_default_display.svg',
  ];
  for (const rel of allDisplayAssets) {
    const diskPath = path.join(PUBLIC_DIR, rel.replace(/^\//, ''));
    assert.ok(fs.existsSync(diskPath), `Missing display asset on disk: ${diskPath}`);
  }

  // 4. Character names, IDs, and original image fields remain completely unchanged
  assert.strictEqual(charizard.name, 'Charizard');
  assert.strictEqual(charizard.id, 'pkmn_6');
  assert.strictEqual(charizard.image, '/assets/pokemon/6.png');
  assert.strictEqual(luffy.name, 'Luffy');
  assert.strictEqual(luffy.id, 'one_piece_luffy');
  assert.strictEqual(luffy.image, '/assets/anime/luffy.png');
  assert.strictEqual(spidey.name, 'Spider-Man');
  assert.strictEqual(spidey.id, 'marvel_spiderman');
  assert.strictEqual(spidey.image, '/assets/marvel/spiderman.jpg');

  // 5. Isolation check: only renderAuctionCard in game.js uses getAuctionDisplayImage
  const gameJs = fs.readFileSync(path.join(PUBLIC_DIR, 'game.js'), 'utf8');
  const matches = gameJs.match(/getAuctionDisplayImage/g) || [];
  assert.strictEqual(matches.length, 2, 'getAuctionDisplayImage should only appear in the renderAuctionCard guard & call');
  const renderBlock = gameJs.slice(gameJs.indexOf('function renderAuctionCard'), gameJs.indexOf('function updateTimerDisplay'));
  assert.strictEqual((renderBlock.match(/getAuctionDisplayImage/g) || []).length, 2, 'Both references must be inside renderAuctionCard');

  // 6. Turning image override OFF restores original auction images
  window.setAuctionImageOverride(false);
  assert.strictEqual(window.AUCTION_IMAGE_OVERRIDE_ENABLED, false);
  assert.strictEqual(window.getAuctionDisplayImage(charizard), '/assets/pokemon/6.png');
  assert.strictEqual(window.getAuctionDisplayImage(luffy), '/assets/anime/luffy.png');
  assert.strictEqual(window.getAuctionDisplayImage(spidey), '/assets/marvel/spiderman.jpg');

  // 7. Restarting the server automatically disables image override
  const fresh = loadImageHandlerModule().window;
  assert.strictEqual(fresh.AUCTION_IMAGE_OVERRIDE_ENABLED, true);
  await fresh.syncAuctionImageOverrideWithServerBoot(async () => ({
    ok: true,
    json: async () => ({ server_boot_id: 'boot_1001' }),
  }));
  assert.strictEqual(fresh.AUCTION_IMAGE_OVERRIDE_ENABLED, true, 'First boot keeps image override enabled');

  // Simulate server restart (new server_boot_id)
  await fresh.syncAuctionImageOverrideWithServerBoot(async () => ({
    ok: true,
    json: async () => ({ server_boot_id: 'boot_2002' }),
  }));
  assert.strictEqual(fresh.AUCTION_IMAGE_OVERRIDE_ENABLED, false, 'Server restart must auto-disable image override');
  assert.strictEqual(fresh.getAuctionDisplayImage(charizard), '/assets/pokemon/6.png');

  console.log('ALL 7 AUCTION IMAGE HANDLER TESTS PASSED');
})();
