/**
 * TEMPORARY AUCTION IMAGE OVERRIDE HANDLER
 * ========================================
 * Isolated frontend-only image override for the active auction card ONLY.
 * Does NOT modify character names, IDs, databases, stats, prices, roster,
 * battle, results, lobby, or profile images.
 */
(function () {
  'use strict';

  // Easily accessible configuration flag:
  window.AUCTION_IMAGE_OVERRIDE_ENABLED = true;

  const STORAGE_OFF_KEY = 'pkmn_auction_image_override_off';
  const STORAGE_BOOT_KEY = 'pkmn_auction_image_override_boot_id';

  const DISPLAY_IMAGE_MAP = {
    pokemon: {
      charizard: '/assets/auction_display/pokemon/charizard_display.svg',
      pikachu: '/assets/auction_display/pokemon/pikachu_display.svg',
      _default: '/assets/auction_display/pokemon/pokemon_default_display.svg',
    },
    anime: {
      luffy: '/assets/auction_display/anime/luffy_display.svg',
      'monkey d. luffy': '/assets/auction_display/anime/luffy_display.svg',
      'luffy monkey': '/assets/auction_display/anime/luffy_display.svg',
      naruto: '/assets/auction_display/anime/naruto_display.svg',
      'naruto uzumaki': '/assets/auction_display/anime/naruto_display.svg',
      _default: '/assets/auction_display/anime/anime_default_display.svg',
    },
    marvel: {
      'spider-man': '/assets/auction_display/marvel/spiderman_display.svg',
      spiderman: '/assets/auction_display/marvel/spiderman_display.svg',
      'peter parker': '/assets/auction_display/marvel/spiderman_display.svg',
      'iron man': '/assets/auction_display/marvel/ironman_display.svg',
      'tony stark': '/assets/auction_display/marvel/ironman_display.svg',
      _default: '/assets/auction_display/marvel/marvel_default_display.svg',
    },
  };

  function detectUniverse(character) {
    if (!character || typeof character !== 'object') return 'pokemon';
    const animeId = String(character.anime_id || '').toLowerCase();
    const charId = String(character.id || '').toLowerCase();
    if (animeId === 'marvel' || charId.startsWith('marvel_')) return 'marvel';
    if (animeId === 'pokemon' || charId.startsWith('pkmn_') || 'national_id' in character) return 'pokemon';
    if (animeId) return 'anime';
    return 'pokemon';
  }

  function resolveDisplayAsset(character) {
    const universe = detectUniverse(character);
    const table = DISPLAY_IMAGE_MAP[universe] || DISPLAY_IMAGE_MAP.pokemon;
    const rawName = String((character && character.name) || '').trim().toLowerCase();
    for (const [key, path] of Object.entries(table)) {
      if (key === '_default') continue;
      if (rawName === key || rawName.includes(key)) {
        return path;
      }
    }
    return table._default;
  }

  function refreshActiveAuctionCardIfNeeded() {
    if (
      typeof window.renderAuctionCard === 'function' &&
      window.gameState &&
      window.gameState.lastAuctionCharacter
    ) {
      window.renderAuctionCard(window.gameState.lastAuctionCharacter);
    }
    const pill = document.getElementById('auction-image-override-off-btn');
    if (pill) {
      pill.style.display = window.AUCTION_IMAGE_OVERRIDE_ENABLED ? 'inline-flex' : 'none';
    }
  }

  // Respect manual OFF switch across reloads in the same server run
  try {
    if (typeof window.localStorage !== 'undefined' && window.localStorage.getItem(STORAGE_OFF_KEY) === '1') {
      window.AUCTION_IMAGE_OVERRIDE_ENABLED = false;
    }
  } catch (_) {}

  // Public override helper called ONLY by renderAuctionCard()
  window.getAuctionDisplayImage = function getAuctionDisplayImage(character) {
    if (!character) return '';
    if (!window.AUCTION_IMAGE_OVERRIDE_ENABLED) {
      return character.image || '';
    }
    return resolveDisplayAsset(character) || character.image || '';
  };

  // Manual ON/OFF switch
  window.setAuctionImageOverride = function setAuctionImageOverride(enabled) {
    window.AUCTION_IMAGE_OVERRIDE_ENABLED = !!enabled;
    try {
      if (typeof window.localStorage !== 'undefined') {
        if (window.AUCTION_IMAGE_OVERRIDE_ENABLED) {
          window.localStorage.removeItem(STORAGE_OFF_KEY);
        } else {
          window.localStorage.setItem(STORAGE_OFF_KEY, '1');
        }
      }
    } catch (_) {}
    refreshActiveAuctionCardIfNeeded();
    return window.AUCTION_IMAGE_OVERRIDE_ENABLED;
  };

  // Automatic restoration when server restarts (detected via server_boot_id change)
  window.syncAuctionImageOverrideWithServerBoot = async function syncAuctionImageOverrideWithServerBoot(fetchFn) {
    const doFetch = fetchFn || (typeof window.fetch === 'function' ? window.fetch.bind(window) : null);
    if (!doFetch) return window.AUCTION_IMAGE_OVERRIDE_ENABLED;
    try {
      const resp = await doFetch('/api/stats', { cache: 'no-store' });
      if (!resp || !resp.ok) return window.AUCTION_IMAGE_OVERRIDE_ENABLED;
      const stats = await resp.json();
      const bootId = stats && stats.server_boot_id ? String(stats.server_boot_id) : '';
      if (!bootId) return window.AUCTION_IMAGE_OVERRIDE_ENABLED;

      if (typeof window.localStorage !== 'undefined') {
        const savedBootId = window.localStorage.getItem(STORAGE_BOOT_KEY);
        if (!savedBootId) {
          window.localStorage.setItem(STORAGE_BOOT_KEY, bootId);
        } else if (savedBootId !== bootId) {
          // Server restarted -> automatically disable image override
          window.AUCTION_IMAGE_OVERRIDE_ENABLED = false;
          window.localStorage.setItem(STORAGE_OFF_KEY, '1');
          window.localStorage.setItem(STORAGE_BOOT_KEY, bootId);
          refreshActiveAuctionCardIfNeeded();
        }
      }
    } catch (_) {}
    return window.AUCTION_IMAGE_OVERRIDE_ENABLED;
  };

  if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
      window.syncAuctionImageOverrideWithServerBoot();
      const btn = document.getElementById('auction-image-override-off-btn');
      if (btn) {
        btn.style.display = window.AUCTION_IMAGE_OVERRIDE_ENABLED ? 'inline-flex' : 'none';
        btn.addEventListener('click', () => {
          window.setAuctionImageOverride(false);
        });
      }
    });
  }
})();
