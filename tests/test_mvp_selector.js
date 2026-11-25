const assert = require('assert');
const { MVP_CHARACTER_CONFIG, resolveMvpCharacter } = require('../public/mvp-config.js');

// 1. Anime room -> Winning trainer's best-performing eligible anime character is displayed
{
  const roomState = { anime_mode: 'all', selected_anime: [] };
  const leaderboard = [{
    session_id: 'p1',
    name: 'Trainer Red',
    team_power: 195,
    team: [
      { id: 'naruto_uzumaki', name: 'Naruto Uzumaki', anime_id: 'naruto', anime_name: 'Naruto', image: '/img/naruto.png', power_rating: 92, bst: 620, stats: { hp: 100 } },
      { id: 'satoru_gojo', name: 'Satoru Gojo', anime_id: 'jujutsu_kaisen', anime_name: 'Jujutsu Kaisen', image: '/img/gojo.png', power_rating: 98, bst: 680, stats: { hp: 110 } }
    ]
  }];
  const mvp = resolveMvpCharacter(roomState, leaderboard);
  assert.strictEqual(mvp.category, 'anime');
  assert.strictEqual(mvp.character_name, 'Satoru Gojo');
  assert.strictEqual(mvp.image_url, '/img/gojo.png');
  assert.strictEqual(mvp.is_fallback, false);
}

// 2. Marvel room -> Winning trainer's best-performing eligible Marvel character is displayed
{
  const roomState = { anime_mode: 'single', selected_anime: ['marvel'] };
  const leaderboard = [{
    session_id: 'p1',
    name: 'Tony',
    team_power: 185,
    team: [
      { id: 'spider_man', name: 'Spider-Man', anime_id: 'marvel', anime_name: 'Marvel', image: '/img/spidey.png', power_rating: 89, bst: 580, stats: { hp: 90 } },
      { id: 'thor', name: 'Thor', anime_id: 'marvel', anime_name: 'Marvel', image: '/img/thor.png', power_rating: 96, bst: 660, stats: { hp: 120 } }
    ]
  }];
  const mvp = resolveMvpCharacter(roomState, leaderboard);
  assert.strictEqual(mvp.category, 'marvel');
  assert.strictEqual(mvp.character_name, 'Thor');
  assert.strictEqual(mvp.image_url, '/img/thor.png');
}

// 3. Pokémon room -> Winning trainer's best-performing eligible Pokémon is displayed
{
  const roomState = { anime_mode: 'pokemon', selected_anime: [] };
  const leaderboard = [{
    session_id: 'p1',
    name: 'Ash',
    team_power: 180,
    team: [
      { id: 'pikachu', name: 'Pikachu', anime_id: 'pokemon', anime_name: 'Pokémon', image: '/img/pikachu.png', power_rating: 75, bst: 320, stats: { hp: 35 } },
      { id: 'charizard', name: 'Charizard', anime_id: 'pokemon', anime_name: 'Pokémon', image: '/img/charizard.png', power_rating: 91, bst: 534, stats: { hp: 78 } }
    ]
  }];
  const mvp = resolveMvpCharacter(roomState, leaderboard);
  assert.strictEqual(mvp.category, 'pokemon');
  assert.strictEqual(mvp.character_name, 'Charizard');
  assert.strictEqual(mvp.image_url, '/img/charizard.png');
}

// 4. Single Anime room -> MVP belongs to the selected anime franchise
{
  const roomState = { anime_mode: 'single', selected_anime: ['bleach'] };
  const leaderboard = [{
    session_id: 'p1',
    name: 'IchigoFan',
    team_power: 99,
    team: [
      { id: 'goku', name: 'Goku', anime_id: 'dragon_ball', anime_name: 'Dragon Ball', image: '/img/goku.png', power_rating: 99, bst: 700 },
      { id: 'ichigo_kurosaki', name: 'Ichigo Kurosaki', anime_id: 'bleach', anime_name: 'Bleach', image: '/img/ichigo.png', power_rating: 94, bst: 640 }
    ]
  }];
  const mvp = resolveMvpCharacter(roomState, leaderboard);
  assert.strictEqual(mvp.franchise_id, 'bleach');
  assert.strictEqual(mvp.character_name, 'Ichigo Kurosaki');
}

// 5. Selected Anime room -> MVP belongs to one of the selected franchises
{
  const roomState = { anime_mode: 'multiple', selected_anime: ['naruto', 'one_piece'] };
  const leaderboard = [{
    session_id: 'p1',
    name: 'PirateNinja',
    team_power: 190,
    team: [
      { id: 'goku', name: 'Goku', anime_id: 'dragon_ball', anime_name: 'Dragon Ball', image: '/img/goku.png', power_rating: 99, bst: 700 },
      { id: 'monkey_d_luffy', name: 'Monkey D. Luffy', anime_id: 'one_piece', anime_name: 'One Piece', image: '/img/luffy.png', power_rating: 95, bst: 650 }
    ]
  }];
  const mvp = resolveMvpCharacter(roomState, leaderboard);
  assert.ok(['naruto', 'one_piece'].includes(mvp.franchise_id));
  assert.strictEqual(mvp.character_name, 'Monkey D. Luffy');
}

// 6. Winning trainer has an empty roster -> Show a graceful fallback
{
  const mvpPokemon = resolveMvpCharacter({ anime_mode: 'pokemon' }, [{ session_id: 'p1', name: 'Red', team: [] }]);
  assert.strictEqual(mvpPokemon.category, 'pokemon');
  assert.strictEqual(mvpPokemon.is_fallback, true);
  assert.strictEqual(mvpPokemon.character_name, MVP_CHARACTER_CONFIG.categories.pokemon[0].character_name);

  const mvpMarvel = resolveMvpCharacter({ anime_mode: 'single', selected_anime: ['marvel'] }, [{ session_id: 'p1', name: 'Nick', team: [] }]);
  assert.strictEqual(mvpMarvel.category, 'marvel');
  assert.strictEqual(mvpMarvel.is_fallback, true);
  assert.strictEqual(mvpMarvel.character_name, MVP_CHARACTER_CONFIG.categories.marvel[0].character_name);
}

// 7. Character artwork is missing -> Show fallback artwork
{
  const roomState = { anime_mode: 'pokemon' };
  const leaderboard = [{
    session_id: 'p1',
    name: 'Red',
    team: [{ id: 'lucario', name: 'Lucario', anime_id: 'pokemon', image: '', power_rating: 88, bst: 525 }]
  }];
  const mvp = resolveMvpCharacter(roomState, leaderboard);
  assert.strictEqual(mvp.image_url, '/api/avatar/lucario');
  assert.strictEqual(mvp.fallback_image_url, '/api/avatar/lucario');
}

// 8. Two characters have equal performance -> Apply deterministic tie-breaking rule
{
  const roomState = { anime_mode: 'anime' };
  const leaderboard = [{
    session_id: 'p1',
    name: 'TieTester',
    team: [
      { id: 'zoro', name: 'Zoro', anime_id: 'one_piece', power_rating: 90, bst: 600, stats: { hp: 90 } },
      { id: 'ace', name: 'Ace', anime_id: 'one_piece', power_rating: 90, bst: 600, stats: { hp: 90 } }
    ]
  }];
  const mvp = resolveMvpCharacter(roomState, leaderboard);
  assert.strictEqual(mvp.character_name, 'Ace');
}

console.log('ALL 8 MVP TESTS PASSED');
