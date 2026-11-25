(function (root) {
  'use strict';

  function normalizeKey(value) {
    return String(value || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
  }

  function avatarFallback(characterId, characterName) {
    const slug = characterId || normalizeKey(characterName) || 'char';
    return `/api/avatar/${encodeURIComponent(slug)}`;
  }

  function buildPoolEntry(characterId, characterName, franchise, category, imageUrl) {
    return {
      character_id: characterId,
      character_name: characterName,
      franchise: franchise,
      category: category,
      image_url: imageUrl || avatarFallback(characterId, characterName),
      fallback_image_url: avatarFallback(characterId, characterName),
      performance_score_reference: 'power_rating'
    };
  }

  const MVP_CHARACTER_CONFIG = {
    categories: {
      anime: [
        buildPoolEntry('monkey_d_luffy', 'Monkey D. Luffy', 'one_piece', 'anime'),
        buildPoolEntry('naruto_uzumaki', 'Naruto Uzumaki', 'naruto', 'anime'),
        buildPoolEntry('goku', 'Goku', 'dragon_ball', 'anime'),
        buildPoolEntry('ichigo_kurosaki', 'Ichigo Kurosaki', 'bleach', 'anime'),
        buildPoolEntry('satoru_gojo', 'Satoru Gojo', 'jujutsu_kaisen', 'anime')
      ],
      marvel: [
        buildPoolEntry('spider_man', 'Spider-Man', 'marvel', 'marvel'),
        buildPoolEntry('iron_man', 'Iron Man', 'marvel', 'marvel'),
        buildPoolEntry('thor', 'Thor', 'marvel', 'marvel'),
        buildPoolEntry('captain_america', 'Captain America', 'marvel', 'marvel'),
        buildPoolEntry('doctor_strange', 'Doctor Strange', 'marvel', 'marvel')
      ],
      pokemon: [
        buildPoolEntry('charizard', 'Charizard', 'pokemon', 'pokemon'),
        buildPoolEntry('pikachu', 'Pikachu', 'pokemon', 'pokemon'),
        buildPoolEntry('lucario', 'Lucario', 'pokemon', 'pokemon'),
        buildPoolEntry('greninja', 'Greninja', 'pokemon', 'pokemon'),
        buildPoolEntry('gengar', 'Gengar', 'pokemon', 'pokemon')
      ]
    }
  };

  function getCharacterFranchiseId(charObj) {
    if (!charObj) return 'pokemon';
    if (charObj.anime_id) return normalizeKey(charObj.anime_id);
    if (charObj.franchise) return normalizeKey(charObj.franchise);
    if (charObj.anime_name) {
      const nameNorm = normalizeKey(charObj.anime_name);
      if (nameNorm === 'pok_mon' || nameNorm === 'pokemon') return 'pokemon';
      return nameNorm;
    }
    return 'pokemon';
  }

  function inferCategoryFromFranchise(franchiseId) {
    const f = normalizeKey(franchiseId);
    if (f === 'pokemon') return 'pokemon';
    if (f === 'marvel' || f === 'mcu' || f === 'avengers') return 'marvel';
    return 'anime';
  }

  function detectRoomCategory(roomState) {
    const mode = roomState && roomState.anime_mode ? String(roomState.anime_mode).toLowerCase() : 'all';
    const selected = Array.isArray(roomState && roomState.selected_anime)
      ? roomState.selected_anime.map(normalizeKey).filter(Boolean)
      : [];

    if (mode === 'pokemon') {
      return { mode: 'pokemon', category: 'pokemon', allowedFranchises: ['pokemon'] };
    }
    if ((mode === 'single' || mode === 'multiple') && selected.length > 0) {
      const allPokemon = selected.every(f => f === 'pokemon');
      const allMarvel = selected.every(f => inferCategoryFromFranchise(f) === 'marvel');
      const category = allPokemon ? 'pokemon' : (allMarvel ? 'marvel' : 'anime');
      return { mode: mode, category: category, allowedFranchises: selected };
    }
    return { mode: mode || 'all', category: 'anime', allowedFranchises: null };
  }

  function isCharacterEligible(charObj, categoryInfo) {
    const franchiseId = getCharacterFranchiseId(charObj);
    if (categoryInfo.allowedFranchises && categoryInfo.allowedFranchises.length > 0) {
      return categoryInfo.allowedFranchises.includes(franchiseId);
    }
    if (categoryInfo.category === 'pokemon') {
      return franchiseId === 'pokemon';
    }
    if (categoryInfo.category === 'marvel') {
      return inferCategoryFromFranchise(franchiseId) === 'marvel';
    }
    // For 'all' anime mode, any franchise in the room is eligible
    return true;
  }

  function compareCharactersDeterministic(a, b) {
    const prA = Number(a.power_rating || 0);
    const prB = Number(b.power_rating || 0);
    if (prB !== prA) return prB - prA;

    const bstA = Number(a.bst || 0);
    const bstB = Number(b.bst || 0);
    if (bstB !== bstA) return bstB - bstA;

    const hpA = Number((a.stats && a.stats.hp) || 0);
    const hpB = Number((b.stats && b.stats.hp) || 0);
    if (hpB !== hpA) return hpB - hpA;

    const nameA = String(a.name || a.character_name || '');
    const nameB = String(b.name || b.character_name || '');
    return nameA.localeCompare(nameB);
  }

  function findPoolMatch(charObj, pool) {
    const cid = normalizeKey(charObj.id || charObj.character_id);
    const cname = normalizeKey(charObj.name || charObj.character_name);
    return pool.find(p => normalizeKey(p.character_id) === cid || normalizeKey(p.character_name) === cname) || null;
  }

  function resolveMvpCharacter(roomState, leaderboard) {
    const categoryInfo = detectRoomCategory(roomState || {});
    const pool = MVP_CHARACTER_CONFIG.categories[categoryInfo.category] || MVP_CHARACTER_CONFIG.categories.anime;
    const winner = Array.isArray(leaderboard) && leaderboard.length > 0 ? leaderboard[0] : null;
    const roster = winner && Array.isArray(winner.team) ? winner.team : [];

    const eligibleRoster = roster.filter(c => isCharacterEligible(c, categoryInfo));

    if (eligibleRoster.length > 0) {
      const sorted = eligibleRoster.slice().sort(compareCharactersDeterministic);
      const topChar = sorted[0];
      const poolMatch = findPoolMatch(topChar, pool);
      const charId = topChar.id || (poolMatch ? poolMatch.character_id : normalizeKey(topChar.name));
      const fallbackUrl = (poolMatch && poolMatch.fallback_image_url) || avatarFallback(charId, topChar.name);
      const imageUrl = topChar.image || (poolMatch && poolMatch.image_url) || fallbackUrl;

      return {
        character_id: charId,
        character_name: topChar.name || (poolMatch ? poolMatch.character_name : 'Champion'),
        franchise: topChar.anime_name || getCharacterFranchiseId(topChar),
        franchise_id: getCharacterFranchiseId(topChar),
        category: categoryInfo.category,
        image_url: imageUrl,
        fallback_image_url: fallbackUrl,
        power_rating: Number(topChar.power_rating || 0),
        bst: Number(topChar.bst || 0),
        is_fallback: false,
        winner: winner
      };
    }

    // Graceful deterministic category/franchise fallback for empty or ineligible rosters
    let fallbackEntry = pool[0];
    if (categoryInfo.allowedFranchises && categoryInfo.allowedFranchises.length > 0) {
      const franchiseMatch = pool.find(p => categoryInfo.allowedFranchises.includes(normalizeKey(p.franchise)));
      if (franchiseMatch) {
        fallbackEntry = franchiseMatch;
      } else {
        const fid = categoryInfo.allowedFranchises[0];
        fallbackEntry = buildPoolEntry(fid, fid.replace(/_/g, ' ').replace(/\b\w/g, m => m.toUpperCase()), fid, categoryInfo.category);
      }
    }

    return {
      character_id: fallbackEntry.character_id,
      character_name: fallbackEntry.character_name,
      franchise: fallbackEntry.franchise,
      franchise_id: normalizeKey(fallbackEntry.franchise),
      category: fallbackEntry.category,
      image_url: fallbackEntry.image_url,
      fallback_image_url: fallbackEntry.fallback_image_url,
      power_rating: 0,
      bst: 0,
      is_fallback: true,
      winner: winner
    };
  }

  const api = {
    MVP_CHARACTER_CONFIG: MVP_CHARACTER_CONFIG,
    detectRoomCategory: detectRoomCategory,
    resolveMvpCharacter: resolveMvpCharacter
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.MVP_CHARACTER_CONFIG = MVP_CHARACTER_CONFIG;
    root.resolveMvpCharacter = resolveMvpCharacter;
  }
})(typeof window !== 'undefined' ? window : globalThis);
