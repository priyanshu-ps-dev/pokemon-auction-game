/**
 * Pokemon Auction Arena: Real-Time Multiplayer Client Controller
 * ==============================================================
 * Handles WebSocket communication, room-specific purse management,
 * authoritative timer rendering, flexible bidding (any valid amount),
 * informed character profiles during bidding, and detailed final results.
 */

const gameState = {
  ws: null,
  sessionId: sessionStorage.getItem("pkmn_auction_session_id"),
  reconnectToken: sessionStorage.getItem("pkmn_auction_reconnect_token"),
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
let audioCtx;
window.addEventListener('pointerdown', () => {
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (AudioContext) audioCtx = new AudioContext();
}, { once: true });

function playTone(freq, type, duration, delay = 0, gainLevel = 0.15) {
  if (!gameState.soundEnabled || !audioCtx) return;
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
let reconnectAttempts = 0;
let reconnectStartedAt = 0;
const connectionStatus = () => document.getElementById('connection-status');

function sendAction(action, data = {}) {
  if (gameState.ws?.readyState !== WebSocket.OPEN) return false;
  gameState.ws.send(JSON.stringify({ action, data }));
  return true;
}

function clearRoomSession() {
  gameState.roomCode = null;
  gameState.sessionId = null;
  gameState.reconnectToken = null;
  gameState.roomState = null;
  for (const key of ['room_code', 'session_id', 'reconnect_token']) {
    sessionStorage.removeItem('pkmn_auction_' + key);
  }
}

function connectWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  gameState.ws = socket;

  socket.onopen = () => {
    reconnectAttempts = 0;
    reconnectStartedAt = 0;
    if (gameState.roomCode && gameState.reconnectToken) {
      sendAction('resume_room', {
        room_code: gameState.roomCode,
        session_id: gameState.sessionId,
        reconnect_token: gameState.reconnectToken
      });
    } else {
      connectionStatus().hidden = true;
    }
  };

  socket.onmessage = ({data}) => {
    const message = JSON.parse(data);
    handleServerMessage(message.type, message.data);
  };

  socket.onclose = ({code}) => {
    if (gameState.ws !== socket) return;
    if (code === 4001) {
      clearRoomSession();
      switchArenaScreen('arena-setup');
    }
    const status = connectionStatus();
    status.hidden = false;
    if (!reconnectStartedAt) reconnectStartedAt = Date.now();
    if (Date.now() - reconnectStartedAt >= 120000) {
      status.textContent = 'Connection lost. Reload to retry.';
      return;
    }
    status.textContent = 'Connection lost. Reconnecting…';
    const delay = Math.min(10000, 400 * 2 ** reconnectAttempts++) + Math.random() * 300;
    setTimeout(connectWebSocket, delay);
  };
}

// Dispatch Incoming Server Messages
function handleServerMessage(type, data) {
  switch (type) {
    case 'room_joined': {
      connectionStatus().hidden = true;
      gameState.roomCode = data.room_code;
      gameState.sessionId = data.session_id;
      gameState.reconnectToken = data.reconnect_token;
      sessionStorage.setItem('pkmn_auction_session_id', data.session_id);
      sessionStorage.setItem('pkmn_auction_reconnect_token', data.reconnect_token);
      gameState.isHost = data.is_host;
      gameState.roomState = data.room_state;
      sessionStorage.setItem('pkmn_auction_room_code', data.room_code);
      const rs = data.room_state || {};
      const status = rs.status || 'LOBBY';
      gameState.currentMatchId = rs.match_id;
      gameState.isWithdrawn = !!rs.players?.find(p => p.session_id === gameState.sessionId)?.is_withdrawn;
      document.getElementById('lobby-chat-messages')?.replaceChildren();
      for (const message of data.chat_history || []) appendChatMessage(message);
      document.getElementById('stage-log-list')?.replaceChildren();
      for (const lot of data.auction_history || []) {
        const name = escapeHtml(lot.character?.name || 'Character');
        const text = lot.winner_name
          ? `${name} sold to ${escapeHtml(lot.winner_name)} for $${lot.winning_bid}`
          : `${name} went unsold`;
        addStageLog(text, lot.winner_name ? 'won' : 'unsold');
      }
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
        if (data.live_progress?.turn_entry) {
          const latest = data.live_progress;
          applyResolvedInteractiveTurn(latest.turn_entry, latest.player_a_name, latest.player_b_name);
        }
      } else if (status === 'GAME_OVER' || status === 'REMATCH_PENDING') {
        switchArenaScreen('arena-results');
        if (data.finish_data) renderLeaderboard(data.finish_data.leaderboard, data.finish_data.battle_results);
      } else {
        updateLobbyUI(rs);
        switchArenaScreen('arena-lobby');
      }
      break;
    }

    case 'resume_error':
      clearRoomSession();
      connectionStatus().hidden = true;
      switchArenaScreen('arena-setup');
      showRoomToast(data.message, 'error');
      break;

    case 'room_state':
      gameState.roomState = data;
      gameState.isHost = !!data.players?.find(p => p.session_id === gameState.sessionId)?.is_host;
      if (data.status === 'LOBBY') {
        if (gameState.roomCode && !document.getElementById('arena-lobby').classList.contains('active')) switchArenaScreen('arena-lobby');
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
      addStageLog(`🔔 Round Started! <strong>${escapeHtml(data.pokemon.name)}</strong> is up for auction!`, 'info');
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
      gameState.isHost = data.new_host_id === gameState.sessionId;
      showRoomToast(data.message || 'Host status transferred.', 'info', 4000);
      addStageLog(`👑 ${escapeHtml(data.message)}`, 'info');
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
      clearRoomSession();
      switchArenaScreen('arena-setup');
      break;

    case 'player_kicked':
      gameState.roomCode = null;
      gameState.isHost = false;
      gameState.isWithdrawn = false;
      gameState.roomState = null;
      clearRoomSession();
      closeLeaveRoomModal();
      closeKickConfirmModal();
      const wModal = document.getElementById('withdraw-modal');
      if (wModal) wModal.style.display = 'none';
      hideRematchModal();
      switchArenaScreen('arena-setup');
      showRoomToast(data.message || 'You have been removed from this room by the host.', 'error', 7000);
      break;

    case 'kick_success':
      showRoomToast(data.message || `${data.target_name || 'Player'} has been removed from the room.`, 'success', 4500);
      if (document.getElementById('arena-stage')?.classList.contains('active')) {
        addStageLog(`🚫 <strong>${escapeHtml(data.target_name || 'Player')}</strong> was removed from the room.`, 'alert');
      }
      break;

    case 'player_left':
      if (data.room_state) {
        gameState.roomState = data.room_state;
        const meInRoom = Array.isArray(data.room_state.players)
          ? data.room_state.players.find(pl => pl.session_id === gameState.sessionId)
          : null;
        if (meInRoom) {
          gameState.isHost = !!meInRoom.is_host;
        }
        if (data.room_state.status === 'LOBBY') {
          updateLobbyUI(data.room_state);
        } else {
          updateStageUI(data.room_state);
        }
      }
      if (document.getElementById('arena-stage')?.classList.contains('active')) {
        addStageLog(
          `🚪 <strong>${escapeHtml(data.player_name || 'A player')}</strong> ${data.kicked ? 'was removed by the host' : 'left the room'}.`,
          'alert'
        );
      }
      break;

    case 'auction_tick':
      if (data.match_id !== gameState.roomState?.match_id || data.round_id !== gameState.roomState?.auction_character_count) break;
      updateTimerDisplay(data.timer_seconds_left);
      if (data.timer_seconds_left <= 3 && data.timer_seconds_left > 0) soundFX.tick();
      break;

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
      addStageLog(`💵 <strong>${escapeHtml(data.highest_bidder_name)}</strong> bid <strong>$${data.current_bid.toLocaleString()}</strong>! Timer reset!`, 'bid');
      break;
    }

    case 'bid_error':
      showBiddingError(data.message);
      break;

    case 'auction_won':
      soundFX.sold();
      addStageLog(`🏆 SOLD! <strong>${escapeHtml(data.winner_name)}</strong> won <strong>${escapeHtml(data.pokemon.name)}</strong> for $${data.winning_bid.toLocaleString()}!`, 'won');
      showShowcaseBanner(`SOLD to ${data.winner_name}!`, `Winning Bid: $${data.winning_bid.toLocaleString()}`);
      updateStageUI(data.room_state);
      break;

    case 'auction_unsold':
      soundFX.unsold();
      addStageLog(`❌ UNSOLD! No bids placed for <strong>${escapeHtml(data.pokemon.name)}</strong>. Removed from match.`, 'unsold');
      showShowcaseBanner(`UNSOLD`, `No bids placed. Next Pokémon arriving...`);
      updateStageUI(data.room_state);
      break;

    case 'room_event':
      addStageLog(`📢 ${escapeHtml(data.message)}`, 'alert');
      break;

    case 'battle_started':
      gameState.roomState = data.room_state;
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
        if (data.is_match_start) {
          const ctrlPanel = document.getElementById('battle-control-panel');
          if (ctrlPanel) ctrlPanel.style.display = 'none';
          const banner = document.getElementById('battle-action-banner');
          if (banner) {
            banner.textContent = `⚔️ Match ${data.match_index} / ${data.total_matches}: ${data.player_a_name} vs ${data.player_b_name}`;
          }
        }
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

    case 'avatar_library_updated':
      applyLocalAvatarManifest(data);
      break;

    case 'avatar_admin_result':
      showAvatarAdminStatus(data.message || '', !!data.success);
      if (data.action === 'upload' && data.success) {
        const fileInp = document.getElementById('avatar-upload-files');
        const nameInp = document.getElementById('avatar-upload-name');
        const strip = document.getElementById('avatar-upload-preview-strip');
        if (fileInp) fileInp.value = '';
        if (nameInp) nameInp.value = '';
        if (strip) strip.innerHTML = '';
      }
      break;

    case 'error':
      if (window.AuctionTicketUI && window.AuctionTicketUI.isOpen()) {
        window.AuctionTicketUI.handleServerError(data.message);
      } else {
        alert(data.message);
      }
      break;
  }
}

// Screen Switcher
function updateStageBackgroundVideo() {
  const video = document.getElementById('landing-bg-video');
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (document.hidden || document.body.classList.contains('in-arena-match') ||
      reducedMotion || navigator.connection?.saveData) {
    video.pause();
    return;
  }
  if (!video.src) video.src = '/assets/landing-video.mp4';
  video.play().catch(() => {});
}

function switchArenaScreen(screenId) {
  document.querySelectorAll('.arena-screen').forEach(s => s.classList.remove('active'));
  const target = document.getElementById(screenId);
  if (target) target.classList.add('active');

  // Close landing modals when transitioning screens
  ['profile-modal-backdrop', 'create-room-modal-backdrop', 'join-room-modal-backdrop'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
  });
  if (window.AuctionTicketUI && screenId !== 'arena-setup') {
    window.AuctionTicketUI.closeAll();
  }

  // Dim background video slightly during active lobby/stage/results
  document.body.classList.toggle('in-arena-match', screenId !== 'arena-setup');
  updateStageBackgroundVideo(screenId, gameState.roomState);
}

// Helper to open/close HUD modals
function openHudModal(backdropId) {
  const el = document.getElementById(backdropId);
  if (el) el.classList.add('active');
}

function closeHudModal(backdropId) {
  const el = document.getElementById(backdropId);
  if (el) el.classList.remove('active');
}

// Initialize Multiplayer Arena UI
function initArena() {
  connectWebSocket();
  setupAvatarPicker();
  setupEventListeners();
  initStageCharacterDex();

  document.addEventListener('visibilitychange', updateStageBackgroundVideo);
  matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', updateStageBackgroundVideo);
  updateStageBackgroundVideo();

  // Load sound setting
  const soundBtn = document.getElementById('sound-toggle-btn');
  if (soundBtn) {
    soundBtn.addEventListener('click', () => {
      gameState.soundEnabled = !gameState.soundEnabled;
      const labelEl = soundBtn.querySelector('.hud-sound-label');
      if (labelEl) {
        labelEl.textContent = gameState.soundEnabled ? 'SOUND ON' : 'SOUND OFF';
      } else {
        soundBtn.textContent = gameState.soundEnabled ? 'SOUND ON' : 'SOUND OFF';
      }
      soundBtn.classList.toggle('active', gameState.soundEnabled);
      soundBtn.classList.toggle('is-muted', !gameState.soundEnabled);
    });
  }

  // Mobile HUD nav toggle
  const mobileToggle = document.getElementById('hud-mobile-toggle');
  const hudNavItems = document.getElementById('hud-nav-items');
  if (mobileToggle && hudNavItems) {
    mobileToggle.addEventListener('click', () => {
      const isOpen = hudNavItems.classList.toggle('mobile-open');
      mobileToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });
  }

  // Top Nav Tab Switcher (Multiplayer Arena)
  const tabArenaBtn = document.getElementById('tab-arena-btn');
  const viewArena = document.getElementById('view-arena');
  if (tabArenaBtn && viewArena) {
    tabArenaBtn.addEventListener('click', () => {
      document.querySelectorAll('.app-view').forEach(v => v.classList.remove('active'));
      viewArena.classList.add('active');
      tabArenaBtn.classList.add('active');
      if (hudNavItems) hudNavItems.classList.remove('mobile-open');
    });
  }

  // Check URL parameters for direct room invitation (?room=CODE)
  const urlParams = new URLSearchParams(window.location.search);
  const inviteCode = urlParams.get('room');
  if (inviteCode) {
    const code = inviteCode.trim().toUpperCase();
    if (window.AuctionTicketUI) {
      window.AuctionTicketUI.openJoin(code);
    }
  }
}

// ============================================================================
// UNIVERSAL LOCAL ANIME AVATAR LIBRARY (Zero External APIs)
// ============================================================================
const avatarLibraryState = {
  characters: [],
  categories: [],
  activeCategory: 'ALL',
  searchQuery: '',
  pendingAvatar: gameState.myAvatar || 'red',
  visibleCount: 48,
  pageSize: 48,
  adminMode: false,
  replaceTargetId: null,
  loaded: false
};

function isCustomAvatarPath(val) {
  return typeof val === 'string' && (val.startsWith('/assets/avatars/') || val.startsWith('assets/avatars/'));
}

function resolveAvatarInfo(avatarVal) {
  if (isCustomAvatarPath(avatarVal)) {
    const norm = avatarVal.startsWith('/') ? avatarVal : '/' + avatarVal;
    const found = avatarLibraryState.characters.find(c => c.image === norm);
    if (found) {
      return {
        isCustom: true,
        id: found.id,
        name: found.name,
        anime: found.anime,
        image: found.image,
        fallback: TRAINER_AVATARS[0]
      };
    }
    // Even if manifest hasn't loaded yet, derive readable fallback from path
    const parts = norm.split('/');
    const fileStem = (parts[parts.length - 1] || 'Avatar').replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ');
    return {
      isCustom: true,
      id: norm,
      name: fileStem,
      anime: 'Anime Character',
      image: norm,
      fallback: TRAINER_AVATARS[0]
    };
  }
  const trainer = TRAINER_AVATARS.find(a => a.id === avatarVal) || TRAINER_AVATARS[0];
  return {
    isCustom: false,
    id: trainer.id,
    name: trainer.name,
    anime: 'Default Trainer',
    color: trainer.color,
    icon: trainer.icon,
    fallback: trainer
  };
}

function renderAvatarBadgeHtml(avatarVal, wrapperClass, altName = 'Avatar') {
  const info = resolveAvatarInfo(avatarVal);
  if (info.isCustom) {
    return `
      <div class="${wrapperClass} custom-avatar-wrap">
        <img src="${escapeHtml(info.image)}" alt="${escapeHtml(altName || info.name)}" class="avatar-portrait-img" loading="lazy"
          onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='flex';">
        <div class="avatar-fallback-circle" style="display:none; background:${info.fallback.color};">${info.fallback.icon}</div>
      </div>
    `;
  }
  return `<div class="${wrapperClass}" style="background:${info.color};">${info.icon}</div>`;
}

function renderAvatarInlineHtml(avatarVal, altName = 'Avatar') {
  const info = resolveAvatarInfo(avatarVal);
  if (info.isCustom) {
    return `
      <span class="avatar-inline-wrap">
        <img src="${escapeHtml(info.image)}" alt="${escapeHtml(altName || info.name)}" class="avatar-inline-img" loading="lazy"
          onerror="this.style.display='none'; if(this.nextElementSibling) this.nextElementSibling.style.display='inline';">
        <span style="display:none;">${info.fallback.icon}</span>
      </span>
    `;
  }
  return `<span style="font-size:1.2rem;">${info.icon}</span>`;
}

async function loadLocalAvatarManifest() {
  try {
    const res = await fetch('/assets/avatars/manifest.json?t=' + Date.now());
    if (!res.ok) throw new Error('Manifest load failed');
    const data = await res.json();
    applyLocalAvatarManifest(data);
  } catch (err) {
    console.warn('[AvatarLibrary] Using default 12 trainers:', err);
    applyLocalAvatarManifest({ characters: [], categories: [] });
  }
}

function applyLocalAvatarManifest(data) {
  avatarLibraryState.characters = Array.isArray(data.characters) ? data.characters : [];
  avatarLibraryState.categories = Array.isArray(data.categories) ? data.categories : [];
  avatarLibraryState.loaded = true;

  const badge = document.getElementById('avatar-lib-total-badge');
  if (badge) {
    badge.textContent = `${avatarLibraryState.characters.length} Characters`;
  }
  const adminCount = document.getElementById('avatar-admin-count');
  if (adminCount) {
    adminCount.textContent = String(avatarLibraryState.characters.length);
  }

  renderAvatarCategoryFilters();
  renderAvatarLibraryGrid();
  updateAvatarPreview(avatarLibraryState.pendingAvatar);
  renderAvatarAdminList();
}

function renderAvatarCategoryFilters() {
  const container = document.getElementById('avatar-category-filters');
  if (!container) return;
  container.innerHTML = '';

  const totalCount = avatarLibraryState.characters.length;
  const pills = [
    { key: 'ALL', label: `ALL CHARACTERS (${totalCount})` }
  ];

  // Only show populated anime categories
  avatarLibraryState.categories.forEach(cat => {
    if (cat.count > 0) {
      pills.push({ key: cat.name, label: `${cat.name.toUpperCase()} (${cat.count})` });
    }
  });

  pills.forEach(p => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `avatar-cat-pill ${avatarLibraryState.activeCategory === p.key ? 'active' : ''}`;
    btn.textContent = p.label;
    btn.addEventListener('click', () => {
      avatarLibraryState.activeCategory = p.key;
      avatarLibraryState.visibleCount = avatarLibraryState.pageSize;
      renderAvatarCategoryFilters();
      renderAvatarLibraryGrid();
    });
    container.appendChild(btn);
  });
}

function getFilteredAvatarEntries() {
  const q = avatarLibraryState.searchQuery.trim().toLowerCase();
  const cat = avatarLibraryState.activeCategory;
  const entries = [];

  avatarLibraryState.characters.forEach(ch => {
    if (cat !== 'ALL' && ch.anime !== cat) return;
    if (q && !ch.name.toLowerCase().includes(q) && !ch.anime.toLowerCase().includes(q)) return;
    entries.push({
      isCustom: true,
      value: ch.image,
      id: ch.id,
      name: ch.name,
      anime: ch.anime,
      image: ch.image
    });
  });

  return entries;
}

function renderAvatarLibraryGrid() {
  const grid = document.getElementById('avatar-library-grid');
  const loadMoreWrap = document.getElementById('avatar-load-more-wrap');
  if (!grid) return;
  grid.innerHTML = '';

  const entries = getFilteredAvatarEntries();
  if (entries.length === 0) {
    grid.innerHTML = `
      <div class="avatar-empty-state">
        <div class="avatar-empty-icon">🔍</div>
        <h4>No matching anime character found</h4>
        <p>Try a different name or import local character portraits into <code>public/assets/avatars/</code>.</p>
      </div>
    `;
    if (loadMoreWrap) loadMoreWrap.style.display = 'none';
    return;
  }

  const slice = entries.slice(0, avatarLibraryState.visibleCount);
  slice.forEach(item => {
    const isSelected = avatarLibraryState.pendingAvatar === item.value;
    const card = document.createElement('button');
    card.type = 'button';
    card.className = `avatar-lib-card ${isSelected ? 'selected' : ''}`;
    card.dataset.avatarVal = item.value;

    const mediaHtml = item.isCustom
      ? `<img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.name)}" class="avatar-lib-thumb" loading="lazy"
           onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
         <div class="avatar-lib-fallback" style="display:none; background:#1e293b;">⚡</div>`
      : `<div class="avatar-lib-trainer-box" style="background:${item.color};">${item.icon}</div>`;

    card.innerHTML = `
      <div class="avatar-lib-media">
        ${mediaHtml}
        <span class="avatar-lib-check" aria-hidden="true">✓</span>
      </div>
      <div class="avatar-lib-info">
        <div class="avatar-lib-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
        <div class="avatar-lib-franchise">${escapeHtml(item.anime)}</div>
      </div>
    `;

    card.addEventListener('click', () => {
      avatarLibraryState.pendingAvatar = item.value;
      grid.querySelectorAll('.avatar-lib-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      updateAvatarPreview(item.value);
    });

    grid.appendChild(card);
  });

  if (loadMoreWrap) {
    loadMoreWrap.style.display = entries.length > avatarLibraryState.visibleCount ? 'flex' : 'none';
  }
}

function updateAvatarPreview(avatarVal) {
  const frame = document.getElementById('preview-avatar-media');
  const nameEl = document.getElementById('preview-char-name');
  const animeEl = document.getElementById('preview-char-anime');
  const statusEl = document.getElementById('preview-char-status');
  if (!frame || !nameEl || !animeEl) return;

  const info = resolveAvatarInfo(avatarVal);
  if (info.isCustom) {
    frame.innerHTML = `
      <img src="${escapeHtml(info.image)}" alt="${escapeHtml(info.name)}" class="avatar-preview-img"
        onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
      <div class="avatar-preview-fallback" style="display:none; background:${info.fallback.color};">${info.fallback.icon}</div>
    `;
  } else {
    frame.innerHTML = `<div class="avatar-preview-trainer" style="background:${info.color};">${info.icon}</div>`;
  }

  nameEl.textContent = info.name;
  animeEl.textContent = info.anime;
  if (statusEl) {
    const isActive = avatarVal === gameState.myAvatar;
    statusEl.textContent = isActive ? 'ACTIVE IDENTITY' : 'SELECTED — CLICK CONFIRM';
    statusEl.classList.toggle('is-active', isActive);
  }
}

function showAvatarAdminStatus(msg, isSuccess) {
  const box = document.getElementById('avatar-admin-status');
  if (!box) return;
  box.textContent = msg;
  box.className = `avatar-admin-status ${isSuccess ? 'is-success' : 'is-error'}`;
  box.style.display = 'block';
}

function renderAvatarAdminList() {
  const list = document.getElementById('avatar-admin-list');
  if (!list) return;
  const searchEl = document.getElementById('avatar-admin-search');
  const q = searchEl ? searchEl.value.trim().toLowerCase() : '';
  const items = avatarLibraryState.characters.filter(c =>
    !q || c.name.toLowerCase().includes(q) || c.anime.toLowerCase().includes(q)
  );

  if (items.length === 0) {
    list.innerHTML = '<div class="avatar-admin-empty">No imported portraits yet. Upload images on the left or place files into <code>public/assets/avatars/&lt;franchise&gt;/</code>.</div>';
    return;
  }

  list.innerHTML = '';
  items.slice(0, 100).forEach(ch => {
    const row = document.createElement('div');
    row.className = 'avatar-admin-row';
    row.innerHTML = `
      <img src="${escapeHtml(ch.image)}" alt="${escapeHtml(ch.name)}" class="avatar-admin-thumb" loading="lazy"
        onerror="this.src='/api/avatar/${escapeHtml(ch.id)}'">
      <div class="avatar-admin-meta">
        <div class="avatar-admin-name">${escapeHtml(ch.name)}</div>
        <div class="avatar-admin-anime">${escapeHtml(ch.anime)}</div>
      </div>
      <div class="avatar-admin-row-actions">
        <button type="button" class="avatar-mini-btn" data-action="edit" title="Edit Name / Category">✏️</button>
        <button type="button" class="avatar-mini-btn" data-action="replace" title="Replace Portrait">🖼️</button>
        <button type="button" class="avatar-mini-btn danger" data-action="delete" title="Remove">🗑️</button>
      </div>
    `;

    row.querySelector('[data-action="edit"]').addEventListener('click', () => {
      const newName = prompt('Edit Character Name:', ch.name);
      if (newName === null) return;
      const newAnime = prompt('Edit Anime Franchise (e.g. One Piece, Naruto, Pokémon, Dragon Ball, Bleach, Jujutsu Kaisen, Demon Slayer):', ch.anime);
      if (newAnime === null) return;
      if (gameState.ws && gameState.ws.readyState === WebSocket.OPEN) {
        gameState.ws.send(JSON.stringify({
          action: 'avatar_admin_edit',
          data: { id: ch.id, name: newName.trim(), anime: newAnime.trim() }
        }));
      }
    });

    row.querySelector('[data-action="replace"]').addEventListener('click', () => {
      avatarLibraryState.replaceTargetId = ch.id;
      const replaceInp = document.getElementById('avatar-replace-file-input');
      if (replaceInp) replaceInp.click();
    });

    row.querySelector('[data-action="delete"]').addEventListener('click', () => {
      if (!confirm(`Remove "${ch.name}" from the local avatar library?`)) return;
      if (gameState.ws && gameState.ws.readyState === WebSocket.OPEN) {
        gameState.ws.send(JSON.stringify({
          action: 'avatar_admin_delete',
          data: { id: ch.id }
        }));
      }
    });

    list.appendChild(row);
  });
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

// Avatar Picker & Library Initialization
function setupAvatarPicker() {
  loadLocalAvatarManifest();

  const searchInput = document.getElementById('avatar-search-input');
  const searchClear = document.getElementById('avatar-search-clear');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      avatarLibraryState.searchQuery = e.target.value;
      avatarLibraryState.visibleCount = avatarLibraryState.pageSize;
      if (searchClear) searchClear.style.display = e.target.value ? 'inline-flex' : 'none';
      renderAvatarLibraryGrid();
    });
  }
  if (searchClear && searchInput) {
    searchClear.addEventListener('click', () => {
      searchInput.value = '';
      avatarLibraryState.searchQuery = '';
      searchClear.style.display = 'none';
      renderAvatarLibraryGrid();
    });
  }

  const loadMoreBtn = document.getElementById('avatar-load-more-btn');
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', () => {
      avatarLibraryState.visibleCount += avatarLibraryState.pageSize;
      renderAvatarLibraryGrid();
    });
  }

  const toggleAdminBtn = document.getElementById('toggle-avatar-admin-btn');
  const browserView = document.getElementById('avatar-browser-view');
  const adminView = document.getElementById('avatar-admin-view');
  if (toggleAdminBtn && browserView && adminView) {
    toggleAdminBtn.addEventListener('click', () => {
      avatarLibraryState.adminMode = !avatarLibraryState.adminMode;
      browserView.style.display = avatarLibraryState.adminMode ? 'none' : 'block';
      adminView.style.display = avatarLibraryState.adminMode ? 'block' : 'none';
      toggleAdminBtn.innerHTML = avatarLibraryState.adminMode ? '<span>← BACK TO CHARACTERS</span>' : '<span>⚙️ MANAGE / IMPORT</span>';
    });
  }

  const uploadFilesInp = document.getElementById('avatar-upload-files');
  const previewStrip = document.getElementById('avatar-upload-preview-strip');
  if (uploadFilesInp && previewStrip) {
    uploadFilesInp.addEventListener('change', async () => {
      previewStrip.innerHTML = '';
      const files = Array.from(uploadFilesInp.files || []).slice(0, 12);
      for (const file of files) {
        try {
          const url = await readFileAsDataURL(file);
          const img = document.createElement('img');
          img.src = url;
          img.alt = file.name;
          img.className = 'avatar-upload-preview-thumb';
          previewStrip.appendChild(img);
        } catch (e) {}
      }
    });
  }

  const uploadSubmitBtn = document.getElementById('avatar-upload-submit-btn');
  if (uploadSubmitBtn && uploadFilesInp) {
    uploadSubmitBtn.addEventListener('click', async () => {
      const files = Array.from(uploadFilesInp.files || []);
      if (files.length === 0) {
        showAvatarAdminStatus('Please select one or more PNG/JPG/WEBP portrait images.', false);
        return;
      }
      const franchise = document.getElementById('avatar-upload-franchise')?.value || 'other-anime';
      const customName = (document.getElementById('avatar-upload-name')?.value || '').trim();
      const items = [];
      for (const file of files) {
        const dataUrl = await readFileAsDataURL(file);
        const derivedName = (files.length === 1 && customName)
          ? customName
          : file.name.replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        items.push({
          name: derivedName,
          anime: franchise,
          filename: file.name,
          image_data: dataUrl
        });
      }
      if (gameState.ws && gameState.ws.readyState === WebSocket.OPEN) {
        gameState.ws.send(JSON.stringify({ action: 'avatar_admin_upload', data: { items } }));
      } else {
        showAvatarAdminStatus('WebSocket not connected. Refresh and try again.', false);
      }
    });
  }

  const rescanBtn = document.getElementById('avatar-rescan-btn');
  if (rescanBtn) {
    rescanBtn.addEventListener('click', () => loadLocalAvatarManifest());
  }

  const adminSearch = document.getElementById('avatar-admin-search');
  if (adminSearch) {
    adminSearch.addEventListener('input', () => renderAvatarAdminList());
  }

  const replaceInp = document.getElementById('avatar-replace-file-input');
  if (replaceInp) {
    replaceInp.addEventListener('change', async () => {
      const file = replaceInp.files?.[0];
      if (!file || !avatarLibraryState.replaceTargetId) return;
      const dataUrl = await readFileAsDataURL(file);
      if (gameState.ws && gameState.ws.readyState === WebSocket.OPEN) {
        gameState.ws.send(JSON.stringify({
          action: 'avatar_admin_replace',
          data: { id: avatarLibraryState.replaceTargetId, filename: file.name, image_data: dataUrl }
        }));
      }
      replaceInp.value = '';
      avatarLibraryState.replaceTargetId = null;
    });
  }
}

let pendingKickTarget = null;
let roomToastTimer = null;

function showRoomToast(message, variant = 'info', durationMs = 4500) {
  const banner = document.getElementById('room-toast-banner');
  const textEl = document.getElementById('room-toast-text');
  if (!banner || !textEl) return;
  textEl.textContent = message;
  banner.classList.remove('is-error', 'is-success');
  if (variant === 'error') banner.classList.add('is-error');
  if (variant === 'success') banner.classList.add('is-success');
  banner.style.display = 'flex';
  if (roomToastTimer) clearTimeout(roomToastTimer);
  roomToastTimer = setTimeout(() => {
    banner.style.display = 'none';
  }, durationMs);
}

function openKickConfirmModal(sessionId, playerName) {
  if (!gameState.isHost || sessionId === gameState.sessionId) return;
  pendingKickTarget = { sessionId, playerName };
  const nameEl = document.getElementById('kick-confirm-player-name');
  if (nameEl) nameEl.textContent = playerName;
  const modal = document.getElementById('kick-confirm-modal');
  if (modal) modal.style.display = 'flex';
}

function closeKickConfirmModal() {
  pendingKickTarget = null;
  const modal = document.getElementById('kick-confirm-modal');
  if (modal) modal.style.display = 'none';
}

function openLeaveRoomModal() {
  const modal = document.getElementById('leave-room-modal');
  if (modal) modal.style.display = 'flex';
}

function closeLeaveRoomModal() {
  const modal = document.getElementById('leave-room-modal');
  if (modal) modal.style.display = 'none';
}


// Attach User Interactions
function setupEventListeners() {
  const nameInput = document.getElementById('player-name-input');
  if (nameInput) {
    nameInput.value = gameState.myName;
    nameInput.addEventListener('input', (e) => {
      gameState.myName = e.target.value.trim() || 'Trainer Red';
      localStorage.setItem('pkmn_auction_name', gameState.myName);
    });
  }

  // Landing Page HUD Modal Triggers
  const navProfileBtn = document.getElementById('nav-profile-btn');
  const openCreateBtn = document.getElementById('open-create-modal-btn');
  const openJoinBtn = document.getElementById('open-join-modal-btn');
  const saveProfileBtn = document.getElementById('save-profile-btn');
  const hudNavItems = document.getElementById('hud-nav-items');

  if (navProfileBtn) {
    navProfileBtn.addEventListener('click', () => {
      avatarLibraryState.pendingAvatar = gameState.myAvatar || 'red';
      avatarLibraryState.adminMode = false;
      const bv = document.getElementById('avatar-browser-view');
      const av = document.getElementById('avatar-admin-view');
      const tb = document.getElementById('toggle-avatar-admin-btn');
      if (bv) bv.style.display = 'block';
      if (av) av.style.display = 'none';
      if (tb) tb.innerHTML = '<span>⚙️ MANAGE / IMPORT</span>';
      loadLocalAvatarManifest();
      openHudModal('profile-modal-backdrop');
      if (hudNavItems) hudNavItems.classList.remove('mobile-open');
    });
  }
  if (saveProfileBtn) {
    saveProfileBtn.addEventListener('click', () => {
      if (nameInput) {
        gameState.myName = nameInput.value.trim() || 'Trainer Red';
        localStorage.setItem('pkmn_auction_name', gameState.myName);
      }
      if (avatarLibraryState.pendingAvatar) {
        gameState.myAvatar = avatarLibraryState.pendingAvatar;
        localStorage.setItem('pkmn_auction_avatar', gameState.myAvatar);
      }
      if (gameState.ws && gameState.ws.readyState === WebSocket.OPEN) {
        gameState.ws.send(JSON.stringify({
          action: 'update_profile',
          data: { name: gameState.myName, avatar: gameState.myAvatar }
        }));
      }
      closeHudModal('profile-modal-backdrop');
    });
  }
  const cancelProfileBtn = document.getElementById('cancel-profile-btn');
  if (cancelProfileBtn) {
    cancelProfileBtn.addEventListener('click', () => {
      avatarLibraryState.pendingAvatar = gameState.myAvatar;
      closeHudModal('profile-modal-backdrop');
    });
  }
  if (openCreateBtn) {
    openCreateBtn.addEventListener('click', () => {
      if (window.AuctionTicketUI) {
        window.AuctionTicketUI.openCreate();
      } else {
        openHudModal('create-room-modal-backdrop');
      }
    });
  }
  if (openJoinBtn) {
    openJoinBtn.addEventListener('click', () => {
      if (window.AuctionTicketUI) {
        window.AuctionTicketUI.openJoin();
      } else {
        openHudModal('join-room-modal-backdrop');
      }
    });
  }

  // Close buttons and backdrop clicks for HUD modals
  const modalMappings = [
    ['profile-modal-backdrop', 'profile-modal-close-btn'],
    ['create-room-modal-backdrop', 'create-modal-close-btn'],
    ['join-room-modal-backdrop', 'join-modal-close-btn']
  ];
  modalMappings.forEach(([backdropId, closeBtnId]) => {
    const backdrop = document.getElementById(backdropId);
    const closeBtn = document.getElementById(closeBtnId);
    if (closeBtn) {
      closeBtn.addEventListener('click', () => closeHudModal(backdropId));
    }
    if (backdrop) {
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) closeHudModal(backdropId);
      });
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      modalMappings.forEach(([backdropId]) => closeHudModal(backdropId));
      const metricsBackdrop = document.getElementById('metrics-modal-backdrop');
      if (metricsBackdrop) metricsBackdrop.classList.remove('active');
    }
  });

  // Legacy sub-tabs (if present)
  const createSubTab = document.getElementById('subtab-create-btn');
  const joinSubTab = document.getElementById('subtab-join-btn');
  const formCreate = document.getElementById('form-create-room');
  const formJoin = document.getElementById('form-join-room');

  if (createSubTab && joinSubTab && formCreate && formJoin) {
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
  }

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
      if (window.AuctionTicketUI) {
        window.AuctionTicketUI.setFranchises(franchises);
      }
      const select = document.getElementById('single-anime-select');
      const chipsList = document.getElementById('franchise-chips-list');
      const adminFilter = document.getElementById('admin-franchise-filter');
      const dexSideFilter = document.getElementById('dex-side-franchise');

      if (select) select.innerHTML = '';
      if (chipsList) chipsList.innerHTML = '';

      franchises.forEach(f => {
        if (dexSideFilter) {
          const opt = document.createElement('option');
          opt.value = f.id;
          opt.textContent = f.name;
          dexSideFilter.appendChild(opt);
        }
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

  // Ticket-driven Create Room & Join Room bridges (preserving exact WebSocket payload)
  window.triggerCreateRoomFromTicket = (cfg) => {
    if (!gameState.ws || gameState.ws.readyState !== WebSocket.OPEN) {
      alert('Connecting to server... Please try again in a moment.');
      return;
    }
    const battleControlMode = (cfg && cfg.battle_control_mode) || document.getElementById('battle-control-select')?.value || 'ai_vs_ai';
    const tournamentFormat = (cfg && cfg.tournament_format) || document.getElementById('tournament-format-select')?.value || 'round_robin';

    gameState.ws.send(JSON.stringify({
      action: 'create_room',
      data: {
        name: gameState.myName,
        avatar: gameState.myAvatar,
        starting_purse: cfg.starting_purse || 100,
        min_bid: 1,
        anime_mode: cfg.anime_mode || selectedAnimeMode || 'all',
        selected_anime: cfg.selected_anime || Array.from(selectedAnimeFranchises),
        forms_mode: cfg.forms_mode || 'SINGLE_BASE',
        battle_control_mode: battleControlMode,
        tournament_format: tournamentFormat
      }
    }));
  };

  window.triggerJoinRoomFromTicket = (code) => {
    const cleanCode = String(code || '').trim().toUpperCase();
    if (!cleanCode) return alert('Please enter a room code');
    if (!gameState.ws || gameState.ws.readyState !== WebSocket.OPEN) {
      alert('Connecting to server... Please try again in a moment.');
      return;
    }
    gameState.ws.send(JSON.stringify({
      action: 'join_room',
      data: {
        room_code: cleanCode,
        name: gameState.myName,
        avatar: gameState.myAvatar
      }
    }));
  };

  // Legacy Create Room Click (if present)
  const createRoomBtn = document.getElementById('create-room-btn');
  if (createRoomBtn) {
    createRoomBtn.addEventListener('click', () => {
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

      window.triggerCreateRoomFromTicket({
        starting_purse: purse,
        anime_mode: selectedAnimeMode,
        selected_anime: selectedAnime,
        forms_mode: formsMode
      });
    });
  }

  // Legacy Join Room Click (if present)
  const joinRoomBtn = document.getElementById('join-room-btn');
  if (joinRoomBtn) {
    joinRoomBtn.addEventListener('click', () => {
      const code = document.getElementById('room-code-input').value.trim().toUpperCase();
      window.triggerJoinRoomFromTicket(code);
    });
  }

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

  // Dynamic Quick Bid Buttons (Auto-fills the custom bid input box + cyan selection glow)
  document.querySelectorAll('.btn-quick-bid').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.btn-quick-bid').forEach(b => b.classList.remove('is-selected'));
      btn.classList.add('is-selected');
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

  // Back to Lobby / Leave Room Buttons (Lobby, Stage, Battle, Results)
  document.querySelectorAll('.js-back-to-lobby').forEach(btn => {
    btn.addEventListener('click', () => {
      openLeaveRoomModal();
    });
  });

  document.getElementById('room-toast-close')?.addEventListener('click', () => {
    document.getElementById('room-toast-banner').style.display = 'none';
  });

  const leaveCancelBtn = document.getElementById('btn-leave-cancel');
  const leaveConfirmBtn = document.getElementById('btn-leave-confirm');
  if (leaveCancelBtn) {
    leaveCancelBtn.addEventListener('click', closeLeaveRoomModal);
  }
  if (leaveConfirmBtn) {
    leaveConfirmBtn.addEventListener('click', () => {
      closeLeaveRoomModal();
      if (gameState.ws && gameState.ws.readyState === WebSocket.OPEN && gameState.roomCode) {
        gameState.ws.send(JSON.stringify({
          action: 'leave_room',
          data: {}
        }));
      }
      gameState.roomCode = null;
      gameState.isHost = false;
      gameState.isWithdrawn = false;
      gameState.roomState = null;
      clearRoomSession();
      switchArenaScreen('arena-setup');
    });
  }

  // Kick Player Confirmation Modal
  const kickCancelBtn = document.getElementById('btn-kick-cancel');
  const kickConfirmBtn = document.getElementById('btn-kick-confirm');
  if (kickCancelBtn) {
    kickCancelBtn.addEventListener('click', closeKickConfirmModal);
  }
  if (kickConfirmBtn) {
    kickConfirmBtn.addEventListener('click', () => {
      if (pendingKickTarget && gameState.ws && gameState.ws.readyState === WebSocket.OPEN && gameState.roomCode) {
        gameState.ws.send(JSON.stringify({
          action: 'kick_player',
          data: { target_session_id: pendingKickTarget.sessionId }
        }));
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
    ${renderAvatarInlineHtml(msg.sender_avatar, msg.sender_name)}
    <span class="chat-sender">${escapeHtml(msg.sender_name)}:</span>
    <span class="chat-text">${escapeHtml(msg.text)}</span>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

// Bidding Action
function placeBid(amount) {
  const room = gameState.roomState;
  if (!room || !sendAction('place_bid', {
    amount,
    match_id: room.match_id,
    round_id: room.auction_character_count
  })) {
    showBiddingError('Waiting for the server connection.');
  }
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
  document.getElementById('lobby-purse-display').textContent = `$${roomState.starting_purse.toLocaleString()}`;
  document.getElementById('lobby-player-count').textContent = roomState.players.length;

  const list = document.getElementById('lobby-players-list');
  list.innerHTML = '';

  const me = roomState.players.find(p => p.session_id === gameState.sessionId);
  if (me) {
    gameState.isHost = me.is_host;
    const readyBtn = document.getElementById('ready-toggle-btn');
    if (readyBtn) {
      readyBtn.innerHTML = me.is_ready
        ? `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg><span>UNREADY</span>`
        : `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg><span>MARK READY</span>`;
      readyBtn.classList.toggle('ready', me.is_ready);
    }
  }

  const startBtn = document.getElementById('start-game-btn');
  if (gameState.isHost) {
    startBtn.style.display = 'inline-flex';
    startBtn.disabled = roomState.players.filter(p => p.is_connected).length < 2;
    startBtn.title = roomState.players.length < 2 ? 'Need at least 2 players to start' : 'Start the auction';
  } else {
    startBtn.style.display = 'none';
  }

  roomState.players.forEach(p => {
    const isMe = p.session_id === gameState.sessionId;

    const card = document.createElement('div');
    card.className = `lobby-player-card ${p.is_ready ? 'is-ready' : ''} ${isMe ? 'is-me' : ''}`;
    card.innerHTML = `
      ${renderAvatarBadgeHtml(p.avatar, 'lobby-avatar', p.name)}
      <div class="lobby-player-info">
        <div class="player-name">
          <span>${escapeHtml(p.name)}</span> ${isMe ? '<span class="you-badge">(You)</span>' : ''}
          ${p.is_host ? '<span class="host-badge">👑 HOST</span>' : ''}
        </div>
        <div class="player-purse">Purse: $${p.purse.toLocaleString()}</div>
      </div>
      <div class="ready-badge ${p.is_ready ? 'ready' : 'not-ready'}">
        ${!p.is_connected ? 'RECONNECTING' : p.is_ready ? 'READY' : 'WAITING'}
      </div>
    `;
    if (gameState.isHost && !isMe) {
      const kick = document.createElement('button');
      kick.type = 'button';
      kick.className = 'btn-kick-player';
      kick.textContent = 'Kick Player';
      kick.addEventListener('click', () => openKickConfirmModal(p.session_id, p.name));
      card.appendChild(kick);
    }
    list.appendChild(card);
  });

  // Render subtle empty slots up to 4 visible rows (dynamically shrinks as players join)
  const emptyCount = Math.max(0, 4 - roomState.players.length);
  for (let i = 0; i < emptyCount; i++) {
    const emptySlot = document.createElement('div');
    emptySlot.className = 'lobby-empty-slot';
    emptySlot.innerHTML = `
      <span class="lobby-empty-plus" aria-hidden="true">+</span>
      <span class="lobby-empty-text">Waiting for player...</span>
    `;
    list.appendChild(emptySlot);
  }
}

// Update Stage UI
function updateStageUI(roomState) {
  gameState.roomState = roomState;
  const stageEl = document.getElementById('arena-stage');
  if (stageEl && stageEl.classList.contains('active')) {
    updateStageBackgroundVideo('arena-stage', roomState);
  }
  document.getElementById('stage-room-code').textContent = roomState.room_code;

  const poolDisplay = document.getElementById('stage-pool-display');
  const round = roomState.auction_pokemon_count || 1;
  const maxPool = roomState.max_auction_pokemon || 16;
  const remaining = Math.max(0, maxPool - round);
  if (poolDisplay) {
    poolDisplay.textContent = `${round} / ${maxPool}`;
  }
  const bidPoolDone = document.getElementById('bid-pool-done');
  const bidPoolLeft = document.getElementById('bid-pool-left');
  if (bidPoolDone) bidPoolDone.textContent = `LOT ${round} / ${maxPool}`;
  if (bidPoolLeft) bidPoolLeft.textContent = `${remaining} LEFT`;

  const me = roomState.players.find(p => p.session_id === gameState.sessionId);
  if (me) {
    // Update my profile bar with carry-over purse and avatar
    const barWrap = document.getElementById('my-bar-avatar-wrap');
    if (barWrap) {
      barWrap.innerHTML = renderAvatarBadgeHtml(me.avatar, 'avatar-tiny-badge', me.name);
    }
    document.getElementById('my-bar-name').textContent = me.name;
    document.getElementById('my-bar-purse').textContent = `$${me.purse.toLocaleString()}`;
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
        <img src="${escapeHtml(p.image || '/api/avatar/default')}" alt="${escapeHtml(p.name)}" class="roster-slot-img" loading="lazy" onerror="this.onerror=null; this.src='/api/avatar/${encodeURIComponent(p.id)}';">
        <div class="roster-slot-info">
          <div class="roster-slot-name">${escapeHtml(p.name)}</div>
          <div class="roster-slot-meta">
            <span>${escapeHtml(animeName)} ${escapeHtml(formText)}${p.auction_cost ? ' · $' + p.auction_cost : ''}</span>
          </div>
        </div>
        <span class="slot-num">#${i + 1}</span>
      `;
    } else {
      slot.innerHTML = `
        <span class="empty-slot-plus" aria-hidden="true">+</span>
        <span class="empty-slot-text">Add Character</span>
      `;
    }
    container.appendChild(slot);
  }
}

// Render Opponents Table during Auction (NO TEAM POWER SHOWN)
function renderOpponents(players) {
  const container = document.getElementById('opponents-list');
  const countBadge = document.getElementById('players-arena-count');
  if (countBadge) countBadge.textContent = `(${players.length})`;
  container.innerHTML = '';

  players.forEach(p => {
    const isMe = p.session_id === gameState.sessionId;
    const isLeader = p.session_id === (gameState.roomState ? gameState.roomState.highest_bidder_id : null);
    const crownHtml = p.is_host
      ? `<span class="arena-host-crown" title="Room Host" aria-label="Room Host">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="#facc15" stroke="#eab308" stroke-width="1.2" aria-hidden="true">
            <path d="M3 18h18v2H3v-2zm0-2l2-9 5 4 2-6 2 6 5-4 2 9H3z"/>
          </svg>
        </span>`
      : '';

    const card = document.createElement('div');
    card.className = `opponent-card ${isLeader ? 'leading' : ''} ${isMe ? 'is-me' : ''} ${p.is_withdrawn ? 'is-withdrawn' : ''}`;
    card.innerHTML = `
      ${renderAvatarBadgeHtml(p.avatar, 'opponent-avatar', p.name)}
      <div class="opponent-info">
        <div class="opponent-name">
          <span>${escapeHtml(p.name)}${isMe ? ' (You)' : ''}</span>
          ${p.is_withdrawn ? '<span class="withdrawn-badge" style="background:#ef4444; color:#fff; font-size:0.65rem; padding:1px 5px; border-radius:4px; font-weight:700;">WITHDRAWN</span>' : ''}
          ${p.has_skipped && !p.is_withdrawn ? '<span class="skipped-badge" style="background:#64748b; color:#fff; font-size:0.65rem; padding:1px 5px; border-radius:4px; font-weight:700;">SKIPPED</span>' : ''}
          ${isLeader ? '<span class="lead-badge">🔥 LEADING</span>' : ''}
          ${p.is_team_full ? '<span class="full-badge">FULL</span>' : ''}
        </div>
        <div class="opponent-stats">
          <span>Purse: $${p.purse.toLocaleString()}</span>
          <span class="stat-sep">|</span>
          <span>Team: ${p.team_count}/6</span>
        </div>
      </div>
      ${crownHtml}
      ${gameState.isHost && !isMe ? '<button type="button" class="btn-kick-player btn-kick-player--sm">Kick Player</button>' : ''}
    `;
    card.querySelector('.btn-kick-player')?.addEventListener('click', () => openKickConfirmModal(p.session_id, p.name));
    container.appendChild(card);
  });
}

// Render the public auction profile: artwork, identity, power and character information.
function renderAuctionCard(poke) {
  const round = gameState.roomState ? (gameState.roomState.auction_pokemon_count || 1) : 1;
  const maxPool = gameState.roomState ? (gameState.roomState.max_auction_pokemon || 16) : 16;
  if (window.AuctionCharacterTicketUI && typeof window.AuctionCharacterTicketUI.renderCharacter === 'function') {
    window.AuctionCharacterTicketUI.renderCharacter(poke, round, maxPool);
    return;
  }

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
  const power = Number(poke.power_rating || 0).toFixed(1);
  const tier = poke.power_tier || 'B';
  const role = poke.role || poke.category || poke.species || 'Fighter';
  const techniques = (poke.techniques || poke.abilities || []).slice(0, 3);

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
    <div class="auction-public-profile">
      <strong>${power} POWER</strong> <span>${escapeHtml(tier)} TIER</span>
      <div>${escapeHtml(role)}</div>
      ${poke.description ? `<p>${escapeHtml(poke.description)}</p>` : ''}
      ${techniques.length ? `<small>${techniques.map(escapeHtml).join(' • ')}</small>` : ''}
    </div>
  `;
}

// Update Timer Display
function updateTimerDisplay(seconds) {
  const num = document.getElementById('auction-timer-num');
  const box = document.getElementById('timer-banner-box');
  const circle = document.getElementById('timer-circle-fill');
  const safeSec = Math.max(0, parseInt(seconds, 10) || 0);
  if (num) {
    const mins = Math.floor(safeSec / 60);
    const secs = safeSec % 60;
    num.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
  }

  if (circle) {
    const totalOffset = 263.89;
    const maxSeconds = (gameState.roomState && gameState.roomState.countdown_seconds) || 15;
    const progress = Math.max(0, Math.min(1, safeSec / maxSeconds));
    circle.style.strokeDashoffset = totalOffset * (1 - progress);
    circle.style.stroke = safeSec <= 4 ? '#ef4444' : (safeSec <= 7 ? '#f59e0b' : '#22d3ee');
  }

  if (box) {
    box.classList.toggle('is-urgent', safeSec <= 4);
    box.classList.toggle('is-warning', safeSec > 4 && safeSec <= 7);
  }
  if (num) {
    num.style.color = safeSec <= 4 ? '#fb7185' : (safeSec <= 7 ? '#fde047' : '#ffffff');
  }
}

// Update Bid Status Hero (AUTHORITATIVE: GUARANTEED ZERO "undefined" TEXT)
function updateBidStatus(amount, bidderId, bidderName, bidderAvatar) {
  const amountEl = document.getElementById('current-bid-amount');
  const bidderEl = document.getElementById('current-bidder-name');
  amountEl.textContent = amount > 0 ? amount.toLocaleString() : '0';
  const minBid = gameState.roomState ? gameState.roomState.min_bid : 1;

  if (!bidderId) {
    bidderEl.textContent = `No Bids Yet (Opening: $${minBid})`;
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
  const current = gameState.roomState?.current_bid || 0;
  const minBid = gameState.roomState?.min_bid || 1;
  const next = current === 0 ? minBid : current + 1;
  document.getElementById('next-valid-bid-display').textContent = '$' + next;
  document.querySelectorAll('.btn-quick-bid').forEach(button => {
    const increment = Number(button.dataset.inc);
    const amount = increment ? (current || minBid) + increment : next;
    button.textContent = increment ? '+$' + increment + ' ($' + amount + ')' : 'MIN ($' + amount + ')';
    button.dataset.amount = amount;
  });
}

// Reserve Budget Note
function updateReserveBudgetNote(me) {
  if (!me) return;
  const note = document.getElementById('reserve-budget-note');
  const minBid = gameState.roomState ? (gameState.roomState.min_bid || 1) : 1;
  if (me.team_count >= 6) {
    note.textContent = 'Team full (6/6). Maximum capacity reached.';
    note.style.color = '#94a3b8';
  } else {
    note.textContent = `Minimum bid is $${minBid} • Bids are final • Purse: $${me.purse.toLocaleString()} (${me.team_count}/6)`;
    note.style.color = '#cbd5e1';
  }
}

// Update Bid Buttons Disabling
function updateBidButtonStates(me, roomState) {
  const isLeader = roomState.highest_bidder_id === gameState.sessionId;
  const isFull = me.team_count >= 6;
  const isWithdrawn = me.is_withdrawn || gameState.isWithdrawn;
  const hasSkipped = me.has_skipped || (roomState.skipped_player_ids && roomState.skipped_player_ids.includes(gameState.sessionId));
  const minBid = roomState.min_bid || 1;
  const minRequired = roomState.current_bid === 0 ? minBid : roomState.current_bid + 1;
  const maxAllowed = (isFull || isWithdrawn || hasSkipped) ? 0 : Math.max(0, me.purse - (5 - me.team_count) * minBid);

  const quickBtns = document.querySelectorAll('.btn-quick-bid');
  const submitBtn = document.getElementById('submit-bid-btn');
  const customInput = document.getElementById('custom-bid-input');
  const skipBtn = document.getElementById('btn-skip-character');
  const skipBadge = document.getElementById('skip-status-badge');

  const disabled = roomState.status !== "AUCTION" || roomState.lot_settled || isLeader || isFull || isWithdrawn || hasSkipped || minRequired > maxAllowed;

  quickBtns.forEach(btn => {
    btn.disabled = disabled || Number(btn.dataset.amount) > maxAllowed;
  });
  if (submitBtn) submitBtn.disabled = disabled;
  if (customInput) {
    customInput.disabled = disabled;
    customInput.max = maxAllowed;
  }

  if (skipBtn) {
    skipBtn.disabled = isWithdrawn || hasSkipped || roomState.status !== 'AUCTION';
  }
  if (skipBadge) {
    skipBadge.style.display = hasSkipped ? 'inline-block' : 'none';
  }

  // Update min and placeholder without overwriting the player's entered bid amount
  if (!disabled && customInput) {
    customInput.min = minRequired;
    customInput.placeholder = `Min $${minRequired}`;
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
      submitBtn.innerHTML = `<svg class="gavel-btn-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m14 13-7.5 7.5c-.83.83-2.17.83-3 0a2.12 2.12 0 0 1 0-3L11 10"/><path d="m16 16 6-6"/><path d="m8 8 6-6"/><path d="m9 7 8 8"/><path d="m21 11-8-8"/></svg><span>PLACE BID</span>`;
    }
  }
}

// Showcase Toast Overlay
function showShowcaseBanner(title, subtitle) {
  const banner = document.createElement('div');
  banner.className = 'showcase-overlay';
  banner.innerHTML = `
    <div class="showcase-content">
      <h2>${escapeHtml(title)}</h2>
      <p>${escapeHtml(subtitle)}</p>
    </div>
  `;
  document.body.appendChild(banner);
  setTimeout(() => { banner.classList.add('fade-out'); }, 2000);
  setTimeout(() => { banner.remove(); }, 2500);
}

// Live Auction Log
function addStageLog(htmlText, type) {
  const list = document.getElementById('stage-log-list');
  if (!list) return;
  const item = document.createElement('div');
  const safeType = type || 'system';
  item.className = `log-item log-${safeType}`;

  const iconMap = {
    bid: '🔨',
    sold: '🏆',
    unsold: '❌',
    round: '🟢',
    join: '👤',
    system: '⚡'
  };
  const icon = iconMap[safeType] || '•';
  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  item.innerHTML = `
    <span class="log-item-icon" aria-hidden="true">${icon}</span>
    <span class="log-item-body">${htmlText}</span>
    <span class="log-item-time">${timeStr}</span>
  `;
  list.prepend(item);
  if (list.children.length > 25) list.lastChild.remove();
}

// Render Dynamic Category-Based MVP Showcase Panel
function renderMvpPanel(leaderboard, battleResults) {
  if (!Array.isArray(leaderboard) || leaderboard.length === 0) return;
  const winner = leaderboard[0];
  const combatMvp = battleResults?.combat_mvp;
  const mvp = combatMvp ? {
    character_name: combatMvp.name,
    franchise: [combatMvp.franchise, `${combatMvp.knockouts} KO · ${combatMvp.damage} damage`].filter(Boolean).join(' · '),
    image_url: combatMvp.image,
    fallback_image_url: '/api/avatar/' + encodeURIComponent(combatMvp.id)
  } : { character_name: 'No combat MVP', fallback_image_url: '/api/avatar/default' };
  const bestValue = battleResults?.best_value;
  document.getElementById('best-value-purchase').textContent = bestValue
    ? `Best draft value · ${bestValue.name} · $${bestValue.cost} · ${bestValue.damage} damage`
    : '';

  const trainerEl = document.getElementById('mvp-trainer-name');
  const powerEl = document.getElementById('mvp-team-power');
  const sizeEl = document.getElementById('mvp-team-size');
  const bstEl = document.getElementById('mvp-total-bst');
  const hpEl = document.getElementById('mvp-total-hp');
  const purseEl = document.getElementById('mvp-purse');
  const imgEl = document.getElementById('mvp-character-img');
  const charNameEl = document.getElementById('mvp-character-name');
  const franchiseEl = document.getElementById('mvp-character-franchise');

  if (trainerEl) trainerEl.textContent = winner.name || 'Winner';
  if (powerEl) powerEl.textContent = Number(winner.team_power || 0).toFixed(1);
  const teamCount = winner.pokemon_count || (winner.team ? winner.team.length : 0);
  if (sizeEl) sizeEl.textContent = `${teamCount}/6`;
  if (bstEl) bstEl.textContent = Number(winner.total_bst || 0).toLocaleString();
  if (hpEl) hpEl.textContent = Number(winner.total_hp || 0).toLocaleString();
  if (purseEl) purseEl.textContent = `$${Number(winner.remaining_purse || 0).toLocaleString()}`;

  if (charNameEl) charNameEl.textContent = mvp.character_name || 'Champion';
  if (franchiseEl) franchiseEl.textContent = mvp.franchise || '';
  if (imgEl) {
    imgEl.alt = mvp.character_name || 'MVP Character';
    imgEl.onerror = () => {
      if (imgEl.dataset.fallbackApplied) return;
      imgEl.dataset.fallbackApplied = '1';
      imgEl.src = mvp.fallback_image_url;
    };
    delete imgEl.dataset.fallbackApplied;
    imgEl.src = mvp.image_url || mvp.fallback_image_url;
  }
}

// Render Final Leaderboard (REVEAL ALL STATS DRAMATICALLY!)
function renderLeaderboard(leaderboard, battleResults = null) {
  renderMvpPanel(leaderboard, battleResults);

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
    const pod = document.createElement('div');
    pod.className = `podium-card rank-${p.rank || (idx + 1)}`;
    const teamCount = p.pokemon_count || (p.team ? p.team.length : 0);
    const hasBattle = typeof p.battle_wins === 'number';
    const headline = hasBattle
      ? `${p.battle_wins}W-${p.battle_losses}L-${p.battle_draws}D <span class="lbl">${p.battle_points} PTS</span>`
      : `${p.team_power.toFixed(1)} <span class="lbl">TEAM POWER</span>`;
    pod.innerHTML = `
      <div class="podium-medal">${medals[idx] || '🏅'}</div>
      ${renderAvatarBadgeHtml(p.avatar, 'podium-avatar', p.name)}
      <h3 class="podium-name">${escapeHtml(p.name)}</h3>
      <div class="podium-power">${headline}</div>
      <div class="podium-stats">
        <span>Team: ${teamCount}/6</span> &bull; 
        <span>Power: ${p.team_power.toFixed(1)}</span> &bull; 
        <span>HP: ${p.total_hp || 0}</span>
      </div>
      <div style="font-size:0.8rem; color:#94a3b8; margin-top:0.3rem;">
        Purse: $${p.remaining_purse.toLocaleString()}
      </div>
    `;
    podium.appendChild(pod);
  });

  // 2. Render Full Table
  const tbody = document.getElementById('leaderboard-body');
  tbody.innerHTML = '';

  leaderboard.forEach(p => {
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
          ${renderAvatarInlineHtml(p.avatar, p.name)}
          <strong>${escapeHtml(p.name)}</strong> ${isMe ? '(You)' : ''}
          ${p.is_withdrawn ? '<span style="color:#ef4444; font-size:0.75rem; font-weight:700;">(Withdrawn)</span>' : ''}
        </div>
      </td>
      <td><strong>${recordText}</strong></td>
      <td><strong style="color:#f59e0b;">${ptsText}</strong></td>
      <td><span style="color:#10b981; font-weight:600;">${teamCount}/6</span></td>
      <td><strong style="color:#38bdf8; font-size:1.05rem;">${p.team_power.toFixed(1)}</strong></td>
      <td>$${p.remaining_purse.toLocaleString()}</td>
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
            <div style="color:#94a3b8; font-size:0.8rem;">Turns: ${m.turns_played} &bull; ${escapeHtml(m.explanation || m.reason)}</div>
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

  // Keep Team Inspection drawer collapsed on initial load (opens on "Inspect Team" click)
  const showcasePanel = document.getElementById('team-showcase-panel');
  if (showcasePanel) showcasePanel.style.display = 'none';

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
        <img src="${escapeHtml(p.image || '/api/avatar/default')}" alt="${escapeHtml(p.name)}" class="showcase-img" loading="lazy" onerror="this.onerror=null; this.src='/api/avatar/${encodeURIComponent(p.id)}';">
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
      category: '',
      combat_eligible: '',
      has_artwork: '',
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
    const categorySelect = document.getElementById('anime-category-select');
    const combatSelect = document.getElementById('anime-combat-select');
    const artworkSelect = document.getElementById('anime-artwork-select');
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

    if (categorySelect) {
      categorySelect.addEventListener('change', (e) => {
        this.state.filters.category = e.target.value;
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    }

    if (combatSelect) {
      combatSelect.addEventListener('change', (e) => {
        this.state.filters.combat_eligible = e.target.value;
        this.state.currentPage = 1;
        this.fetchCharacters();
      });
    }

    if (artworkSelect) {
      artworkSelect.addEventListener('change', (e) => {
        this.state.filters.has_artwork = e.target.value;
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
        if (categorySelect) categorySelect.value = '';
        if (combatSelect) combatSelect.value = '';
        if (artworkSelect) artworkSelect.value = '';
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
          category: '',
          combat_eligible: '',
          has_artwork: '',
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
    if (this.state.filters.category) p.set('category', this.state.filters.category);
    if (this.state.filters.combat_eligible) p.set('combat_eligible', this.state.filters.combat_eligible);
    if (this.state.filters.has_artwork) p.set('has_artwork', this.state.filters.has_artwork);
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
    const statScale = statEntries.some(([, value]) => Number(value) > 100) ? 255 : 100;
    if (statEntries.length > 0) {
      statsBarsHtml = statEntries.map(([k, v]) => {
        const pct = Math.min(100, Math.round((Number(v) / statScale) * 100));
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
              <span style="font-size:0.78rem; color:#94a3b8;">${escapeHtml(char.role || char.category || 'Fighter')} &bull; ${escapeHtml(char.species || 'Entity')}</span>
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
          <div><strong style="color:#94a3b8;">Role:</strong> ${escapeHtml(char.role || char.category || 'Fighter')}</div>
          <div><strong style="color:#94a3b8;">Identity:</strong> ${escapeHtml((char.aliases || char.alt_names || [])[0] || char.name)}</div>
          <div><strong style="color:#94a3b8;">Continuity:</strong> ${escapeHtml(char.incarnation || char.anime_name || 'Database')}</div>
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


// ============================================================================
// STAGE LEFT SIDE PANEL: CHARACTER DEX
// ============================================================================
const dexSideState = {
  offset: 0,
  limit: 25,
  total: 0,
  timer: null
};

function initStageCharacterDex() {
  const searchInp = document.getElementById('dex-side-search');
  const franchiseSel = document.getElementById('dex-side-franchise');
  const loadMoreBtn = document.getElementById('dex-side-load-more');
  if (!searchInp || !franchiseSel) return;

  const reload = () => {
    dexSideState.offset = 0;
    fetchStageCharacterDex(false);
  };

  searchInp.addEventListener('input', () => {
    clearTimeout(dexSideState.timer);
    dexSideState.timer = setTimeout(reload, 220);
  });
  franchiseSel.addEventListener('change', reload);
  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', () => {
      dexSideState.offset += dexSideState.limit;
      fetchStageCharacterDex(true);
    });
  }

  fetchStageCharacterDex(false);
}

async function fetchStageCharacterDex(append = false) {
  const listEl = document.getElementById('dex-side-list');
  const countEl = document.getElementById('dex-side-count');
  const loadMoreBtn = document.getElementById('dex-side-load-more');
  if (!listEl) return;

  const q = (document.getElementById('dex-side-search')?.value || '').trim();
  const animeId = document.getElementById('dex-side-franchise')?.value || '';

  const params = new URLSearchParams({
    offset: String(dexSideState.offset)
  });
  if (q) params.set('q', q);
  if (animeId) params.set('anime_id', animeId);

  try {
    const res = await fetch(`/api/auction-catalog?${params.toString()}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const chars = Array.isArray(data.characters) ? data.characters : [];
    dexSideState.total = data.total || chars.length;

    if (countEl) countEl.textContent = dexSideState.total.toLocaleString();
    if (!append) listEl.innerHTML = '';

    if (chars.length === 0 && !append) {
      listEl.innerHTML = '<div class="dex-side-empty">No characters match your filter.</div>';
    } else {
      chars.forEach(c => {
        const fallback = `/api/avatar/${encodeURIComponent(c.id || String(c.name || 'char').toLowerCase().replace(/\s+/g, '_'))}`;
        const card = document.createElement('button');
        card.type = 'button';
        card.className = 'dex-side-card';
        card.setAttribute('aria-label', `Open ${c.name} character information`);
        const power = Number(c.power_rating || 0).toFixed(1);
        const tier = c.power_tier || 'B';
        const role = c.role || c.category || c.species || 'Fighter';
        card.innerHTML = `
          <img src="${escapeHtml(c.image || fallback)}" alt="${escapeHtml(c.name)}" class="dex-side-thumb" loading="lazy"
            onerror="this.onerror=null; this.src='${fallback}';">
          <div class="dex-side-meta">
            <div class="dex-side-name" title="${escapeHtml(c.name)}">${escapeHtml(c.name)}</div>
            <div class="dex-side-sub">${escapeHtml(role)}</div>
            <div class="dex-side-tech">${escapeHtml((c.techniques || c.abilities || []).slice(0, 2).join(' • '))}</div>
          </div>
          <div class="dex-side-stats">
            <span class="dex-side-tier tier-${tier.replace('+', '-plus')}">${escapeHtml(tier)}</span>
            <span class="dex-side-power">${power} PR</span>
            <span class="dex-side-more">INFO ›</span>
          </div>
        `;
        card.addEventListener('click', () => animeDatabaseModule.openDetailModal(c));
        listEl.appendChild(card);
      });
    }

    if (loadMoreBtn) {
      const shown = dexSideState.offset + chars.length;
      loadMoreBtn.style.display = shown < dexSideState.total ? 'block' : 'none';
    }
  } catch (err) {
    if (!append) {
      listEl.innerHTML = '<div class="dex-side-empty">Unable to load Character Dex.</div>';
    }
  }
}
