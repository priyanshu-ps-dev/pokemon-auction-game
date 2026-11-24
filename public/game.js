/**
 * Pokemon Auction Arena: Real-Time Multiplayer Client Controller
 * ==============================================================
 * Handles WebSocket communication, room-specific purse management,
 * authoritative timer rendering, flexible bidding (any valid amount),
 * hidden stats during bidding, and dramatic final stats reveal.
 */

// Global Game State (per-tab sessionStorage prevents multi-tab sessionId collisions while surviving F5 refresh)
const _savedSessionId = sessionStorage.getItem('pkmn_auction_session_id') || ('sess_' + Math.random().toString(36).substring(2, 10));
sessionStorage.setItem('pkmn_auction_session_id', _savedSessionId);

const gameState = {
  ws: null,
  sessionId: _savedSessionId,
  roomCode: sessionStorage.getItem('pkmn_auction_room_code') || null,
  isHost: false,
  isWithdrawn: false,
  myName: localStorage.getItem('pkmn_auction_name') || 'Trainer Red',
  myAvatar: localStorage.getItem('pkmn_auction_avatar') || 'red',
  soundEnabled: true,
  roomState: null,
  timerInterval: null
};

// 12 Trainer Avatars
const TRAINER_AVATARS = [
  { id: 'red', name: 'Red', color: '#ef4444', icon: '🧢' },
  { id: 'blue', name: 'Blue', color: '#3b82f6', icon: '🕶️' },
  { id: 'leaf', name: 'Leaf', color: '#10b981', icon: '👒' },
  { id: 'ash', name: 'Ash', color: '#f59e0b', icon: '⚡' },
  { id: 'cynthia', name: 'Cynthia', color: '#8b5cf6', icon: '🐉' },
  { id: 'steven', name: 'Steven', color: '#06b6d4', icon: '💎' },
  { id: 'brendan', name: 'Brendan', color: '#ec4899', icon: '🎒' },
  { id: 'may', name: 'May', color: '#f97316', icon: '🎀' },
  { id: 'ethan', name: 'Ethan', color: '#eab308', icon: '🎧' },
  { id: 'dawn', name: 'Dawn', color: '#0284c7', icon: '🧣' },
  { id: 'leon', name: 'Leon', color: '#6366f1', icon: '👑' },
  { id: 'lyra', name: 'Lyra', color: '#84cc16', icon: '🌟' }
];

// Web Audio API Synthesizer
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

function playTone(freq, type, duration, delay = 0, gainLevel = 0.15) {
  if (!gameState.soundEnabled) return;
  try {
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, audioCtx.currentTime + delay);
    gain.gain.setValueAtTime(gainLevel, audioCtx.currentTime + delay);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + delay + duration);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(audioCtx.currentTime + delay);
    osc.stop(audioCtx.currentTime + delay + duration);
  } catch (e) {}
}

const soundFX = {
  bid() {
    playTone(587.33, 'sine', 0.08, 0, 0.15); // D5
    playTone(880.00, 'sine', 0.15, 0.08, 0.2); // A5
  },
  tick() {
    playTone(400, 'triangle', 0.03, 0, 0.08);
  },
  sold() {
    playTone(150, 'sawtooth', 0.12, 0, 0.3);
    playTone(80, 'sine', 0.3, 0.05, 0.4);
  },
  unsold() {
    playTone(280, 'sawtooth', 0.2, 0, 0.15);
    playTone(220, 'sawtooth', 0.3, 0.15, 0.15);
  },
  victory() {
    [523.25, 659.25, 783.99, 1046.50].forEach((freq, idx) => {
      playTone(freq, 'triangle', 0.35, idx * 0.12, 0.2);
    });
  }
};

// WebSocket Controller
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  gameState.ws = new WebSocket(wsUrl);

  gameState.ws.onopen = () => {
    console.log('[WS] Connected to Auction Server');
    const savedRoom = sessionStorage.getItem('pkmn_auction_room_code');
    if (savedRoom) {
      console.log(`[WS] Auto-rejoining room ${savedRoom} with session ${gameState.sessionId}`);
      sendAction('join_room', {
        room_code: savedRoom,
        name: gameState.myName,
        avatar: gameState.myAvatar
      });
    }
  };

  gameState.ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleServerMessage(msg.type, msg.data);
    } catch (e) {
      console.error('[WS] Parse error', e);
    }
  };

  gameState.ws.onclose = () => {
    console.warn('[WS] Disconnected, attempting reconnect in 2s...');
    setTimeout(connectWebSocket, 2000);
  };
}

// Dispatch Incoming Server Messages
function handleServerMessage(type, data) {
  switch (type) {
    case 'room_joined': {
      gameState.roomCode = data.room_code;
      gameState.isHost = data.is_host;
      gameState.roomState = data.room_state;
      sessionStorage.setItem('pkmn_auction_room_code', data.room_code);
      const rs = data.room_state || {};
      const status = rs.status || 'LOBBY';
      if (status === 'AUCTION' || status === 'SHOWCASE') {
        switchArenaScreen('arena-stage');
        updateStageUI(rs);
        if (rs.current_pokemon) {
          renderAuctionCard(rs.current_pokemon);
        }
        updateBidStatus(rs.current_bid || 0, rs.highest_bidder_id || null, rs.highest_bidder_name || null, null);
        updateTimerDisplay(rs.timer_seconds_left != null ? rs.timer_seconds_left : 15);
      } else if (status === 'BATTLE') {
        switchArenaScreen('arena-battle');
        updateStageUI(rs);
      } else if (status === 'GAME_OVER') {
        switchArenaScreen('arena-results');
      } else {
        updateLobbyUI(rs);
        switchArenaScreen('arena-lobby');
      }
      break;
    }

    case 'room_state':
      gameState.roomState = data;
      if (data.status === 'LOBBY') {
        updateLobbyUI(data);
      } else if (data.status === 'AUCTION' || data.status === 'SHOWCASE') {
        updateStageUI(data);
      }
      break;

    case 'auction_started':
      soundFX.bid();
      switchArenaScreen('arena-stage');
      const skipBadge = document.getElementById('skip-status-badge');
      if (skipBadge) skipBadge.style.display = 'none';
      const skipBtn = document.getElementById('btn-skip-character');
      if (skipBtn) skipBtn.disabled = gameState.isWithdrawn;
      updateStageUI(data.room_state);
      renderAuctionCard(data.pokemon);
      addStageLog(`🔔 Round Started! <strong>${data.pokemon.name}</strong> is up for auction!`, 'info');
      break;

    case 'character_skipped':
      if (data.session_id === gameState.sessionId) {
        const badge = document.getElementById('skip-status-badge');
        if (badge) badge.style.display = 'inline-block';
        const skipBtn = document.getElementById('btn-skip-character');
        if (skipBtn) skipBtn.disabled = true;
        document.querySelectorAll('.btn-quick-bid').forEach(b => b.disabled = true);
        const subBtn = document.getElementById('submit-bid-btn');
        if (subBtn) {
          subBtn.disabled = true;
          subBtn.textContent = 'SKIPPED BY YOU';
        }
        const cInp = document.getElementById('custom-bid-input');
        if (cInp) cInp.disabled = true;
        addStageLog(`⏭️ You skipped this character.`, 'alert');
      } else {
        addStageLog(`⏭️ <strong>${escapeHtml(data.player_name)}</strong> skipped this character.`, 'info');
      }
      if (data.room_state) updateStageUI(data.room_state);
      break;

    case 'all_skipped_round_ended':
      soundFX.unsold();
      addStageLog(`⏭️ <strong>All eligible trainers skipped!</strong> Concluding round early.`, 'unsold');
      break;

    case 'player_withdrawn':
      addStageLog(`🚪 <strong>${escapeHtml(data.player_name)}</strong> withdrew from the match.`, 'alert');
      if (data.session_id === gameState.sessionId) {
        gameState.isWithdrawn = true;
        document.querySelectorAll('.btn-quick-bid').forEach(b => b.disabled = true);
        const subBtn = document.getElementById('submit-bid-btn');
        if (subBtn) {
          subBtn.disabled = true;
          subBtn.textContent = 'WITHDRAWN FROM MATCH';
        }
        const cInp = document.getElementById('custom-bid-input');
        if (cInp) cInp.disabled = true;
        const skipBtn = document.getElementById('btn-skip-character');
        if (skipBtn) skipBtn.disabled = true;
        addStageLog(`⚠️ You have withdrawn from the match. You will observe remaining rounds.`, 'alert');
      }
      if (data.room_state) updateStageUI(data.room_state);
      break;

    case 'host_transferred':
      addStageLog(`👑 ${escapeHtml(data.message)}`, 'info');
      if (data.new_host_id === gameState.sessionId) {
        gameState.isHost = true;
        addStageLog(`👑 You are now the room host!`, 'won');
      }
      break;

    case 'rematch_requested':
      showRematchModal(data);
      break;

    case 'rematch_vote_update':
      updateRematchTally(data);
      break;

    case 'rematch_declined':
      hideRematchModal();
      alert(data.message || 'Rematch was declined.');
      break;

    case 'rematch_started':
      hideRematchModal();
      gameState.isWithdrawn = false;
      gameState.currentMatchId = data.match_id || null;
      resetBattleUI();
      const stageLog = document.getElementById('stage-log-list');
      if (stageLog) stageLog.innerHTML = '';
      addStageLog(`🔄 Rematch started! Match #${data.match_number}`, 'won');
      switchArenaScreen('arena-stage');
      if (data.room_state) updateStageUI(data.room_state);
      break;

    case 'room_left':
      gameState.roomCode = null;
      gameState.isHost = false;
      gameState.isWithdrawn = false;
      sessionStorage.removeItem('pkmn_auction_room_code');
      switchArenaScreen('arena-setup');
      break;

    case 'auction_tick': {
      if (data.room_state) {
        gameState.roomState = data.room_state;
      } else if (gameState.roomState) {
        gameState.roomState.current_bid = data.current_bid;
        gameState.roomState.highest_bidder_id = data.highest_bidder_id;
        gameState.roomState.highest_bidder_name = data.highest_bidder_name;
        gameState.roomState.timer_seconds_left = data.timer_seconds_left;
      }
      updateTimerDisplay(data.timer_seconds_left);
      updateBidStatus(data.current_bid, data.highest_bidder_id, data.highest_bidder_name, data.highest_bidder_avatar);
      if (gameState.roomState && Array.isArray(gameState.roomState.players)) {
        const me = gameState.roomState.players.find(p => p.session_id === gameState.sessionId);
        if (me) updateBidButtonStates(me, gameState.roomState);
      }
      if (data.timer_seconds_left <= 3 && data.timer_seconds_left > 0) {
        soundFX.tick();
      }
      break;
    }

    case 'bid_success': {
      soundFX.bid();
      if (data.room_state) {
        gameState.roomState = data.room_state;
      } else if (gameState.roomState) {
        gameState.roomState.current_bid = data.current_bid;
        gameState.roomState.highest_bidder_id = data.highest_bidder_id;
        gameState.roomState.highest_bidder_name = data.highest_bidder_name;
        gameState.roomState.timer_seconds_left = data.timer_seconds_left;
      }
      updateBidStatus(data.current_bid, data.highest_bidder_id, data.highest_bidder_name, data.highest_bidder_avatar);
      updateTimerDisplay(data.timer_seconds_left);
      if (gameState.roomState && Array.isArray(gameState.roomState.players)) {
        const me = gameState.roomState.players.find(p => p.session_id === gameState.sessionId);
        if (me) updateBidButtonStates(me, gameState.roomState);
      }
      addStageLog(`₹ <strong>${data.highest_bidder_name}</strong> bid <strong>₹${data.current_bid.toLocaleString()}</strong>! Timer reset!`, 'bid');
      break;
    }

    case 'bid_error':
      showBiddingError(data.message);
      break;

    case 'auction_won':
      soundFX.sold();
      addStageLog(`🏆 SOLD! <strong>${data.winner_name}</strong> won <strong>${data.pokemon.name}</strong> for ₹${data.winning_bid.toLocaleString()}!`, 'won');
      showShowcaseBanner(`SOLD to ${data.winner_name}!`, `Winning Bid: ₹${data.winning_bid.toLocaleString()}`);
      updateStageUI(data.room_state);
      break;

    case 'auction_unsold':
      soundFX.unsold();
      addStageLog(`❌ UNSOLD! No bids placed for <strong>${data.pokemon.name}</strong>. Removed from match.`, 'unsold');
      showShowcaseBanner(`UNSOLD`, `No bids placed. Next Pokémon arriving...`);
      updateStageUI(data.room_state);
      break;

    case 'room_event':
      addStageLog(`📢 ${data.message}`, 'alert');
      break;

    case 'battle_started':
      gameState.currentMatchId = data.match_id || gameState.currentMatchId;
      resetBattleUI();
      switchArenaScreen('arena-battle');
      break;

    case 'battle_progress':
      if (!gameState.battleSkipped) {
        const mc = document.getElementById('battle-match-counter');
        if (mc) mc.textContent = `Match ${data.match_index} / ${data.total_matches}`;
      }
      break;

    case 'battle_results':
      if (data.match_id && gameState.currentMatchId && data.match_id !== gameState.currentMatchId) break;
      gameState.pendingBattleResults = data;
      break;

    case 'battle_turn_prompt':
      if (data.match_id && gameState.currentMatchId && data.match_id !== gameState.currentMatchId) break;
      renderInteractiveTurnPrompt(data);
      break;

    case 'battle_action_ack':
      {
        const st = document.getElementById('battle-turn-status');
        if (st) st.textContent = '✅ Action submitted! Waiting for opponent...';
        document.querySelectorAll('.battle-move-btn, .battle-switch-btn, .battle-transform-btn').forEach(b => { b.disabled = true; });
      }
      break;

    case 'battle_action_error':
      alert(data.message || 'Invalid battle action.');
      break;

    case 'battle_turn_resolved':
      if (data.match_id && gameState.currentMatchId && data.match_id !== gameState.currentMatchId) break;
      if (data.turn_entry) {
        applyResolvedInteractiveTurn(data.turn_entry, data.player_a_name, data.player_b_name);
      }
      break;

    case 'game_over':
      {
        const ctrlPanel = document.getElementById('battle-control-panel');
        if (ctrlPanel) ctrlPanel.style.display = 'none';
        const bResults = data.battle_results || gameState.pendingBattleResults;
        if (bResults && bResults.matches && bResults.matches.length > 0 && !gameState.battleSkipped && gameState.roomState?.battle_control_mode === 'ai_vs_ai') {
          playBattleSequence(bResults, data);
        } else {
          soundFX.victory();
          switchArenaScreen('arena-results');
          renderLeaderboard(data.leaderboard, bResults);
        }
      }
      break;

    case 'chat':
      appendChatMessage(data);
      break;

    case 'error':
      alert(data.message);
      break;
  }
}

// Screen Switcher
function switchArenaScreen(screenId) {
  document.querySelectorAll('.arena-screen').forEach(s => s.classList.remove('active'));
  const target = document.getElementById(screenId);
  if (target) target.classList.add('active');
}

// Initialize Multiplayer Arena UI
function initArena() {
  connectWebSocket();
  setupAvatarPicker();
  setupEventListeners();

  // Load sound setting
  const soundBtn = document.getElementById('sound-toggle-btn');
  soundBtn.addEventListener('click', () => {
    gameState.soundEnabled = !gameState.soundEnabled;
    soundBtn.textContent = gameState.soundEnabled ? '🔊 Sound On' : '🔇 Muted';
    soundBtn.classList.toggle('active', gameState.soundEnabled);
  });

  // Top Nav Tab Switcher (Arena vs Anime Database vs Pokédex)
  const tabArenaBtn = document.getElementById('tab-arena-btn');
  const tabAnimeBtn = document.getElementById('tab-anime-btn');
  const tabPokedexBtn = document.getElementById('tab-pokedex-btn');
  const viewArena = document.getElementById('view-arena');
  const viewAnime = document.getElementById('view-anime');
  const viewPokedex = document.getElementById('view-pokedex');

  function switchTab(activeBtn, activeView) {
    [tabArenaBtn, tabAnimeBtn, tabPokedexBtn].forEach(b => { if (b) b.classList.remove('active'); });
    [viewArena, viewAnime, viewPokedex].forEach(v => { if (v) v.classList.remove('active'); });
    if (activeBtn) activeBtn.classList.add('active');
    if (activeView) activeView.classList.add('active');
  }

  if (tabArenaBtn) {
    tabArenaBtn.addEventListener('click', () => switchTab(tabArenaBtn, viewArena));
  }
  if (tabAnimeBtn) {
    tabAnimeBtn.addEventListener('click', () => {
      switchTab(tabAnimeBtn, viewAnime);
      if (window.animeDatabaseModule && !window.animeDatabaseModule.initialized) {
        window.animeDatabaseModule.init();
      }
    });
  }
  if (tabPokedexBtn) {
    tabPokedexBtn.addEventListener('click', () => switchTab(tabPokedexBtn, viewPokedex));
  }

  // Check URL parameters for direct room invitation (?room=CODE)
  const urlParams = new URLSearchParams(window.location.search);
  const inviteCode = urlParams.get('room');
  if (inviteCode) {
    const code = inviteCode.trim().toUpperCase();
    const subtabJoinBtn = document.getElementById('subtab-join-btn');
    const subtabCreateBtn = document.getElementById('subtab-create-btn');
    const formJoin = document.getElementById('form-join-room');
    const formCreate = document.getElementById('form-create-room');
    const roomInput = document.getElementById('room-code-input');

    if (subtabJoinBtn && formJoin) {
      subtabJoinBtn.classList.add('active');
      if (subtabCreateBtn) subtabCreateBtn.classList.remove('active');
      formJoin.classList.add('active');
      if (formCreate) formCreate.classList.remove('active');
    }
    if (roomInput) {
      roomInput.value = code;
    }
    const heroP = document.querySelector('.setup-hero p');
    if (heroP) {
      heroP.innerHTML = `You've been invited to join Auction Room <strong style="color:#38bdf8; font-size:1.1rem; letter-spacing:1px;">${escapeHtml(code)}</strong>! Choose your Trainer name and join the arena.`;
    }
  }
}

// Avatar Picker
function setupAvatarPicker() {
  const container = document.getElementById('avatar-picker');
  container.innerHTML = '';

  TRAINER_AVATARS.forEach(av => {
    const chip = document.createElement('div');
    chip.className = `avatar-option ${av.id === gameState.myAvatar ? 'selected' : ''}`;
    chip.dataset.avatarId = av.id;
    chip.innerHTML = `
      <div class="avatar-circle" style="background:${av.color};">${av.icon}</div>
      <span class="avatar-label">${av.name}</span>
    `;
    chip.addEventListener('click', () => {
      document.querySelectorAll('.avatar-option').forEach(c => c.classList.remove('selected'));
      chip.classList.add('selected');
      gameState.myAvatar = av.id;
      localStorage.setItem('pkmn_auction_avatar', av.id);
    });
    container.appendChild(chip);
  });
}

// Attach User Interactions
function setupEventListeners() {
  const nameInput = document.getElementById('player-name-input');
  nameInput.value = gameState.myName;
  nameInput.addEventListener('input', (e) => {
    gameState.myName = e.target.value.trim() || 'Trainer Red';
    localStorage.setItem('pkmn_auction_name', gameState.myName);
  });

  // Sub-tabs: Create Room vs Join Room
  const createSubTab = document.getElementById('subtab-create-btn');
  const joinSubTab = document.getElementById('subtab-join-btn');
  const formCreate = document.getElementById('form-create-room');
  const formJoin = document.getElementById('form-join-room');

  createSubTab.addEventListener('click', () => {
    createSubTab.classList.add('active');
    joinSubTab.classList.remove('active');
    formCreate.classList.add('active');
    formJoin.classList.remove('active');
  });

  joinSubTab.addEventListener('click', () => {
    joinSubTab.classList.add('active');
    createSubTab.classList.remove('active');
    formJoin.classList.add('active');
    formCreate.classList.remove('active');
  });

  // Multi-Anime Mode Selection State
  let selectedAnimeMode = 'all';
  const selectedAnimeFranchises = new Set();

  // Mode radio buttons
  document.querySelectorAll('.mode-radio-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.mode-radio-btn').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      selectedAnimeMode = btn.dataset.mode;

      const singleWrapper = document.getElementById('single-anime-wrapper');
      const multiWrapper = document.getElementById('multiple-anime-wrapper');

      singleWrapper.style.display = selectedAnimeMode === 'single' ? 'block' : 'none';
      multiWrapper.style.display = selectedAnimeMode === 'multiple' ? 'block' : 'none';
    });
  });

  // Fetch and populate franchises
  fetch('/api/anime')
    .then(r => r.json())
    .then(franchises => {
      const select = document.getElementById('single-anime-select');
      const chipsList = document.getElementById('franchise-chips-list');
      const adminFilter = document.getElementById('admin-franchise-filter');

      if (select) select.innerHTML = '';
      if (chipsList) chipsList.innerHTML = '';

      franchises.forEach(f => {
        if (select) {
          const opt = document.createElement('option');
          opt.value = f.id;
          opt.textContent = `${f.name} (${f.character_count || 0})`;
          select.appendChild(opt);
        }
        if (adminFilter) {
          const opt = document.createElement('option');
          opt.value = f.id;
          opt.textContent = f.name;
          adminFilter.appendChild(opt);
        }
        if (chipsList) {
          const chip = document.createElement('div');
          chip.className = 'franchise-chip';
          chip.dataset.fid = f.id;
          chip.textContent = f.name;
          chip.addEventListener('click', () => {
            if (selectedAnimeFranchises.has(f.id)) {
              selectedAnimeFranchises.delete(f.id);
              chip.classList.remove('active');
            } else {
              selectedAnimeFranchises.add(f.id);
              chip.classList.add('active');
            }
          });
          chipsList.appendChild(chip);
        }
      });
    })
    .catch(err => console.error('Error fetching anime franchises:', err));

  // Admin Drawer Controls
  const openAdminBtn = document.getElementById('open-admin-btn');
  const adminDrawer = document.getElementById('admin-drawer');
  const adminCloseBtn = document.getElementById('admin-close-btn');

  if (openAdminBtn && adminDrawer) {
    openAdminBtn.addEventListener('click', () => {
      adminDrawer.classList.add('open');
      loadAdminData();
    });
  }
  if (adminCloseBtn && adminDrawer) {
    adminCloseBtn.addEventListener('click', () => {
      adminDrawer.classList.remove('open');
    });
  }

  // Create Room Click
  document.getElementById('create-room-btn').addEventListener('click', () => {
    const purse = parseInt(document.getElementById('starting-purse-select').value, 10);
    const formsMode = document.getElementById('forms-mode-select') ? document.getElementById('forms-mode-select').value : 'SINGLE_BASE';

    let selectedAnime = [];
    if (selectedAnimeMode === 'single') {
      const selVal = document.getElementById('single-anime-select').value;
      if (selVal) selectedAnime = [selVal];
    } else if (selectedAnimeMode === 'multiple') {
      selectedAnime = Array.from(selectedAnimeFranchises);
      if (selectedAnime.length === 0) {
        alert('Please select at least one franchise for Selected Anime mode.');
        return;
      }
    }

    const battleControlMode = document.getElementById('battle-control-select')?.value || 'ai_vs_ai';
    const tournamentFormat = document.getElementById('tournament-format-select')?.value || 'round_robin';

    gameState.ws.send(JSON.stringify({
      action: 'create_room',
      data: {
        name: gameState.myName,
        avatar: gameState.myAvatar,
        session_id: gameState.sessionId,
        starting_purse: purse,
        min_bid: 10,
        anime_mode: selectedAnimeMode,
        selected_anime: selectedAnime,
        forms_mode: formsMode,
        battle_control_mode: battleControlMode,
        tournament_format: tournamentFormat
      }
    }));
  });

  // Join Room Click
  document.getElementById('join-room-btn').addEventListener('click', () => {
    const code = document.getElementById('room-code-input').value.trim().toUpperCase();
    if (!code) return alert('Please enter a room code');
    gameState.ws.send(JSON.stringify({
      action: 'join_room',
      data: {
        room_code: code,
        name: gameState.myName,
        avatar: gameState.myAvatar,
        session_id: gameState.sessionId
      }
    }));
  });

  // Copy Room Code Button
  document.getElementById('copy-code-btn').addEventListener('click', () => {
    if (gameState.roomCode) {
      navigator.clipboard.writeText(gameState.roomCode);
      const btn = document.getElementById('copy-code-btn');
      btn.textContent = '✅ Copied!';
      setTimeout(() => { btn.textContent = '📋 Copy Room Code'; }, 2000);
    }
  });

  // Copy Complete Shareable Invite Link Button
  const copyInviteBtn = document.getElementById('copy-invite-btn');
  if (copyInviteBtn) {
    copyInviteBtn.addEventListener('click', () => {
      if (gameState.roomCode) {
        const inviteUrl = `${window.location.origin}${window.location.pathname}?room=${gameState.roomCode}`;
        navigator.clipboard.writeText(inviteUrl).then(() => {
          copyInviteBtn.textContent = '✅ Invite Link Copied!';
          const toast = document.getElementById('invite-copied-toast');
          if (toast) toast.style.display = 'block';
          setTimeout(() => {
            copyInviteBtn.textContent = '🔗 COPY INVITE LINK';
            if (toast) toast.style.display = 'none';
          }, 2500);
        }).catch(() => {
          prompt('Copy this room invite link:', inviteUrl);
        });
      }
    });
  }

  // Ready Toggle Click
  document.getElementById('ready-toggle-btn').addEventListener('click', () => {
    gameState.ws.send(JSON.stringify({ action: 'toggle_ready' }));
  });

  // Start Auction Click (Host)
  document.getElementById('start-game-btn').addEventListener('click', () => {
    gameState.ws.send(JSON.stringify({ action: 'start_game' }));
  });

  // Dynamic Quick Bid Buttons (Auto-fills the custom bid input box)
  document.querySelectorAll('.btn-quick-bid').forEach(btn => {
    btn.addEventListener('click', () => {
      const amount = parseInt(btn.dataset.amount, 10);
      const input = document.getElementById('custom-bid-input');
      if (amount > 0 && input) {
        input.value = amount;
        input.focus();
        const submitBtn = document.getElementById('submit-bid-btn');
        if (submitBtn) {
          submitBtn.style.transform = 'scale(1.03)';
          setTimeout(() => { submitBtn.style.transform = ''; }, 180);
        }
      }
    });
  });

  // Custom Bid Button (Accepts any valid amount)
  document.getElementById('submit-bid-btn').addEventListener('click', () => {
    const input = document.getElementById('custom-bid-input');
    const val = parseInt(input.value, 10);
    if (val > 0) placeBid(val);
  });

  // Chat send
  document.getElementById('chat-send-btn').addEventListener('click', sendChatMessage);
  document.getElementById('chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendChatMessage();
  });

  // Skip Character Button
  const skipBtn = document.getElementById('btn-skip-character');
  if (skipBtn) {
    skipBtn.addEventListener('click', () => {
      if (gameState.ws && gameState.roomCode) {
        gameState.ws.send(JSON.stringify({
          action: 'skip_character',
          data: {}
        }));
      }
    });
  }

  // More Options Menu Toggle
  const moreOptionsBtn = document.getElementById('btn-more-options');
  const moreOptionsMenu = document.getElementById('more-options-menu');
  if (moreOptionsBtn && moreOptionsMenu) {
    moreOptionsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = moreOptionsMenu.style.display === 'block';
      moreOptionsMenu.style.display = isOpen ? 'none' : 'block';
    });
    document.addEventListener('click', () => {
      if (moreOptionsMenu) moreOptionsMenu.style.display = 'none';
    });
  }

  // Withdraw Modal Interactions
  const withdrawMenuItem = document.getElementById('btn-withdraw-match');
  const withdrawModal = document.getElementById('withdraw-modal');
  const withdrawCancel = document.getElementById('btn-withdraw-cancel');
  const withdrawConfirm = document.getElementById('btn-withdraw-confirm');

  if (withdrawMenuItem && withdrawModal) {
    withdrawMenuItem.addEventListener('click', () => {
      if (moreOptionsMenu) moreOptionsMenu.style.display = 'none';
      withdrawModal.style.display = 'flex';
    });
  }
  if (withdrawCancel && withdrawModal) {
    withdrawCancel.addEventListener('click', () => {
      withdrawModal.style.display = 'none';
    });
  }
  if (withdrawConfirm && withdrawModal) {
    withdrawConfirm.addEventListener('click', () => {
      withdrawModal.style.display = 'none';
      if (gameState.ws && gameState.roomCode) {
        gameState.ws.send(JSON.stringify({
          action: 'withdraw_match',
          data: {}
        }));
      }
    });
  }

  // Rematch and Exit Room Buttons
  const rematchBtn = document.getElementById('btn-rematch');
  if (rematchBtn) {
    rematchBtn.addEventListener('click', () => {
      if (!gameState.isHost) {
        alert('Only the room host can initiate a rematch.');
        return;
      }
      if (gameState.ws && gameState.roomCode) {
        gameState.ws.send(JSON.stringify({
          action: 'request_rematch',
          data: {}
        }));
      }
    });
  }

  const exitRoomBtn = document.getElementById('btn-exit-room');
  if (exitRoomBtn) {
    exitRoomBtn.addEventListener('click', () => {
      if (confirm('Are you sure you want to exit the room?')) {
        if (gameState.ws && gameState.roomCode) {
          gameState.ws.send(JSON.stringify({
            action: 'exit_room',
            data: {}
          }));
        }
        gameState.roomCode = null;
        gameState.isHost = false;
        gameState.isWithdrawn = false;
        switchArenaScreen('arena-setup');
      }
    });
  }

  const rematchAccept = document.getElementById('btn-rematch-accept');
  const rematchDecline = document.getElementById('btn-rematch-decline');
  if (rematchAccept) {
    rematchAccept.addEventListener('click', () => {
      if (gameState.ws && gameState.roomCode) {
        gameState.ws.send(JSON.stringify({
          action: 'vote_rematch',
          data: { accept: true }
        }));
      }
      const btns = document.getElementById('rematch-vote-buttons');
      const waitNote = document.getElementById('rematch-waiting-note');
      if (btns) btns.style.display = 'none';
      if (waitNote) waitNote.style.display = 'block';
    });
  }
  if (rematchDecline) {
    rematchDecline.addEventListener('click', () => {
      if (gameState.ws && gameState.roomCode) {
        gameState.ws.send(JSON.stringify({
          action: 'vote_rematch',
          data: { accept: false }
        }));
      }
      hideRematchModal();
    });
  }

  // Play Again (Legacy fallback)
  const playAgain = document.getElementById('play-again-btn');
  if (playAgain) {
    playAgain.addEventListener('click', () => {
      switchArenaScreen('arena-setup');
    });
  }
}

function showRematchModal(data) {
  const modal = document.getElementById('rematch-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  const desc = document.getElementById('rematch-modal-desc');
  if (desc) desc.textContent = `Trainer ${escapeHtml(data.host_name)} wants a rematch!`;
  const tally = document.getElementById('rematch-tally-bar');
  if (tally) tally.textContent = `Accepted: ${data.accepted_count} / ${data.total_needed} Trainers`;

  const btns = document.getElementById('rematch-vote-buttons');
  const waitNote = document.getElementById('rematch-waiting-note');
  if (data.host_session_id === gameState.sessionId) {
    if (btns) btns.style.display = 'none';
    if (waitNote) waitNote.style.display = 'block';
  } else {
    if (btns) btns.style.display = 'flex';
    if (waitNote) waitNote.style.display = 'none';
  }
}

function updateRematchTally(data) {
  const tally = document.getElementById('rematch-tally-bar');
  if (tally) {
    tally.textContent = `Accepted: ${data.accepted_count} / ${data.total_needed} Trainers`;
  }
}

function hideRematchModal() {
  const modal = document.getElementById('rematch-modal');
  if (modal) modal.style.display = 'none';
  const btns = document.getElementById('rematch-vote-buttons');
  const waitNote = document.getElementById('rematch-waiting-note');
  if (btns) btns.style.display = 'flex';
  if (waitNote) waitNote.style.display = 'none';
}

function sendChatMessage() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (text && gameState.ws) {
    gameState.ws.send(JSON.stringify({
      action: 'chat',
      data: { text }
    }));
    input.value = '';
  }
}

function appendChatMessage(msg) {
  const container = document.getElementById('lobby-chat-messages');
  const div = document.createElement('div');
  div.className = 'chat-bubble';
  div.innerHTML = `
    <span class="chat-time">${msg.time}</span>
    <span class="chat-sender">${escapeHtml(msg.sender_name)}:</span>
    <span class="chat-text">${escapeHtml(msg.text)}</span>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// Bidding Action
function placeBid(amount) {
  if (!gameState.ws) return;
  gameState.ws.send(JSON.stringify({
    action: 'place_bid',
    data: { amount }
  }));
}

function showBiddingError(msg) {
  const note = document.getElementById('reserve-budget-note');
  note.textContent = `⚠️ ${msg}`;
  note.style.color = '#ef4444';
  setTimeout(() => {
    const me = gameState.roomState && gameState.roomState.players.find(p => p.session_id === gameState.sessionId);
    updateReserveBudgetNote(me);
  }, 4000);
}

// Update Lobby UI
function updateLobbyUI(roomState) {
  gameState.roomState = roomState;
  document.getElementById('lobby-code-display').textContent = roomState.room_code;
  document.getElementById('lobby-purse-display').textContent = `₹${roomState.starting_purse.toLocaleString()}`;
  document.getElementById('lobby-player-count').textContent = roomState.players.length;

  const list = document.getElementById('lobby-players-list');
  list.innerHTML = '';

  const me = roomState.players.find(p => p.session_id === gameState.sessionId);
  if (me) {
    gameState.isHost = me.is_host;
    const readyBtn = document.getElementById('ready-toggle-btn');
    readyBtn.textContent = me.is_ready ? '❌ Unready' : '✅ Mark Ready';
    readyBtn.classList.toggle('ready', me.is_ready);
  }

  const startBtn = document.getElementById('start-game-btn');
  if (gameState.isHost) {
    startBtn.style.display = 'inline-block';
    startBtn.disabled = roomState.players.length < 2;
    startBtn.title = roomState.players.length < 2 ? 'Need at least 2 players to start' : 'Start the auction';
  } else {
    startBtn.style.display = 'none';
  }

  roomState.players.forEach(p => {
    const av = TRAINER_AVATARS.find(a => a.id === p.avatar) || TRAINER_AVATARS[0];
    const isMe = p.session_id === gameState.sessionId;

    const card = document.createElement('div');
    card.className = `lobby-player-card ${p.is_ready ? 'is-ready' : ''} ${isMe ? 'is-me' : ''}`;
    card.innerHTML = `
      <div class="lobby-avatar" style="background:${av.color};">${av.icon}</div>
      <div class="lobby-player-info">
        <div class="player-name">
          ${escapeHtml(p.name)} ${isMe ? '<span class="you-badge">(You)</span>' : ''}
          ${p.is_host ? '<span class="host-badge">👑 HOST</span>' : ''}
        </div>
        <div class="player-purse">Purse: ₹${p.purse.toLocaleString()}</div>
      </div>
      <div class="ready-badge ${p.is_ready ? 'ready' : 'not-ready'}">
        ${p.is_ready ? 'READY' : 'WAITING'}
      </div>
    `;
    list.appendChild(card);
  });
}

// Update Stage UI
function updateStageUI(roomState) {
  gameState.roomState = roomState;
  document.getElementById('stage-room-code').textContent = roomState.room_code;

  const poolDisplay = document.getElementById('stage-pool-display');
  if (poolDisplay) {
    const round = roomState.auction_pokemon_count || 1;
    const maxPool = roomState.max_auction_pokemon || 16;
    poolDisplay.textContent = `${round} / ${maxPool}`;
  }

  const me = roomState.players.find(p => p.session_id === gameState.sessionId);
  if (me) {
    // Update my profile bar with carry-over purse
    document.getElementById('my-bar-name').textContent = me.name;
    document.getElementById('my-bar-purse').textContent = `₹${me.purse.toLocaleString()}`;
    document.getElementById('my-team-count-display').textContent = `${me.team_count}/6`;

    // Team dots
    const dots = document.querySelectorAll('#my-team-dots .dot');
    dots.forEach((dot, idx) => {
      dot.classList.toggle('filled', idx < me.team_count);
    });

    // Render my team roster (ONLY artwork, name, and types - NO STATS/TIER!)
    renderMyRoster(me.team);
    updateReserveBudgetNote(me);
    updateBidButtonStates(me, roomState);
  }

  // Update Opponents list (ONLY purse and team count - NO POWER SHOWN!)
  renderOpponents(roomState.players);
}

// Render My Acquired Roster during Auction (NO STATS / NO POWER REVEALED)
function renderMyRoster(team) {
  const container = document.getElementById('my-roster-list');
  container.innerHTML = '';

  for (let i = 0; i < 6; i++) {
    const p = team[i];
    const slot = document.createElement('div');
    slot.className = `roster-slot ${p ? 'filled' : 'empty'}`;

    if (p) {
      const animeName = p.anime_name || 'Pokémon';
      const formText = p.current_form && p.current_form !== 'Base' ? `(${p.current_form})` : '';
      slot.innerHTML = `
        <span class="slot-num">#${i + 1}</span>
        <img src="${p.image}" alt="${p.name}" class="roster-slot-img" onerror="this.onerror=null; this.src='/api/avatar/' + (p.id || p.name.toLowerCase().replace(/\\s+/g, '_'));">
        <div class="roster-slot-info">
          <div class="roster-slot-name">${escapeHtml(p.name)}</div>
          <div class="roster-slot-meta">
            <span style="font-size:0.75rem; color:#38bdf8;">${escapeHtml(animeName)} ${escapeHtml(formText)}</span>
          </div>
        </div>
      `;
    } else {
      slot.innerHTML = `
        <span class="slot-num">#${i + 1}</span>
        <div class="empty-slot-text">Empty Slot</div>
      `;
    }
    container.appendChild(slot);
  }
}

// Render Opponents Table during Auction (NO TEAM POWER SHOWN)
function renderOpponents(players) {
  const container = document.getElementById('opponents-list');
  container.innerHTML = '';

  players.forEach(p => {
    const isMe = p.session_id === gameState.sessionId;
    const isLeader = p.session_id === (gameState.roomState ? gameState.roomState.highest_bidder_id : null);
    const av = TRAINER_AVATARS.find(a => a.id === p.avatar) || TRAINER_AVATARS[0];

    const card = document.createElement('div');
    card.className = `opponent-card ${isLeader ? 'leading' : ''} ${isMe ? 'is-me' : ''} ${p.is_withdrawn ? 'is-withdrawn' : ''}`;
    card.innerHTML = `
      <div class="opponent-avatar" style="background:${av.color};">${av.icon}</div>
      <div class="opponent-info">
        <div class="opponent-name">
          ${escapeHtml(p.name)} ${isMe ? '(You)' : ''}
          ${p.is_withdrawn ? '<span class="withdrawn-badge" style="background:#ef4444; color:#fff; font-size:0.7rem; padding:2px 6px; border-radius:4px; font-weight:700; margin-left:4px;">WITHDRAWN</span>' : ''}
          ${p.has_skipped && !p.is_withdrawn ? '<span class="skipped-badge" style="background:#64748b; color:#fff; font-size:0.7rem; padding:2px 6px; border-radius:4px; font-weight:700; margin-left:4px;">SKIPPED</span>' : ''}
          ${isLeader ? '<span class="lead-badge">🔥 LEADING</span>' : ''}
          ${p.is_team_full ? '<span class="full-badge">FULL</span>' : ''}
        </div>
        <div class="opponent-stats">
          <span>Purse: ₹${p.purse.toLocaleString()}</span> &bull; 
          <span>Team: ${p.team_count}/6</span>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

// Render Active Pokemon / Anime Character Auction Card (ONLY Artwork, Name, Anime, Form - NO STATS/TIER!)
function renderAuctionCard(poke) {
  const card = document.getElementById('active-pokemon-card');
  const typeBadges = (poke.types && poke.types.length)
    ? poke.types.map(t => `<span class="type-badge type-${t.toLowerCase()}">${t}</span>`).join('')
    : '';

  const animeBadge = poke.anime_name
    ? `<span class="anime-badge ${poke.anime_id || ''}">${escapeHtml(poke.anime_name)}</span>`
    : '';

  const formBadge = (poke.current_form && poke.current_form !== 'Base')
    ? `<div class="form-pill">⚡ ${escapeHtml(poke.current_form)}</div>`
    : '';

  card.className = `active-auction-card`;
  card.innerHTML = `
    <div style="display:flex; justify-content:center; gap:0.5rem; margin-bottom:0.5rem; flex-wrap:wrap;">
      ${animeBadge}
    </div>
    <div class="auction-hero-img-wrap">
      <img src="${poke.image}" alt="${poke.name}" class="auction-hero-img" onerror="this.onerror=null; this.src='/api/avatar/' + (poke.id || poke.name.toLowerCase().replace(/\\s+/g, '_'));">
    </div>

    <h2 class="auction-poke-name">${escapeHtml(poke.name)}</h2>
    ${formBadge}
    ${typeBadges ? `<div class="type-pill-list" style="justify-content:center; margin-top:0.5rem; margin-bottom:0.5rem;">${typeBadges}</div>` : ''}
    <div style="font-size:0.75rem; color:#64748b; margin-top:0.4rem;">Stats hidden &bull; Revealed after tournament</div>
  `;
}

// Update Timer Display
function updateTimerDisplay(seconds) {
  const num = document.getElementById('auction-timer-num');
  const circle = document.getElementById('timer-circle-fill');
  num.textContent = Math.max(0, seconds);

  const totalOffset = 263.89;
  const maxSeconds = (gameState.roomState && gameState.roomState.countdown_seconds) || 15;
  const progress = Math.max(0, Math.min(1, seconds / maxSeconds));
  const strokeOffset = totalOffset * (1 - progress);
  circle.style.strokeDashoffset = strokeOffset;

  if (seconds <= 4) {
    circle.style.stroke = '#ef4444';
    num.style.color = '#ef4444';
  } else if (seconds <= 7) {
    circle.style.stroke = '#f59e0b';
    num.style.color = '#f59e0b';
  } else {
    circle.style.stroke = '#10b981';
    num.style.color = '#10b981';
  }
}

// Update Bid Status Hero (AUTHORITATIVE: GUARANTEED ZERO "undefined" TEXT)
function updateBidStatus(amount, bidderId, bidderName, bidderAvatar) {
  const amountEl = document.getElementById('current-bid-amount');
  const bidderEl = document.getElementById('current-bidder-name');
  amountEl.textContent = amount > 0 ? amount.toLocaleString() : '0';
  const minBid = gameState.roomState ? gameState.roomState.min_bid : 10;

  if (!bidderId) {
    bidderEl.textContent = `No Bids Yet (Opening: ₹${minBid})`;
    bidderEl.style.color = '#94a3b8';
  } else {
    const isMe = bidderId === gameState.sessionId;
    let displayName = bidderName;
    if (!displayName && gameState.roomState && gameState.roomState.players) {
      const p = Array.isArray(gameState.roomState.players)
        ? gameState.roomState.players.find(x => x.session_id === bidderId)
        : gameState.roomState.players[bidderId];
      if (p && p.name) displayName = p.name;
    }
    if (!displayName || displayName === 'undefined') {
      displayName = isMe ? 'You' : 'Opponent';
    }
    bidderEl.textContent = isMe ? '🏆 Leading: You (Highest Bidder)' : `Leading: ${displayName}`;
    bidderEl.style.color = isMe ? '#10b981' : '#f59e0b';
  }
  updateDynamicQuickBids();
}

// Dynamic Quick Bid Buttons & Next Valid Bid Display
function updateDynamicQuickBids() {
  const current = gameState.roomState ? (gameState.roomState.current_bid || 0) : 0;
  const minBid = gameState.roomState ? (gameState.roomState.min_bid || 10) : 10;
  const nextValid = current === 0 ? minBid : current + 1;

  const nextValidDisplay = document.getElementById('next-valid-bid-display');
  if (nextValidDisplay) {
    nextValidDisplay.textContent = `₹${nextValid.toLocaleString()}`;
  }

  const minBtn = document.getElementById('btn-quick-min');
  const p5Btn = document.getElementById('btn-quick-p5');
  const p10Btn = document.getElementById('btn-quick-p10');
  const p25Btn = document.getElementById('btn-quick-p25');
  const p50Btn = document.getElementById('btn-quick-p50');

  if (minBtn) {
    minBtn.textContent = `MIN (₹${nextValid.toLocaleString()})`;
    minBtn.dataset.amount = nextValid;
  }
  if (p5Btn) {
    const v = current === 0 ? minBid + 5 : current + 5;
    p5Btn.textContent = `+₹5 (₹${v.toLocaleString()})`;
    p5Btn.dataset.amount = v;
  }
  if (p10Btn) {
    const v = current === 0 ? minBid + 10 : current + 10;
    p10Btn.textContent = `+₹10 (₹${v.toLocaleString()})`;
    p10Btn.dataset.amount = v;
  }
  if (p25Btn) {
    const v = current === 0 ? minBid + 25 : current + 25;
    p25Btn.textContent = `+₹25 (₹${v.toLocaleString()})`;
    p25Btn.dataset.amount = v;
  }
  if (p50Btn) {
    const v = current === 0 ? minBid + 50 : current + 50;
    p50Btn.textContent = `+₹50 (₹${v.toLocaleString()})`;
    p50Btn.dataset.amount = v;
  }

  const customInput = document.getElementById('custom-bid-input');
  if (customInput && !customInput.disabled) {
    customInput.min = nextValid;
    customInput.placeholder = `Enter ₹${nextValid.toLocaleString()} or higher`;
  }
}

// Reserve Budget Note
function updateReserveBudgetNote(me) {
  if (!me) return;
  const note = document.getElementById('reserve-budget-note');
  if (me.team_count >= 6) {
    note.textContent = 'Team full (6/6 Pokémon). Maximum capacity reached.';
    note.style.color = '#94a3b8';
  } else {
    note.textContent = `Available Purse: ₹${me.purse.toLocaleString()} • Roster: ${me.team_count}/6 Pokémon (6 is max limit, team sizes 1–6 are all valid).`;
    note.style.color = '#38bdf8';
  }
}

// Update Bid Buttons Disabling
function updateBidButtonStates(me, roomState) {
  const isLeader = roomState.highest_bidder_id === gameState.sessionId;
  const isFull = me.team_count >= 6;
  const isWithdrawn = me.is_withdrawn || gameState.isWithdrawn;
  const hasSkipped = me.has_skipped || (roomState.skipped_player_ids && roomState.skipped_player_ids.includes(gameState.sessionId));
  const minBid = roomState.min_bid || 10;
  const minRequired = roomState.current_bid === 0 ? minBid : roomState.current_bid + 1;
  const maxAllowed = (isFull || isWithdrawn || hasSkipped) ? 0 : me.purse;

  const quickBtns = document.querySelectorAll('.btn-quick-bid');
  const submitBtn = document.getElementById('submit-bid-btn');
  const customInput = document.getElementById('custom-bid-input');
  const skipBtn = document.getElementById('btn-skip-character');
  const skipBadge = document.getElementById('skip-status-badge');

  const disabled = isLeader || isFull || isWithdrawn || hasSkipped || minRequired > maxAllowed;

  quickBtns.forEach(btn => {
    btn.disabled = disabled;
  });
  if (submitBtn) submitBtn.disabled = disabled;
  if (customInput) customInput.disabled = disabled;

  if (skipBtn) {
    skipBtn.disabled = isWithdrawn || hasSkipped || roomState.status !== 'AUCTION';
  }
  if (skipBadge) {
    skipBadge.style.display = hasSkipped ? 'inline-block' : 'none';
  }

  // Auto-set placeholder and min value
  if (!disabled && customInput) {
    customInput.min = minRequired;
    customInput.placeholder = `Min ₹${minRequired}`;
    if (!customInput.value || parseInt(customInput.value, 10) < minRequired) {
      customInput.value = minRequired;
    }
  }

  if (submitBtn) {
    if (isWithdrawn) {
      submitBtn.textContent = 'WITHDRAWN FROM MATCH';
    } else if (hasSkipped) {
      submitBtn.textContent = 'SKIPPED BY YOU';
    } else if (isLeader) {
      submitBtn.textContent = 'YOU ARE HIGHEST BIDDER';
    } else if (isFull) {
      submitBtn.textContent = 'TEAM FULL (6/6)';
    } else if (minRequired > maxAllowed) {
      submitBtn.textContent = 'INSUFFICIENT FUNDS';
    } else {
      submitBtn.textContent = '🔨 PLACE BID';
    }
  }
}

// Showcase Toast Overlay
function showShowcaseBanner(title, subtitle) {
  const banner = document.createElement('div');
  banner.className = 'showcase-overlay';
  banner.innerHTML = `
    <div class="showcase-content">
      <h2>${title}</h2>
      <p>${subtitle}</p>
    </div>
  `;
  document.body.appendChild(banner);
  setTimeout(() => { banner.classList.add('fade-out'); }, 2000);
  setTimeout(() => { banner.remove(); }, 2500);
}

// Live Auction Log
function addStageLog(htmlText, type) {
  const list = document.getElementById('stage-log-list');
  const item = document.createElement('div');
  item.className = `log-item log-${type}`;
  item.innerHTML = htmlText;
  list.prepend(item);
  if (list.children.length > 20) list.lastChild.remove();
}

// Render Final Leaderboard (REVEAL ALL STATS DRAMATICALLY!)
function renderLeaderboard(leaderboard, battleResults = null) {
  // 0. Champion Banner from Battle Results
  const champBanner = document.getElementById('battle-champion-banner');
  if (champBanner) {
    if (battleResults && battleResults.champion) {
      const ch = battleResults.champion;
      champBanner.style.display = 'inline-block';
      champBanner.textContent = `🏆 Champion: ${ch.name} (${ch.wins}W - ${ch.losses}L - ${ch.draws}D | ${ch.points} pts)`;
    } else {
      champBanner.style.display = 'none';
    }
  }

  // 1. Render Podium
  const podium = document.getElementById('podium-grid');
  podium.innerHTML = '';

  const top3 = leaderboard.slice(0, 3);
  const medals = ['🥇', '🥈', '🥉'];

  top3.forEach((p, idx) => {
    const av = TRAINER_AVATARS.find(a => a.id === p.avatar) || TRAINER_AVATARS[0];
    const pod = document.createElement('div');
    pod.className = `podium-card rank-${p.rank || (idx + 1)}`;
    const teamCount = p.pokemon_count || (p.team ? p.team.length : 0);
    const hasBattle = typeof p.battle_wins === 'number';
    const headline = hasBattle
      ? `${p.battle_wins}W-${p.battle_losses}L-${p.battle_draws}D <span class="lbl">${p.battle_points} PTS</span>`
      : `${p.team_power.toFixed(1)} <span class="lbl">TEAM POWER</span>`;
    pod.innerHTML = `
      <div class="podium-medal">${medals[idx] || '🏅'}</div>
      <div class="podium-avatar" style="background:${av.color};">${av.icon}</div>
      <h3 class="podium-name">${escapeHtml(p.name)}</h3>
      <div class="podium-power">${headline}</div>
      <div class="podium-stats">
        <span>Team: ${teamCount}/6</span> &bull; 
        <span>Power: ${p.team_power.toFixed(1)}</span> &bull; 
        <span>HP: ${p.total_hp || 0}</span>
      </div>
      <div style="font-size:0.8rem; color:#94a3b8; margin-top:0.3rem;">
        Purse: ₹${p.remaining_purse.toLocaleString()}
      </div>
    `;
    podium.appendChild(pod);
  });

  // 2. Render Full Table
  const tbody = document.getElementById('leaderboard-body');
  tbody.innerHTML = '';

  leaderboard.forEach(p => {
    const av = TRAINER_AVATARS.find(a => a.id === p.avatar) || TRAINER_AVATARS[0];
    const isMe = p.session_id === gameState.sessionId;
    const teamCount = p.pokemon_count || (p.team ? p.team.length : 0);
    const recordText = typeof p.battle_wins === 'number'
      ? `${p.battle_wins}W - ${p.battle_losses}L - ${p.battle_draws}D`
      : '-';
    const ptsText = typeof p.battle_points === 'number' ? p.battle_points : '-';

    const row = document.createElement('tr');
    row.className = isMe ? 'me-row' : '';
    row.innerHTML = `
      <td><span class="rank-badge">${p.rank}</span></td>
      <td>
        <div style="display:flex; align-items:center; gap:0.5rem;">
          <span style="font-size:1.2rem;">${av.icon}</span>
          <strong>${escapeHtml(p.name)}</strong> ${isMe ? '(You)' : ''}
          ${p.is_withdrawn ? '<span style="color:#ef4444; font-size:0.75rem; font-weight:700;">(Withdrawn)</span>' : ''}
        </div>
      </td>
      <td><strong>${recordText}</strong></td>
      <td><strong style="color:#f59e0b;">${ptsText}</strong></td>
      <td><span style="color:#10b981; font-weight:600;">${teamCount}/6</span></td>
      <td><strong style="color:#38bdf8; font-size:1.05rem;">${p.team_power.toFixed(1)}</strong></td>
      <td>₹${p.remaining_purse.toLocaleString()}</td>
      <td>
        <button class="btn btn-outline btn-sm inspect-team-btn" data-session="${p.session_id}">
          🔍 Inspect Team
        </button>
      </td>
    `;
    tbody.appendChild(row);
  });

  // 3. Render Individual Battle Summaries
  const matchesCard = document.getElementById('battle-matches-card');
  const matchesGrid = document.getElementById('battle-matches-summary');
  if (matchesCard && matchesGrid) {
    if (battleResults && Array.isArray(battleResults.matches) && battleResults.matches.length > 0) {
      matchesCard.style.display = 'block';
      matchesGrid.innerHTML = battleResults.matches.map((m, idx) => {
        const winnerName = m.is_draw
          ? 'Draw'
          : (m.winner_id === m.player_a_id ? m.player_a_name : m.player_b_name);
        return `
          <div class="battle-match-summary-card">
            <div style="font-weight:800; color:#38bdf8; margin-bottom:0.25rem;">
              Match ${idx + 1}: ${escapeHtml(m.player_a_name)} vs ${escapeHtml(m.player_b_name)}
            </div>
            <div>Winner: <strong style="color:#10b981;">${escapeHtml(winnerName)}</strong></div>
            <div style="color:#94a3b8; font-size:0.8rem;">Turns: ${m.turns_played} &bull; ${escapeHtml(m.reason)}</div>
          </div>
        `;
      }).join('');
    } else {
      matchesCard.style.display = 'none';
    }
  }

  // Attach inspect click handlers
  document.querySelectorAll('.inspect-team-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const sessId = btn.dataset.session;
      const player = leaderboard.find(p => p.session_id === sessId);
      if (player) inspectPlayerTeam(player);
    });
  });

  // Auto-inspect winner
  if (leaderboard.length > 0) {
    inspectPlayerTeam(leaderboard[0]);
  }

  // Update Rematch button state according to host role
  const rematchBtn = document.getElementById('btn-rematch');
  if (rematchBtn) {
    if (gameState.isHost) {
      rematchBtn.textContent = '🔄 PROPOSE REMATCH';
      rematchBtn.disabled = false;
      rematchBtn.style.opacity = '1';
      rematchBtn.style.cursor = 'pointer';
    } else {
      rematchBtn.textContent = '🔄 REMATCH (Waiting for Host)';
      rematchBtn.disabled = true;
      rematchBtn.style.opacity = '0.6';
      rematchBtn.style.cursor = 'not-allowed';
    }
  }
}

// Inspect a Player's Cards (FULL STATS REVEALED!)
function inspectPlayerTeam(player) {
  const panel = document.getElementById('team-showcase-panel');
  const title = document.getElementById('showcase-title');
  const grid = document.getElementById('showcase-cards-grid');

  const count = player.team ? player.team.length : 0;
  title.innerHTML = `
    <span>🏆 ${escapeHtml(player.name)}'s Final Roster</span>
    <span style="font-size:0.9rem; font-weight:normal; color:#94a3b8; margin-left:0.5rem;">
      (${count}/6 Characters &bull; Combined Power: <strong style="color:#38bdf8;">${player.team_power.toFixed(1)}</strong> &bull; Total BST: <strong>${player.total_bst}</strong>)
    </span>
  `;
  grid.innerHTML = '';

  if (count === 0) {
    grid.innerHTML = '<div style="color:#94a3b8; padding:2rem; text-align:center;">No characters acquired during auction.</div>';
  } else {
    player.team.forEach(p => {
      const tierClass = `tier-${(p.power_tier || p.tier || 'B').replace('+', '-plus')}`;
      const card = document.createElement('div');
      card.className = 'showcase-card';

      const st = p.stats || {};
      const power = p.power_rating ? Number(p.power_rating).toFixed(1) : '50.0';
      const animeName = p.anime_name || 'Pokémon';
      const techniques = (p.techniques && p.techniques.length)
        ? p.techniques.slice(0, 3).join(', ')
        : ((p.abilities && p.abilities.length) ? p.abilities.slice(0, 3).join(', ') : 'Standard');
      const formBadge = (p.current_form && p.current_form !== 'Base')
        ? `<span class="form-pill">⚡ ${escapeHtml(p.current_form)}</span>`
        : '';

      let statsLine = '';
      if ('combat_skill' in st || 'energy_projection' in st) {
        statsLine = `STR: ${st.strength || 0} &bull; SPD: ${st.speed || 0} &bull; DUR: ${st.durability || 0}<br>INT: ${st.intelligence || 0} &bull; SKL: ${st.combat_skill || 0} &bull; ENG: ${st.energy_projection || 0}`;
      } else if ('strength' in st || 'attack_power' in st) {
        statsLine = `STR: ${st.strength || 0} &bull; ATK: ${st.attack_power || 0} &bull; SPD: ${st.speed || 0}<br>DUR: ${st.durability || 0} &bull; DEF: ${st.defense || 0} &bull; BIQ: ${st.battle_iq || 0}`;
      } else {
        statsLine = `HP: ${st.hp || 0} &bull; ATK: ${st.attack || 0} &bull; DEF: ${st.defense || 0}<br>SPA: ${st.special_attack || 0} &bull; SPD: ${st.special_defense || 0} &bull; SPE: ${st.speed || 0}`;
      }
      const attrHtml = p.attribution ? `<div style="font-size:0.62rem; color:#64748b; margin-top:0.25rem;">${escapeHtml(p.attribution)}</div>` : '';

      card.innerHTML = `
        <span class="card-tier-badge ${tierClass}">${p.power_tier || p.tier || 'A'}</span>
        <div style="font-size:0.7rem; color:#f59e0b; font-weight:700; text-transform:uppercase; margin-bottom:0.25rem;">${escapeHtml(animeName)}</div>
        <img src="${p.image}" alt="${p.name}" class="showcase-img" onerror="this.onerror=null; this.src='/api/avatar/' + (p.id || p.name.toLowerCase().replace(/\\s+/g, '_'));">
        <h4 class="showcase-name">${escapeHtml(p.name)}</h4>
        <div style="margin-bottom:0.35rem;">${formBadge}</div>
        <div class="showcase-meta" style="margin-bottom:0.4rem;">
          <span style="color:#38bdf8; font-weight:700;">PR ${power}</span>
          <span style="color:#94a3b8;">Tier ${p.power_tier || p.tier || 'B'}</span>
        </div>
        <div style="font-size:0.7rem; color:#cbd5e1; margin-bottom:0.4rem;">
          <strong>Tech/Abil:</strong> ${escapeHtml(techniques)}
        </div>
        <div style="font-size:0.68rem; color:#94a3b8; font-family:'JetBrains Mono'; text-align:left; background:rgba(0,0,0,0.3); padding:0.4rem; border-radius:6px; line-height:1.4;">
          ${statsLine}
        </div>
        ${attrHtml}
      `;
      grid.appendChild(card);
    });
  }

  panel.style.display = 'block';
  panel.scrollIntoView({ behavior: 'smooth' });
}

// Multi-Anime Admin Data Loader & Automated Import Controller
let adminPollInterval = null;

function loadAdminAudit(refresh = false) {
  fetch(`/api/admin/audit${refresh ? '?refresh=1' : ''}`)
    .then(r => r.json())
    .then(data => {
      const tbody = document.getElementById('admin-audit-tbody');
      if (!tbody) return;
      tbody.innerHTML = '';
      (data.franchise_audit || []).forEach(f => {
        const tr = document.createElement('tr');
        const reached = f.status === 'REACHED TARGET';
        tr.innerHTML = `
          <td><strong>${escapeHtml(f.name)}</strong></td>
          <td>${f.total_records}</td>
          <td><strong style="color:${reached ? '#10b981' : '#f59e0b'}">${f.unique_characters}</strong></td>
          <td><span style="color:#38bdf8;">${f.verified_images}</span></td>
          <td>${f.target}</td>
          <td><span class="badge ${reached ? 'badge-success' : 'badge-warning'}" style="font-size:0.72rem; padding:0.15rem 0.4rem; border-radius:4px; background:${reached ? 'rgba(16,185,129,0.15); color:#10b981;' : 'rgba(245,158,11,0.15); color:#f59e0b;'}">${f.status}</span></td>
        `;
        tbody.appendChild(tr);
      });
    })
    .catch(() => {});
}

function loadAdminData() {
  setupAdminImportControls();
  pollAdminImportStatus();

  if (!adminPollInterval) {
    adminPollInterval = setInterval(pollAdminImportStatus, 1500);
  }

  // 1. Load Audit Table
  loadAdminAudit();

  // 2. Load Franchises
  loadAdminFranchises();

  // 3. Load Characters Table
  loadAdminCharacters();

  const searchInput = document.getElementById('admin-search-input');
  if (searchInput && !searchInput.dataset.bound) {
    searchInput.dataset.bound = 'true';
    let timeout;
    searchInput.addEventListener('input', () => {
      clearTimeout(timeout);
      timeout = setTimeout(() => loadAdminCharacters(), 300);
    });
  }

  const franchiseFilter = document.getElementById('admin-franchise-filter');
  if (franchiseFilter && !franchiseFilter.dataset.bound) {
    franchiseFilter.dataset.bound = 'true';
    franchiseFilter.addEventListener('change', () => loadAdminCharacters());
  }
}

function setupAdminImportControls() {
  const anilistBtn = document.getElementById('btn-import-anilist');
  const jikanBtn = document.getElementById('btn-import-jikan');
  const kitsuBtn = document.getElementById('btn-import-kitsu');
  const allBtn = document.getElementById('btn-import-all');
  const updateBtn = document.getElementById('btn-update-records');
  const repairBtn = document.getElementById('btn-repair-images');
  const dupBtn = document.getElementById('btn-check-duplicates');
  const retryBtn = document.getElementById('btn-retry-failed');
  const stopBtn = document.getElementById('btn-stop-import');
  const refreshAuditBtn = document.getElementById('btn-refresh-audit');
  const pagesSelect = document.getElementById('import-batch-pages');

  function triggerImport(source, pages) {
    const p = pages || (pagesSelect ? pagesSelect.value : 5);
    fetch(`/api/admin/import/start?source=${encodeURIComponent(source)}&pages=${encodeURIComponent(p)}`)
      .then(r => r.json())
      .then(res => {
        pollAdminImportStatus();
      })
      .catch(err => alert('Failed to start import: ' + err.message));
  }

  if (refreshAuditBtn && !refreshAuditBtn.dataset.bound) {
    refreshAuditBtn.dataset.bound = 'true';
    refreshAuditBtn.addEventListener('click', () => {
      loadAdminAudit(true);
    });
  }

  if (anilistBtn && !anilistBtn.dataset.bound) {
    anilistBtn.dataset.bound = 'true';
    anilistBtn.addEventListener('click', () => triggerImport('anilist'));
  }
  if (jikanBtn && !jikanBtn.dataset.bound) {
    jikanBtn.dataset.bound = 'true';
    jikanBtn.addEventListener('click', () => triggerImport('jikan'));
  }
  if (kitsuBtn && !kitsuBtn.dataset.bound) {
    kitsuBtn.dataset.bound = 'true';
    kitsuBtn.addEventListener('click', () => triggerImport('kitsu'));
  }
  if (allBtn && !allBtn.dataset.bound) {
    allBtn.dataset.bound = 'true';
    allBtn.addEventListener('click', () => triggerImport('all'));
  }
  if (updateBtn && !updateBtn.dataset.bound) {
    updateBtn.dataset.bound = 'true';
    updateBtn.addEventListener('click', () => triggerImport('anilist', 5));
  }
  if (repairBtn && !repairBtn.dataset.bound) {
    repairBtn.dataset.bound = 'true';
    repairBtn.addEventListener('click', () => {
      fetch('/api/admin/repair/images')
        .then(r => r.json())
        .then(res => {
          alert(`Image Audit Complete: ${res.verified_images} verified images out of ${res.total_checked} characters. ${res.missing_images} missing/fallback.`);
          loadAdminAudit();
        })
        .catch(err => alert('Repair error: ' + err.message));
    });
  }
  if (dupBtn && !dupBtn.dataset.bound) {
    dupBtn.dataset.bound = 'true';
    dupBtn.addEventListener('click', () => {
      fetch('/api/admin/duplicates/scan')
        .then(r => r.json())
        .then(res => {
          if (res.total_duplicates === 0) {
            alert('Duplicate Scan Complete: Zero duplicates found! All characters are unique.');
          } else {
            alert(`Found ${res.total_duplicates} potential duplicates.`);
          }
          loadAdminAudit();
        })
        .catch(err => alert('Duplicate scan error: ' + err.message));
    });
  }
  if (retryBtn && !retryBtn.dataset.bound) {
    retryBtn.dataset.bound = 'true';
    retryBtn.addEventListener('click', () => triggerImport('anilist', 5));
  }
  if (stopBtn && !stopBtn.dataset.bound) {
    stopBtn.dataset.bound = 'true';
    stopBtn.addEventListener('click', () => {
      fetch('/api/admin/import/stop')
        .then(r => r.json())
        .then(() => pollAdminImportStatus());
    });
  }
}

function pollAdminImportStatus() {
  fetch('/api/admin/import/status')
    .then(r => r.json())
    .then(data => {
      const badge = document.getElementById('import-live-badge');
      const msg = document.getElementById('import-live-message');
      const syncEl = document.getElementById('import-last-sync');
      const stopBtn = document.getElementById('btn-stop-import');
      const progressWrap = document.getElementById('import-progress-wrap');
      const progressBar = document.getElementById('import-progress-bar');

      if (badge) {
        badge.textContent = data.is_running ? 'IMPORTING...' : 'IDLE';
        badge.style.background = data.is_running ? '#38bdf8' : '#10b981';
      }
      if (msg) msg.textContent = data.last_message || 'Ready to import';
      if (syncEl) syncEl.textContent = data.last_sync || 'Never';

      if (stopBtn) stopBtn.style.display = data.is_running ? 'inline-block' : 'none';
      if (progressWrap) progressWrap.style.display = data.is_running ? 'block' : 'none';
      if (progressBar && data.is_running) {
        const pct = Math.min(100, Math.max(15, (data.current_page * 10) % 100));
        progressBar.style.width = pct + '%';
      }

      // Update real-time metric tiles
      const mFran = document.getElementById('metric-admin-franchises');
      const mChars = document.getElementById('metric-admin-chars');
      const mImg = document.getElementById('metric-admin-with-img');
      const mNoImg = document.getElementById('metric-admin-no-img');
      const mDup = document.getElementById('metric-admin-duplicates');
      const mDesc = document.getElementById('metric-admin-with-desc');
      const mFail = document.getElementById('metric-admin-failed');

      if (mFran) mFran.textContent = data.total_franchises || 21;
      if (mChars) mChars.textContent = Number(data.total_characters || 0).toLocaleString();
      if (mImg) mImg.textContent = Number(data.characters_with_images || 0).toLocaleString();
      if (mNoImg) mNoImg.textContent = Number(data.characters_without_images || 0).toLocaleString();
      if (mDup) mDup.textContent = Number(data.total_duplicates_merged || 0).toLocaleString();
      if (mDesc) mDesc.textContent = Number(data.characters_with_descriptions || 0).toLocaleString();
      if (mFail) mFail.textContent = Number(data.failed_count || 0).toLocaleString();
    })
    .catch(() => {});
}

function loadAdminFranchises() {
  fetch('/api/anime')
    .then(r => r.json())
    .then(franchises => {
      const container = document.getElementById('admin-franchises-list');
      const filterSelect = document.getElementById('admin-franchise-filter');
      if (container) container.innerHTML = '';
      if (filterSelect) {
        const currentVal = filterSelect.value;
        filterSelect.innerHTML = '<option value="">All Discovered Franchises</option>';
        franchises.forEach(f => {
          const opt = document.createElement('option');
          opt.value = f.id;
          opt.textContent = `${f.name} (${f.character_count || 0})`;
          if (f.id === currentVal) opt.selected = true;
          filterSelect.appendChild(opt);
        });
      }

      if (container) {
        franchises.forEach(f => {
          const btn = document.createElement('button');
          const isActive = f.is_active !== false;
          btn.className = `btn btn-sm ${isActive ? 'btn-primary' : 'btn-outline'}`;
          btn.style.fontSize = '0.75rem';
          btn.style.margin = '2px';
          btn.textContent = `${f.name} (${f.character_count || 0}): ${isActive ? 'ON' : 'OFF'}`;

          btn.addEventListener('click', () => {
            fetch(`/api/admin/franchise/toggle?id=${f.id}`)
              .then(r => r.json())
              .then(res => {
                if (res.success) {
                  f.is_active = !isActive;
                  loadAdminFranchises();
                }
              });
          });
          container.appendChild(btn);
        });
      }
    });
}

function loadAdminCharacters() {
  const query = document.getElementById('admin-search-input') ? document.getElementById('admin-search-input').value.trim() : '';
  const animeId = document.getElementById('admin-franchise-filter') ? document.getElementById('admin-franchise-filter').value : '';

  let url = `/api/characters?limit=40`;
  if (query) url += `&q=${encodeURIComponent(query)}`;
  if (animeId) url += `&anime_id=${encodeURIComponent(animeId)}`;

  fetch(url)
    .then(r => r.json())
    .then(data => {
      const tbody = document.getElementById('admin-characters-tbody');
      if (!tbody) return;
      tbody.innerHTML = '';

      (data.characters || []).forEach(c => {
        const tr = document.createElement('tr');
        const isActive = c.is_active !== false;
        const pr = c.power_rating ? Number(c.power_rating).toFixed(1) : '50.0';
        const sourceLabel = c.source || 'AniList / Canon';
        const completeness = c.data_completeness || 'Complete';
        const fallbackSrc = `/api/avatar/${c.id || c.name.toLowerCase().replace(/\\s+/g, '_')}`;

        tr.innerHTML = `
          <td>
            <div style="display:flex; align-items:center; gap:0.5rem;">
              <img src="${c.image}" style="width:32px; height:32px; object-fit:contain; border-radius:4px; background:rgba(255,255,255,0.05);" onerror="this.onerror=null; this.src='${fallbackSrc}';">
              <div>
                <strong>${escapeHtml(c.name)}</strong>
                ${c.native_name ? `<div style="font-size:0.7rem; color:#94a3b8;">${escapeHtml(c.native_name)}</div>` : ''}
              </div>
            </div>
          </td>
          <td><span class="anime-badge ${c.anime_id || ''}">${escapeHtml(c.anime_name || '')}</span></td>
          <td><strong style="color:#38bdf8;">${pr}</strong> <span style="font-size:0.7rem; color:#94a3b8;">(${c.power_tier || 'B'})</span></td>
          <td><span style="font-size:0.75rem; color:#cbd5e1;">${escapeHtml(sourceLabel)}</span></td>
          <td><span style="font-size:0.72rem; color:#10b981;">${escapeHtml(completeness)}</span></td>
          <td><span style="color:${isActive ? '#10b981' : '#ef4444'}; font-weight:700;">${isActive ? 'Active' : 'Disabled'}</span></td>
          <td>
            <button class="btn btn-outline btn-sm toggle-char-btn" data-cid="${c.id}" style="font-size:0.72rem; padding:0.2rem 0.5rem;">
              ${isActive ? 'Disable' : 'Enable'}
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      document.querySelectorAll('.toggle-char-btn').forEach(b => {
        b.addEventListener('click', () => {
          const cid = b.dataset.cid;
          fetch(`/api/admin/character/toggle?id=${cid}`)
            .then(r => r.json())
            .then(res => {
              if (res.success) loadAdminCharacters();
            });
        });
      });
    });
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text || '';
  return div.innerHTML;
}

// ============================================================================
// DEDICATED ANIME DATABASE CONTROLLER (21 FRANCHISES, 1,439 CHARACTERS)
// ============================================================================
const animeDatabaseModule = {
  initialized: false,
  state: {
    currentPage: 1,
    pageSize: 36,
    total: 0,
    filters: {
      q: '',
      anime_id: '',
      power_tier: '',
      rarity: '',
      species: '',
      sort: 'power_desc'
    }
  },

  async init() {
    this.initialized = true;
    this.setupListeners();
    await this.loadStats();
    await this.loadFranchisesDropdown();
    await this.fetchCharacters();
  },

  async loadStats() {
    try {
      const res = await fetch('/api/anime/stats');
      if (!res.ok) return;
      const data = await res.json();
      
      const charEl = document.getElementById('stat-anime-chars');
      const franEl = document.getElementById('stat-anime-franchises');
      const formEl = document.getElementById('stat-anime-forms');
      const imgEl = document.getElementById('stat-anime-images');

      if (charEl) charEl.textContent = Number(data.total_characters || 1439).toLocaleString();
      if (franEl) franEl.textContent = `${data.total_franchises || 21} Universes`;
      if (formEl) formEl.textContent = `${data.total_character_forms || 7} Forms`;
      if (imgEl) imgEl.textContent = `100% (${Number(data.characters_with_images || 1439).toLocaleString()} Active)`;

      const tiers = data.tier_counts || {};
      const sp = document.getElementById('tier-pill-sp');
      const s = document.getElementById('tier-pill-s');
      const a = document.getElementById('tier-pill-a');
      const b = document.getElementById('tier-pill-b');
      const c = document.getElementById('tier-pill-c');
      const d = document.getElementById('tier-pill-d');

      if (sp) sp.textContent = `S+: ${tiers['S+'] || 0}`;
      if (s) s.textContent = `S: ${tiers['S'] || 0}`;
      if (a) a.textContent = `A: ${tiers['A'] || 0}`;
      if (b) b.textContent = `B: ${tiers['B'] || 0}`;
      if (c) c.textContent = `C: ${tiers['C'] || 0}`;
      if (d) d.textContent = `D: ${tiers['D'] || 0}`;
    } catch (e) {
      console.warn('Could not load anime stats:', e);
    }
  },

  async loadFranchisesDropdown() {
    try {
      const res = await fetch('/api/anime');
      if (!res.ok) return;
      const franchises = await res.json();
      const select = document.getElementById('anime-franchise-select');
      if (!select) return;
      select.innerHTML = `<option value="">All Franchises (${franchises.length})</option>`;
      franchises.forEach(f => {
        const opt = document.createElement('option');
        opt.value = f.id;
        opt.textContent = `${f.name} (${f.character_count || 0})`;
        select.appendChild(opt);
      });
    } catch (e) {}
  },

  setupListeners() {
    const searchInput = document.getElementById('anime-search-input');
    const clearBtn = document.getElementById('anime-clear-search-btn');
    const franSelect = document.getElementById('anime-franchise-select');
    const tierSelect = document.getElementById('anime-tier-select');
    const raritySelect = document.getElementById('anime-rarity-select');
    const speciesSelect = document.getElementById('anime-species-select');
    const sortSelect = document.getElementById('anime-sort-select');
    const resetBtn = document.getElementById('anime-reset-filters-btn');
    const prevBtn = document.getElementById('anime-prev-page-btn');
    const nextBtn = document.getElementById('anime-next-page-btn');
    const quickButtons = document.querySelectorAll('#anime-quick-franchises .toggle-btn');

    let debounceTimer;
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
          this.state.filters.q = e.target.value.trim();
          if (clearBtn) clearBtn.style.display = this.state.filters.q ? 'block' : 'none';
          this.state.currentPage = 1;
          this.fetchCharacters();
        }, 280);
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        this.state.filters.q = '';
        clearBtn.style.display = 'none';
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    }

    quickButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        quickButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.state.filters.anime_id = btn.dataset.franchise || '';
        if (franSelect) franSelect.value = this.state.filters.anime_id;
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    });

    if (franSelect) {
      franSelect.addEventListener('change', (e) => {
        this.state.filters.anime_id = e.target.value;
        quickButtons.forEach(b => {
          b.classList.toggle('active', b.dataset.franchise === e.target.value);
        });
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    }

    if (tierSelect) {
      tierSelect.addEventListener('change', (e) => {
        this.state.filters.power_tier = e.target.value;
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    }

    if (raritySelect) {
      raritySelect.addEventListener('change', (e) => {
        this.state.filters.rarity = e.target.value;
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    }

    if (speciesSelect) {
      speciesSelect.addEventListener('change', (e) => {
        this.state.filters.species = e.target.value;
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    }

    if (sortSelect) {
      sortSelect.addEventListener('change', (e) => {
        this.state.filters.sort = e.target.value;
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    }

    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        if (clearBtn) clearBtn.style.display = 'none';
        if (franSelect) franSelect.value = '';
        if (tierSelect) tierSelect.value = '';
        if (raritySelect) raritySelect.value = '';
        if (speciesSelect) speciesSelect.value = '';
        if (sortSelect) sortSelect.value = 'power_desc';

        quickButtons.forEach(b => b.classList.remove('active'));
        const allBtn = document.querySelector('#anime-quick-franchises .toggle-btn[data-franchise=""]');
        if (allBtn) allBtn.classList.add('active');

        this.state.filters = {
          q: '',
          anime_id: '',
          power_tier: '',
          rarity: '',
          species: '',
          sort: 'power_desc'
        };
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    }

    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        if (this.state.currentPage > 1) {
          this.state.currentPage--;
          this.fetchCharacters();
          window.scrollTo({ top: 200, behavior: 'smooth' });
        }
      });
    }

    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        const totalPages = Math.ceil(this.state.total / this.state.pageSize) || 1;
        if (this.state.currentPage < totalPages) {
          this.state.currentPage++;
          this.fetchCharacters();
          window.scrollTo({ top: 200, behavior: 'smooth' });
        }
      });
    }
  },

  async fetchCharacters() {
    const grid = document.getElementById('anime-catalog-grid');
    if (!grid) return;
    grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; padding:3rem; color:#94a3b8;">Loading characters from Anime Database...</div>';

    const offset = (this.state.currentPage - 1) * this.state.pageSize;
    const p = new URLSearchParams();
    p.set('limit', this.state.pageSize);
    p.set('offset', offset);
    if (this.state.filters.q) p.set('q', this.state.filters.q);
    if (this.state.filters.anime_id) p.set('anime_id', this.state.filters.anime_id);
    if (this.state.filters.power_tier) p.set('power_tier', this.state.filters.power_tier);
    if (this.state.filters.rarity) p.set('rarity', this.state.filters.rarity);
    if (this.state.filters.species) p.set('species', this.state.filters.species);
    if (this.state.filters.sort) p.set('sort', this.state.filters.sort);

    try {
      const res = await fetch(`/api/characters?${p.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      this.state.total = data.total || 0;
      this.updatePaginationUI();
      this.renderGrid(data.characters || []);
    } catch (err) {
      grid.innerHTML = `<div style="grid-column:1/-1; text-align:center; padding:3rem; color:#ef4444;">Error loading anime characters: ${escapeHtml(err.message)}</div>`;
    }
  },

  updatePaginationUI() {
    const countEl = document.getElementById('anime-results-count');
    const infoEl = document.getElementById('anime-page-info');
    const prevBtn = document.getElementById('anime-prev-page-btn');
    const nextBtn = document.getElementById('anime-next-page-btn');
    const totalPages = Math.max(1, Math.ceil(this.state.total / this.state.pageSize));

    if (countEl) countEl.textContent = `Showing ${this.state.total.toLocaleString()} Anime Characters`;
    if (infoEl) infoEl.textContent = `Page ${this.state.currentPage} of ${totalPages}`;
    if (prevBtn) prevBtn.disabled = this.state.currentPage <= 1;
    if (nextBtn) nextBtn.disabled = this.state.currentPage >= totalPages;
  },

  renderGrid(characters) {
    const grid = document.getElementById('anime-catalog-grid');
    if (!grid) return;

    if (!characters || characters.length === 0) {
      grid.innerHTML = `
        <div style="grid-column:1/-1; text-align:center; padding:4rem 1rem;">
          <h3 style="font-size:1.25rem; color:#94a3b8; margin-bottom:0.5rem;">No Anime Characters Found</h3>
          <p style="color:#64748b; font-size:0.9rem;">Try adjusting your search terms or clearing selected filters.</p>
        </div>
      `;
      return;
    }

    let html = '';
    characters.forEach(c => {
      const tier = c.power_tier || c.tier || 'B';
      const tierClass = `tier-${tier.replace('+', '-plus')}`;
      const borderClass = `tier-border-${tier.replace('+', '-plus')}`;
      const pr = Number(c.power_rating || 50).toFixed(1);
      const bst = c.canonical_bst || c.bst || 500;
      const animeName = c.anime_name || 'Anime';
      const animeId = c.anime_id || '';
      const fallbackSrc = `/api/avatar/${c.id || c.name.toLowerCase().replace(/\\s+/g, '_')}`;

      const techniques = (c.techniques && c.techniques.length)
        ? c.techniques.slice(0, 2).map(t => `<span class="tech-tag" style="background:rgba(255,255,255,0.06); padding:0.15rem 0.4rem; border-radius:4px; font-size:0.7rem; color:#cbd5e1;">${escapeHtml(t)}</span>`).join(' ')
        : (c.abilities && c.abilities.length ? c.abilities.slice(0, 2).map(a => `<span class="tech-tag" style="background:rgba(255,255,255,0.06); padding:0.15rem 0.4rem; border-radius:4px; font-size:0.7rem; color:#cbd5e1;">${escapeHtml(a)}</span>`).join(' ') : '');

      const formCount = (c.forms && c.forms.length) || 0;
      const formBadge = (c.current_form && c.current_form !== 'Base')
        ? `<div class="form-pill" style="margin-top:0.25rem;">⚡ ${escapeHtml(c.current_form)}</div>`
        : (formCount > 0 ? `<div class="form-pill" style="margin-top:0.25rem;">⚡ ${formCount} Forms</div>` : '');

      html += `
        <article class="pokemon-card ${borderClass}" data-cid="${escapeHtml(c.id)}" style="cursor:pointer;">
          <div class="card-top">
            <span class="anime-badge ${animeId}" style="font-size:0.72rem; padding:0.15rem 0.5rem;">${escapeHtml(animeName)}</span>
            <span class="card-tier-badge ${tierClass}">${tier} TIER</span>
          </div>

          <div class="card-img-wrap">
            <div class="card-img-bg"></div>
            <img src="${c.image}" alt="${escapeHtml(c.name)}" loading="lazy" onerror="this.onerror=null; this.src='${fallbackSrc}';">
          </div>

          <div class="card-info">
            <h2 class="pokemon-name" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</h2>
            <p class="pokemon-category">${escapeHtml(c.category || c.species || 'Fighter')} &bull; ${escapeHtml(c.rarity || 'Elite')}</p>
            ${formBadge}
          </div>

          <div class="card-metrics">
            <div class="metric-col">
              <span class="metric-label">Power Rating</span>
              <span class="metric-value metric-power">${pr}</span>
            </div>
            <div class="metric-col">
              <span class="metric-label">Canonical BST</span>
              <span class="metric-value metric-auction" style="color:#f59e0b;">⭐ ${bst}</span>
            </div>
          </div>

          ${techniques ? `<div style="display:flex; flex-wrap:wrap; gap:0.25rem; margin-top:0.5rem; justify-content:center;">${techniques}</div>` : ''}
        </article>
      `;
    });

    grid.innerHTML = html;

    // Attach click for inspection modal
    grid.querySelectorAll('.pokemon-card').forEach(card => {
      card.addEventListener('click', () => {
        const cid = card.dataset.cid;
        const char = characters.find(x => x.id === cid);
        if (char) this.openDetailModal(char);
      });
    });
  },

  openDetailModal(char) {
    const modalBackdrop = document.getElementById('modal-backdrop');
    const modalContent = document.getElementById('modal-content');
    if (!modalBackdrop || !modalContent) return;

    const tier = char.power_tier || char.tier || 'B';
    const tierClass = `tier-${tier.replace('+', '-plus')}`;
    const fallbackSrc = `/api/avatar/${char.id || char.name.toLowerCase().replace(/\\s+/g, '_')}`;
    const pr = Number(char.power_rating || 50).toFixed(1);
    const bst = char.canonical_bst || char.bst || 500;
    const st = char.stats || {};

    let statsBarsHtml = '';
    const statEntries = Object.entries(st);
    if (statEntries.length > 0) {
      statsBarsHtml = statEntries.map(([k, v]) => {
        const pct = Math.min(100, Math.round((v / 255) * 100));
        const label = k.replace(/_/g, ' ').toUpperCase();
        return `
          <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.4rem; font-size:0.8rem;">
            <span style="width:90px; color:#94a3b8; text-transform:uppercase;">${label}</span>
            <div style="flex:1; height:8px; background:rgba(255,255,255,0.08); border-radius:4px; overflow:hidden;">
              <div style="width:${pct}%; height:100%; background:linear-gradient(90deg, #38bdf8, #818cf8);"></div>
            </div>
            <span style="width:40px; font-weight:700; text-align:right; font-family:'JetBrains Mono';">${v}</span>
          </div>
        `;
      }).join('');
    }

    const techList = (char.techniques || char.abilities || []).map(t => 
      `<span style="display:inline-block; background:rgba(56,189,248,0.12); color:#38bdf8; border:1px solid rgba(56,189,248,0.3); padding:0.25rem 0.6rem; border-radius:6px; font-size:0.8rem; margin:0.2rem;">${escapeHtml(t)}</span>`
    ).join(' ');

    const formsList = (char.forms || []).map(f =>
      `<div style="display:flex; justify-content:space-between; padding:0.4rem 0.6rem; background:rgba(255,255,255,0.03); border-radius:6px; margin-bottom:0.3rem; font-size:0.82rem;">
        <span style="color:#f59e0b; font-weight:600;">⚡ ${escapeHtml(f.form_name)}</span>
        <span>BST: <strong>${f.canonical_bst || f.bst || '—'}</strong> &bull; PR: <strong style="color:#38bdf8;">${f.power_rating ? Number(f.power_rating).toFixed(1) : '—'}</strong></span>
      </div>`
    ).join('');

    const altNames = (char.alt_names && char.alt_names.length)
      ? char.alt_names.slice(0, 5).map(a => `<span style="background:rgba(255,255,255,0.06); padding:0.15rem 0.5rem; border-radius:4px; font-size:0.75rem; color:#cbd5e1;">${escapeHtml(a)}</span>`).join(' ')
      : '';

    const associatedAnimeList = (char.associated_anime && char.associated_anime.length)
      ? char.associated_anime.slice(0, 6).map(a => `<span style="background:rgba(56,189,248,0.1); border:1px solid rgba(56,189,248,0.25); color:#38bdf8; padding:0.2rem 0.5rem; border-radius:4px; font-size:0.75rem;">${escapeHtml(a.title || a)}</span>`).join(' ')
      : '';

    const bio = char.description || char.lore || '';
    const sourceLink = char.source_url ? `<a href="${char.source_url}" target="_blank" rel="noopener" style="color:#38bdf8; text-decoration:underline; font-size:0.8rem; margin-left:0.5rem;">🔗 View on Source Database</a>` : '';

    modalContent.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:1.1rem; max-height:80vh; overflow-y:auto; padding-right:0.5rem;">
        <div style="display:flex; gap:1.25rem; align-items:center; flex-wrap:wrap;">
          <div style="width:130px; height:130px; background:rgba(255,255,255,0.03); border-radius:12px; display:flex; align-items:center; justify-content:center; padding:0.5rem; border:1px solid rgba(255,255,255,0.1);">
            <img src="${char.image}" alt="${escapeHtml(char.name)}" style="max-width:100%; max-height:100%; object-fit:contain;" onerror="this.onerror=null; this.src='${fallbackSrc}';">
          </div>
          <div style="flex:1; min-width:240px;">
            <div style="display:flex; gap:0.4rem; margin-bottom:0.35rem; align-items:center; flex-wrap:wrap;">
              <span class="anime-badge ${char.anime_id || ''}">${escapeHtml(char.anime_name || 'Anime')}</span>
              <span class="card-tier-badge ${tierClass}">${tier} TIER</span>
              <span style="font-size:0.78rem; color:#94a3b8;">${escapeHtml(char.gender || 'Unknown')} &bull; ${escapeHtml(char.species || 'Entity')}</span>
            </div>
            <h2 style="font-size:1.6rem; font-weight:900; color:#f8fafc; margin-bottom:0.15rem;">${escapeHtml(char.name)}</h2>
            ${char.native_name ? `<div style="font-size:0.9rem; color:#94a3b8; font-weight:600; margin-bottom:0.35rem;">${escapeHtml(char.native_name)}</div>` : ''}
            
            <div style="display:flex; gap:1.25rem; margin-top:0.4rem; align-items:center;">
              <div>
                <span style="font-size:0.7rem; color:#94a3b8; text-transform:uppercase;">Game Power Rating</span>
                <div style="font-size:1.3rem; font-weight:900; color:#38bdf8;">${pr} <span style="font-size:0.7rem; color:#94a3b8; font-weight:normal;">[Game Estimate]</span></div>
              </div>
              <div>
                <span style="font-size:0.7rem; color:#94a3b8; text-transform:uppercase;">BST / Prominence</span>
                <div style="font-size:1.3rem; font-weight:900; color:#f59e0b;">⭐ ${bst}</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Factual Info Strip -->
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:0.5rem; background:rgba(255,255,255,0.02); padding:0.6rem 0.8rem; border-radius:8px; border:1px solid rgba(255,255,255,0.05); font-size:0.78rem;">
          <div><strong style="color:#94a3b8;">Age:</strong> ${escapeHtml(char.age || 'Unknown')}</div>
          <div><strong style="color:#94a3b8;">Birthday:</strong> ${escapeHtml(char.birthday || 'Unknown')}</div>
          <div><strong style="color:#94a3b8;">Favourites:</strong> ${char.favourites ? Number(char.favourites).toLocaleString() : '—'}</div>
          <div><strong style="color:#94a3b8;">Source:</strong> ${escapeHtml(char.source || 'Database')} ${sourceLink}</div>
        </div>

        ${altNames ? `
          <div>
            <h4 style="font-size:0.8rem; color:#94a3b8; text-transform:uppercase; margin-bottom:0.3rem;">Alternative Names</h4>
            <div style="display:flex; flex-wrap:wrap; gap:0.3rem;">${altNames}</div>
          </div>
        ` : ''}

        ${associatedAnimeList ? `
          <div>
            <h4 style="font-size:0.8rem; color:#94a3b8; text-transform:uppercase; margin-bottom:0.3rem;">Discovered Anime & Media Appearances</h4>
            <div style="display:flex; flex-wrap:wrap; gap:0.35rem;">${associatedAnimeList}</div>
          </div>
        ` : ''}

        ${bio ? `
          <div>
            <h4 style="font-size:0.8rem; color:#94a3b8; text-transform:uppercase; margin-bottom:0.3rem;">Biography & Description</h4>
            <div style="font-size:0.82rem; line-height:1.55; color:#cbd5e1; background:rgba(255,255,255,0.02); padding:0.75rem 1rem; border-radius:8px; border-left:3px solid #38bdf8;">
              ${escapeHtml(bio)}
            </div>
          </div>
        ` : ''}

        <div>
          <h3 style="font-size:0.88rem; color:#cbd5e1; margin-bottom:0.4rem; text-transform:uppercase; letter-spacing:0.5px;">Combat Balance & Base Attributes</h3>
          <div style="background:rgba(0,0,0,0.25); padding:0.75rem; border-radius:8px; border:1px solid rgba(255,255,255,0.06);">
            ${statsBarsHtml || '<div style="color:#94a3b8; font-size:0.8rem;">Standard competitive combat ratings applied based on franchise prominence.</div>'}
          </div>
          <div style="font-size:0.72rem; color:#f59e0b; background:rgba(245,158,11,0.08); border:1px solid rgba(245,158,11,0.25); padding:0.4rem 0.6rem; border-radius:6px; margin-top:0.5rem;">
            ⚖️ <strong>Game Combat Rating:</strong> Estimated game value for multiplayer bidding arena balance. Official anime narrative/canonical facts are preserved above.
          </div>
        </div>

        ${techList ? `
          <div>
            <h3 style="font-size:0.88rem; color:#cbd5e1; margin-bottom:0.4rem; text-transform:uppercase; letter-spacing:0.5px;">Signature Techniques & Abilities</h3>
            <div style="display:flex; flex-wrap:wrap; gap:0.3rem;">${techList}</div>
          </div>
        ` : ''}

        ${formsList ? `
          <div>
            <h3 style="font-size:0.88rem; color:#f59e0b; margin-bottom:0.4rem; text-transform:uppercase; letter-spacing:0.5px;">Transformations & Alternate Forms</h3>
            ${formsList}
          </div>
        ` : ''}
      </div>
    `;

    modalBackdrop.classList.add('active');
  }
};

window.animeDatabaseModule = animeDatabaseModule;

// ============================================================================
// PHASE 3: FRONTEND BATTLE SEQUENCE PLAYBACK & ANIMATIONS
// ============================================================================
function _resolveBattleArt(snap, teamRoster) {
  if (snap && snap.image) return snap.image;
  if (snap && Array.isArray(teamRoster)) {
    const found = teamRoster.find(c => c.id === snap.id || c.name === snap.name);
    if (found && found.image) return found.image;
  }
  if (snap && snap.id && String(snap.id).startsWith('pkmn_')) {
    const pid = String(snap.id).split('_')[1];
    return `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/${pid}.png`;
  }
  return snap ? `/api/avatar/${encodeURIComponent(snap.id || snap.name || 'default')}` : '';
}

function _updateBattleFighterCard(side, snap, trainerName, teamRoster, prevName, remainingCount) {
  const card = document.getElementById(`battle-fighter-${side}`);
  const trainerEl = document.getElementById(`battle-player-${side}-name`);
  const artEl = document.getElementById(`battle-art-${side}`);
  const nameEl = document.getElementById(`battle-char-${side}-name`);
  const badgesEl = document.getElementById(`battle-badges-${side}`);
  const hpFill = document.getElementById(`battle-hp-fill-${side}`);
  const hpText = document.getElementById(`battle-hp-text-${side}`);
  const statusEl = document.getElementById(`battle-status-${side}`);
  const dotsEl = document.getElementById(`battle-team-${side}-dots`);

  if (trainerEl) trainerEl.textContent = trainerName || 'Trainer';
  if (dotsEl && Array.isArray(teamRoster)) {
    const total = teamRoster.length;
    const alive = typeof remainingCount === 'number' ? remainingCount : total;
    dotsEl.innerHTML = Array.from({ length: total }, (_, i) =>
      `<span class="dot ${i < alive ? '' : 'fainted'}"></span>`
    ).join('');
  }
  if (!snap) return;

  if (nameEl) nameEl.textContent = snap.name || 'Combatant';
  if (artEl) artEl.src = _resolveBattleArt(snap, teamRoster);

  if (badgesEl) {
    const types = Array.isArray(snap.types) ? snap.types : [];
    const sysTag = snap.system ? `<span class="badge">${escapeHtml(snap.system.toUpperCase())}</span>` : '';
    const typeTags = types.map(t => `<span class="badge">${escapeHtml(t)}</span>`).join('');
    badgesEl.innerHTML = sysTag + typeTags;
  }

  const maxHp = Math.max(1, snap.max_hp || 100);
  const curHp = Math.max(0, snap.current_hp ?? maxHp);
  const pct = Math.max(0, Math.min(100, Math.round((curHp / maxHp) * 100)));
  if (hpFill) {
    hpFill.style.width = `${pct}%`;
    hpFill.classList.remove('hp-mid', 'hp-low');
    if (pct <= 25) hpFill.classList.add('hp-low');
    else if (pct <= 55) hpFill.classList.add('hp-mid');
  }
  if (hpText) hpText.textContent = `${curHp} / ${maxHp} HP (${pct}%)`;

  if (statusEl) {
    if (snap.status) {
      statusEl.style.display = 'inline-block';
      statusEl.textContent = snap.status;
      _triggerBattleAnim(`battle-fighter-${side}`, 'anim-status');
    } else {
      statusEl.style.display = 'none';
    }
  }

  if (card) {
    card.classList.remove('anim-faint', 'anim-switch');
    if (snap.fainted || curHp <= 0) {
      card.classList.add('anim-faint');
    } else if (prevName && prevName !== snap.name) {
      card.classList.add('anim-switch');
    }
  }
}

function _showDamagePopup(side, dmg, isCrit, eff) {
  const pop = document.getElementById(`battle-dmg-pop-${side}`);
  if (!pop || !dmg) return;
  let label = `-${dmg}`;
  pop.classList.remove('crit', 'super', 'anim-dmg-float');
  if (isCrit) {
    label += ' CRIT!';
    pop.classList.add('crit');
  } else if (eff > 1.0) {
    label += ' SUPER!';
    pop.classList.add('super');
  }
  pop.textContent = label;
  void pop.offsetWidth;
  pop.classList.add('anim-dmg-float');
}

function _triggerBattleAnim(elementId, cls) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}

async function playBattleSequence(battleResults, finishData) {
  switchArenaScreen('arena-battle');
  const formatBadge = document.getElementById('battle-format-badge');
  const matchCounter = document.getElementById('battle-match-counter');
  const turnCounter = document.getElementById('battle-turn-counter');
  const actionBanner = document.getElementById('battle-action-banner');
  const logEl = document.getElementById('battle-event-log');
  const logCard = document.getElementById('battle-log-card');
  const pauseBtn = document.getElementById('pause-battle-btn');
  const speedBtn = document.getElementById('speed-battle-btn');
  const toggleLogBtn = document.getElementById('toggle-battle-log-btn');
  const skipMatchBtn = document.getElementById('skip-match-btn');
  const skipBtn = document.getElementById('skip-battle-btn');

  if (formatBadge) formatBadge.textContent = (battleResults.format || 'BATTLE').replace('_', ' ').toUpperCase();
  if (logEl) logEl.innerHTML = '';

  let isPaused = false;
  let speedMult = 1;
  let skipCurrentMatch = false;

  const finishPlayback = () => {
    soundFX.victory();
    switchArenaScreen('arena-results');
    renderLeaderboard(finishData.leaderboard, battleResults);
  };

  if (pauseBtn) {
    pauseBtn.textContent = '⏸️ Pause';
    pauseBtn.onclick = () => {
      isPaused = !isPaused;
      pauseBtn.textContent = isPaused ? '▶️ Resume' : '⏸️ Pause';
    };
  }
  if (speedBtn) {
    speedBtn.textContent = '⏩ 1x';
    speedBtn.onclick = () => {
      speedMult = speedMult === 1 ? 2 : (speedMult === 2 ? 4 : 1);
      speedBtn.textContent = `⏩ ${speedMult}x`;
    };
  }
  if (toggleLogBtn && logCard) {
    toggleLogBtn.onclick = () => {
      logCard.style.display = logCard.style.display === 'none' ? 'block' : 'none';
    };
  }
  if (skipMatchBtn) {
    skipMatchBtn.onclick = () => { skipCurrentMatch = true; };
  }
  if (skipBtn) {
    skipBtn.onclick = () => {
      gameState.battleSkipped = true;
      finishPlayback();
    };
  }

  const matches = battleResults.matches || [];
  for (let mIdx = 0; mIdx < matches.length; mIdx++) {
    if (gameState.battleSkipped) return;
    skipCurrentMatch = false;
    const match = matches[mIdx];
    if (matchCounter) matchCounter.textContent = `Match ${mIdx + 1} / ${matches.length}`;

    let prevA = null;
    let prevB = null;
    const turns = match.turn_log || [];

    if (turns.length === 0) {
      if (actionBanner) actionBanner.textContent = `${match.player_a_name} vs ${match.player_b_name}: ${match.reason}`;
      if (logEl) {
        const div = document.createElement('div');
        div.className = 'battle-log-entry';
        div.textContent = `Match ${mIdx + 1}: ${match.player_a_name} vs ${match.player_b_name} — ${match.reason}`;
        logEl.prepend(div);
      }
      await new Promise(r => setTimeout(r, Math.round(600 / speedMult)));
      continue;
    }

    const baseMs = turns.length > 20 ? 220 : 420;
    for (let tIdx = 0; tIdx < turns.length; tIdx++) {
      if (gameState.battleSkipped) return;
      if (skipCurrentMatch) break;
      while (isPaused && !gameState.battleSkipped && !skipCurrentMatch) {
        await new Promise(r => setTimeout(r, 120));
      }

      const t = turns[tIdx];
      if (turnCounter) turnCounter.textContent = `Turn ${t.turn}`;

      _updateBattleFighterCard('a', t.active_a, match.player_a_name, match.player_a_team, prevA, t.remaining_a);
      _updateBattleFighterCard('b', t.active_b, match.player_b_name, match.player_b_team, prevB, t.remaining_b);
      prevA = t.active_a ? t.active_a.name : prevA;
      prevB = t.active_b ? t.active_b.name : prevB;

      const evText = (t.events || []).join(' • ');
      if (actionBanner && evText) actionBanner.textContent = evText;

      const details = t.action_details || [];
      for (const d of details) {
        if (d.event_type === 'transform') {
          _triggerBattleAnim(`battle-fighter-${d.side}`, 'anim-transform');
        } else if (d.event_type === 'attack') {
          const atkCls = d.side === 'a' ? 'anim-attack-left' : 'anim-attack-right';
          _triggerBattleAnim(`battle-fighter-${d.side}`, atkCls);
          if (d.category === 'elemental') _triggerBattleAnim(`battle-fighter-${d.side}`, 'anim-elemental');
          if (d.category === 'ranged') _triggerBattleAnim(`battle-fighter-${d.side}`, 'anim-ranged');
          _triggerBattleAnim(`battle-fighter-${d.target_side}`, 'anim-hit');
          _showDamagePopup(d.target_side, d.damage, d.is_crit, d.effectiveness || 1);
        }
      }

      if (logEl && evText) {
        const entry = document.createElement('div');
        entry.className = 'battle-log-entry';
        entry.textContent = `[M${mIdx + 1} T${t.turn}] ${evText}`;
        logEl.prepend(entry);
        if (logEl.children.length > 40) logEl.lastChild.remove();
      }

      await new Promise(r => setTimeout(r, Math.max(60, Math.round(baseMs / speedMult))));
    }
  }

  if (!gameState.battleSkipped) {
    await new Promise(r => setTimeout(r, 450));
    finishPlayback();
  }
}

// ============================================================================
// PHASE 5: INTERACTIVE BATTLE CONTROL HANDLERS
// ============================================================================
let _battlePromptTimer = null;

function resetBattleUI() {
  if (_battlePromptTimer) {
    clearInterval(_battlePromptTimer);
    _battlePromptTimer = null;
  }
  gameState.pendingBattleResults = null;
  gameState.battleSkipped = false;

  const ctrlPanel = document.getElementById('battle-control-panel');
  if (ctrlPanel) ctrlPanel.style.display = 'none';
  for (const id of ['battle-event-log', 'battle-moves-grid', 'battle-switch-row', 'battle-transform-row', 'battle-badges-a', 'battle-badges-b', 'battle-team-a-dots', 'battle-team-b-dots']) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '';
  }
  const turnCounter = document.getElementById('battle-turn-counter');
  if (turnCounter) turnCounter.textContent = 'Turn 0';
  const matchCounter = document.getElementById('battle-match-counter');
  if (matchCounter) matchCounter.textContent = 'Match 1 / 1';
  const actionBanner = document.getElementById('battle-action-banner');
  if (actionBanner) actionBanner.textContent = 'Preparing combatants...';

  for (const side of ['a', 'b']) {
    const card = document.getElementById(`battle-fighter-${side}`);
    if (card) card.classList.remove('anim-faint', 'anim-switch', 'anim-hit', 'anim-attack-left', 'anim-attack-right', 'anim-transform', 'anim-elemental', 'anim-ranged', 'anim-status');
    const nameEl = document.getElementById(`battle-char-${side}-name`);
    if (nameEl) nameEl.textContent = 'Loading...';
    const artEl = document.getElementById(`battle-art-${side}`);
    if (artEl) artEl.src = '';
    const hpFill = document.getElementById(`battle-hp-fill-${side}`);
    if (hpFill) {
      hpFill.style.width = '100%';
      hpFill.classList.remove('hp-mid', 'hp-low');
    }
    const hpText = document.getElementById(`battle-hp-text-${side}`);
    if (hpText) hpText.textContent = 'HP';
    const statusEl = document.getElementById(`battle-status-${side}`);
    if (statusEl) statusEl.style.display = 'none';
  }
}

function renderInteractiveTurnPrompt(promptData) {
  switchArenaScreen('arena-battle');
  if (promptData.match_id) gameState.currentMatchId = promptData.match_id;

  // Immediately render active combatants for the current match (prevents stale previous-match UI!)
  const mySide = promptData.side === 'b' ? 'b' : 'a';
  const oppSide = mySide === 'a' ? 'b' : 'a';
  const myTrainer = mySide === 'a' ? (promptData.player_a_name || gameState.myName) : (promptData.player_b_name || gameState.myName);
  const oppTrainer = oppSide === 'a' ? (promptData.player_a_name || 'Opponent') : (promptData.player_b_name || 'Opponent');
  if (promptData.your_active) {
    _updateBattleFighterCard(mySide, promptData.your_active, myTrainer, null, null, promptData.your_remaining);
  }
  if (promptData.opponent_active) {
    _updateBattleFighterCard(oppSide, promptData.opponent_active, oppTrainer, null, null, promptData.opponent_remaining);
  }
  const panel = document.getElementById('battle-control-panel');
  const statusEl = document.getElementById('battle-turn-status');
  const timerEl = document.getElementById('battle-action-timer');
  const movesGrid = document.getElementById('battle-moves-grid');
  const switchRow = document.getElementById('battle-switch-row');
  const transformRow = document.getElementById('battle-transform-row');
  const turnCounter = document.getElementById('battle-turn-counter');

  if (turnCounter) turnCounter.textContent = `Turn ${promptData.turn + 1}`;
  if (panel) panel.style.display = 'block';
  if (statusEl) statusEl.textContent = promptData.opponent_submitted ? '⚡ Opponent ready! Your Turn' : '⚔️ Your Turn — Select Action';

  if (_battlePromptTimer) clearInterval(_battlePromptTimer);
  let secs = Math.round(promptData.timeout_seconds || 20);
  if (timerEl) timerEl.textContent = `⏱️ ${secs}s`;
  _battlePromptTimer = setInterval(() => {
    secs = Math.max(0, secs - 1);
    if (timerEl) timerEl.textContent = `⏱️ ${secs}s`;
    if (secs <= 0) clearInterval(_battlePromptTimer);
  }, 1000);

  if (movesGrid) {
    movesGrid.innerHTML = '';
    (promptData.available_moves || []).forEach(m => {
      const btn = document.createElement('button');
      btn.className = 'battle-move-btn';
      const ppInfo = m.pp !== null && m.pp !== undefined ? `PP ${m.pp}/${m.max_pp || m.pp}` : m.category;
      btn.innerHTML = `<strong>${escapeHtml(m.name)}</strong><div style="font-size:0.78rem; color:#94a3b8;">${escapeHtml(m.type)} &bull; ${escapeHtml(String(ppInfo))}</div>`;
      btn.onclick = () => {
        gameState.ws.send(JSON.stringify({
          action: 'submit_battle_action',
          data: { action_type: 'attack', move_id: m.id, match_id: gameState.currentMatchId }
        }));
      };
      movesGrid.appendChild(btn);
    });
  }

  if (switchRow) {
    switchRow.innerHTML = '';
    (promptData.available_switches || []).forEach(sw => {
      const btn = document.createElement('button');
      btn.className = 'btn btn-outline btn-sm battle-switch-btn';
      btn.textContent = `🔄 ${sw.name} (${sw.current_hp}/${sw.max_hp})`;
      btn.onclick = () => {
        gameState.ws.send(JSON.stringify({
          action: 'submit_battle_action',
          data: { action_type: 'switch', switch_index: sw.index, match_id: gameState.currentMatchId }
        }));
      };
      switchRow.appendChild(btn);
    });
  }

  if (transformRow) {
    transformRow.innerHTML = '';
    (promptData.available_transformations || []).forEach(tf => {
      const btn = document.createElement('button');
      btn.className = 'btn btn-primary btn-sm battle-transform-btn';
      btn.textContent = `✨ Transform: ${tf.name}`;
      btn.onclick = () => {
        gameState.ws.send(JSON.stringify({
          action: 'submit_battle_action',
          data: { action_type: 'transform', transformation_id: tf.id, match_id: gameState.currentMatchId }
        }));
      };
      transformRow.appendChild(btn);
    });
  }
}

function applyResolvedInteractiveTurn(t, nameA, nameB) {
  if (_battlePromptTimer) clearInterval(_battlePromptTimer);
  _updateBattleFighterCard('a', t.active_a, nameA, null, null, t.remaining_a);
  _updateBattleFighterCard('b', t.active_b, nameB, null, null, t.remaining_b);
  const actionBanner = document.getElementById('battle-action-banner');
  const logEl = document.getElementById('battle-event-log');
  const evText = (t.events || []).join(' • ');
  if (actionBanner && evText) actionBanner.textContent = evText;
  if (logEl && evText) {
    const entry = document.createElement('div');
    entry.className = 'battle-log-entry';
    entry.textContent = `[T${t.turn}] ${evText}`;
    logEl.prepend(entry);
  }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initArena);
