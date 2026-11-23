/**
 * Pokemon Auction & Power Ranking Client Application
 * Handles searching, multi-filtering, sorting, card rendering,
 * detailed modal inspection, and auction simulation.
 */

// Application State
const state = {
  allPokemon: [],
  filteredPokemon: [],
  currentPage: 1,
  pageSize: 36,
  filters: {
    search: '',
    type: '',
    generation: '',
    tier: '',
    rarity: '',
    quick: 'all' // 'all', 'legendary', 'mythical', 'starter', 'base-only'
  },
  sortBy: 'power_desc'
};

// DOM Elements
const searchInput = document.getElementById('search-input');
const clearSearchBtn = document.getElementById('clear-search-btn');
const typeSelect = document.getElementById('type-select');
const genSelect = document.getElementById('gen-select');
const tierSelect = document.getElementById('tier-select');
const raritySelect = document.getElementById('rarity-select');
const sortSelect = document.getElementById('sort-select');
const resetFiltersBtn = document.getElementById('reset-filters-btn');
const quickToggleBtns = document.querySelectorAll('.toggle-btn');
const resultsCount = document.getElementById('results-count');
const catalogGrid = document.getElementById('pokemon-grid');
const pagination = document.getElementById('pagination');
const prevPageBtn = document.getElementById('prev-page-btn');
const nextPageBtn = document.getElementById('next-page-btn');
const pageInfo = document.getElementById('page-info');

const modalBackdrop = document.getElementById('modal-backdrop');
const modalCloseBtn = document.getElementById('modal-close-btn');
const modalContent = document.getElementById('modal-content');

const metricsModalBackdrop = document.getElementById('metrics-modal-backdrop');
const viewStatsBtn = document.getElementById('view-stats-btn');
const metricsCloseBtn = document.getElementById('metrics-close-btn');

// Initialize Application
async function init() {
  attachEventListeners();
  await loadPokemonData();
}

// Load Pokémon dataset from local API or fallback to JSON
async function loadPokemonData() {
  catalogGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: #94a3b8;">Loading 1,351 Pokémon from database...</div>';
  try {
    const res = await fetch('/api/pokemon');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    state.allPokemon = data;
    applyFilters();
  } catch (err) {
    console.error('Failed to fetch from /api/pokemon, trying /data/pokemon_database.json...', err);
    try {
      const resFallback = await fetch('/data/pokemon_database.json');
      const dataFallback = await resFallback.json();
      state.allPokemon = dataFallback;
      applyFilters();
    } catch (e2) {
      catalogGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 3rem; color: #ef4444;">Failed to load Pokémon database: ${e2.message}</div>`;
    }
  }
}

// Attach UI Event Listeners
function attachEventListeners() {
  // Search input
  searchInput.addEventListener('input', (e) => {
    state.filters.search = e.target.value.trim().toLowerCase();
    clearSearchBtn.style.display = state.filters.search ? 'block' : 'none';
    state.currentPage = 1;
    applyFilters();
  });

  clearSearchBtn.addEventListener('click', () => {
    searchInput.value = '';
    state.filters.search = '';
    clearSearchBtn.style.display = 'none';
    state.currentPage = 1;
    applyFilters();
  });

  // Filter selects
  typeSelect.addEventListener('change', (e) => {
    state.filters.type = e.target.value;
    state.currentPage = 1;
    applyFilters();
  });

  genSelect.addEventListener('change', (e) => {
    state.filters.generation = e.target.value;
    state.currentPage = 1;
    applyFilters();
  });

  tierSelect.addEventListener('change', (e) => {
    state.filters.tier = e.target.value;
    state.currentPage = 1;
    applyFilters();
  });

  raritySelect.addEventListener('change', (e) => {
    state.filters.rarity = e.target.value;
    state.currentPage = 1;
    applyFilters();
  });

  // Sorting
  sortSelect.addEventListener('change', (e) => {
    state.sortBy = e.target.value;
    applySort();
    renderCards();
  });

  // Quick Toggles
  quickToggleBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      quickToggleBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.filters.quick = btn.dataset.filter;
      state.currentPage = 1;
      applyFilters();
    });
  });

  // Reset Filters
  resetFiltersBtn.addEventListener('click', () => {
    searchInput.value = '';
    typeSelect.value = '';
    genSelect.value = '';
    tierSelect.value = '';
    raritySelect.value = '';
    sortSelect.value = 'power_desc';

    state.filters = {
      search: '',
      type: '',
      generation: '',
      tier: '',
      rarity: '',
      quick: 'all'
    };
    state.sortBy = 'power_desc';
    clearSearchBtn.style.display = 'none';

    quickToggleBtns.forEach(b => b.classList.remove('active'));
    document.querySelector('.toggle-btn[data-filter="all"]').classList.add('active');

    state.currentPage = 1;
    applyFilters();
  });

  // Pagination navigation
  prevPageBtn.addEventListener('click', () => {
    if (state.currentPage > 1) {
      state.currentPage--;
      renderCards();
      window.scrollTo({ top: 300, behavior: 'smooth' });
    }
  });

  nextPageBtn.addEventListener('click', () => {
    const totalPages = Math.ceil(state.filteredPokemon.length / state.pageSize);
    if (state.currentPage < totalPages) {
      state.currentPage++;
      renderCards();
      window.scrollTo({ top: 300, behavior: 'smooth' });
    }
  });

  // Modals
  modalCloseBtn.addEventListener('click', closeModal);
  modalBackdrop.addEventListener('click', (e) => {
    if (e.target === modalBackdrop) closeModal();
  });

  viewStatsBtn.addEventListener('click', () => {
    metricsModalBackdrop.classList.add('active');
  });

  metricsCloseBtn.addEventListener('click', () => {
    metricsModalBackdrop.classList.remove('active');
  });

  metricsModalBackdrop.addEventListener('click', (e) => {
    if (e.target === metricsModalBackdrop) {
      metricsModalBackdrop.classList.remove('active');
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeModal();
      metricsModalBackdrop.classList.remove('active');
    }
  });
}

// Filter and search application
function applyFilters() {
  const { search, type, generation, tier, rarity, quick } = state.filters;

  state.filteredPokemon = state.allPokemon.filter(p => {
    // 1. Text search (Name, National ID formatted or raw, Category, Ability)
    if (search) {
      const idMatch = p.id.toString() === search || 
                      p.national_id.toString() === search || 
                      `#${p.national_id}`.toLowerCase().includes(search) ||
                      `#${p.national_id.toString().padStart(4, '0')}`.toLowerCase().includes(search);
      const nameMatch = p.name.toLowerCase().includes(search);
      const categoryMatch = p.category && p.category.toLowerCase().includes(search);
      const abilityMatch = p.abilities && p.abilities.some(a => a.toLowerCase().includes(search));
      if (!idMatch && !nameMatch && !categoryMatch && !abilityMatch) {
        return false;
      }
    }

    // 2. Elemental Type
    if (type && !p.types.includes(type)) {
      return false;
    }

    // 3. Generation
    if (generation && p.generation.toString() !== generation) {
      return false;
    }

    // 4. Tier
    if (tier && p.tier !== tier) {
      return false;
    }

    // 5. Rarity
    if (rarity && p.rarity !== rarity) {
      return false;
    }

    // 6. Quick Toggles
    if (quick === 'legendary' && !p.is_legendary) return false;
    if (quick === 'mythical' && !p.is_mythical) return false;
    if (quick === 'starter' && !p.is_starter) return false;
    if (quick === 'base-only' && !p.is_default) return false;

    return true;
  });

  applySort();
  renderCards();
}

// Sorting logic
function applySort() {
  const sort = state.sortBy;
  state.filteredPokemon.sort((a, b) => {
    switch (sort) {
      case 'power_desc':
        return b.power_rating - a.power_rating || b.stats.total - a.stats.total;
      case 'power_asc':
        return a.power_rating - b.power_rating || a.stats.total - b.stats.total;
      case 'bst_desc':
        return b.stats.total - a.stats.total || b.power_rating - a.power_rating;
      case 'auction_desc':
        return b.auction_value_score - a.auction_value_score || b.power_rating - a.power_rating;
      case 'speed_desc':
        return b.stats.speed - a.stats.speed || b.power_rating - a.power_rating;
      case 'attack_desc':
        return b.stats.attack - a.stats.attack || b.power_rating - a.power_rating;
      case 'defense_desc':
        return b.stats.defense - a.stats.defense || b.power_rating - a.power_rating;
      case 'id_asc':
        return a.id - b.id;
      case 'id_desc':
        return b.id - a.id;
      case 'name_asc':
        return a.name.localeCompare(b.name);
      default:
        return b.power_rating - a.power_rating;
    }
  });
}

// Render cards with pagination
function renderCards() {
  const total = state.filteredPokemon.length;
  resultsCount.textContent = `Showing ${total.toLocaleString()} Pokémon`;

  if (total === 0) {
    catalogGrid.innerHTML = `
      <div style="grid-column: 1/-1; text-align: center; padding: 4rem 1rem;">
        <h3 style="font-size: 1.25rem; color: #94a3b8; margin-bottom: 0.5rem;">No Pokémon Found</h3>
        <p style="color: #64748b; font-size: 0.9rem;">Try adjusting your filters or search keywords.</p>
      </div>
    `;
    pagination.style.display = 'none';
    return;
  }

  pagination.style.display = 'flex';
  const totalPages = Math.ceil(total / state.pageSize);
  if (state.currentPage > totalPages) state.currentPage = totalPages;
  pageInfo.textContent = `Page ${state.currentPage} of ${totalPages}`;

  prevPageBtn.disabled = state.currentPage <= 1;
  nextPageBtn.disabled = state.currentPage >= totalPages;

  const startIdx = (state.currentPage - 1) * state.pageSize;
  const pageItems = state.filteredPokemon.slice(startIdx, startIdx + state.pageSize);

  let html = '';
  pageItems.forEach(p => {
    const tierClass = `tier-${p.tier.replace('+', '-plus')}`;
    const borderClass = `tier-border-${p.tier.replace('+', '-plus')}`;
    const formattedDexId = `#${p.national_id.toString().padStart(4, '0')}`;

    const typeBadges = p.types.map(t => 
      `<span class="type-badge type-${t.toLowerCase()}">${t}</span>`
    ).join('');

    html += `
      <article class="pokemon-card ${borderClass}" data-id="${p.id}">
        <div class="card-top">
          <span class="dex-num">${formattedDexId} &bull; Gen ${p.generation}</span>
          <span class="card-tier-badge ${tierClass}">${p.tier} TIER</span>
        </div>

        <div class="card-img-wrap">
          <div class="card-img-bg"></div>
          <img src="${p.image}" alt="${p.name}" loading="lazy" onerror="this.onerror=null; this.src='${p.official_pokedex_image}';">
        </div>

        <div class="card-info">
          <h2 class="pokemon-name" title="${p.name}">${p.name}</h2>
          <p class="pokemon-category">${p.category || 'Pokémon'}</p>
          <div class="type-pill-list">${typeBadges}</div>
        </div>

        <div class="card-metrics">
          <div class="metric-col">
            <span class="metric-label">Power Rating</span>
            <span class="metric-value metric-power">${p.power_rating.toFixed(1)}</span>
          </div>
          <div class="metric-col">
            <span class="metric-label">Auction Bid</span>
            <span class="metric-value metric-auction">🪙 ${p.auction_value_score.toLocaleString()}</span>
          </div>
        </div>

        <div class="mini-stats">
          <div class="mini-stat-row">
            <span class="stat-abbr">BST</span>
            <div class="stat-bar-track">
              <div class="stat-bar-fill" style="width: ${Math.min(100, (p.stats.total / 780) * 100)}%;"></div>
            </div>
            <span class="stat-val">${p.stats.total}</span>
          </div>
          <div class="mini-stat-row">
            <span class="stat-abbr">SPD</span>
            <div class="stat-bar-track">
              <div class="stat-bar-fill" style="width: ${Math.min(100, (p.stats.speed / 200) * 100)}; background: #10b981;"></div>
            </div>
            <span class="stat-val">${p.stats.speed}</span>
          </div>
        </div>
      </article>
    `;
  });

  catalogGrid.innerHTML = html;

  // Attach card click handlers for detail view
  document.querySelectorAll('.pokemon-card').forEach(card => {
    card.addEventListener('click', () => {
      const pid = parseInt(card.dataset.id, 10);
      const poke = state.allPokemon.find(p => p.id === pid);
      if (poke) openModal(poke);
    });
  });
}

// Open Detail Modal
function openModal(p) {
  const tierClass = `tier-${p.tier.replace('+', '-plus')}`;
  const formattedDexId = `#${p.national_id.toString().padStart(4, '0')}`;
  const typesBadges = p.types.map(t => `<span class="type-badge type-${t.toLowerCase()}">${t}</span>`).join('');

  const statsBreakdown = [
    { label: 'HP', val: p.stats.hp, max: 255, color: '#ef4444' },
    { label: 'Attack', val: p.stats.attack, max: 190, color: '#f97316' },
    { label: 'Defense', val: p.stats.defense, max: 250, color: '#eab308' },
    { label: 'Sp. Attack', val: p.stats.special_attack, max: 194, color: '#06b6d4' },
    { label: 'Sp. Defense', val: p.stats.special_defense, max: 250, color: '#3b82f6' },
    { label: 'Speed', val: p.stats.speed, max: 200, color: '#10b981' }
  ].map(s => `
    <div class="stat-full-row">
      <span class="stat-full-label">${s.label}</span>
      <span class="stat-full-val">${s.val}</span>
      <div class="stat-full-bar-track">
        <div class="stat-full-bar-fill" style="width: ${(s.val / s.max) * 100}%; background: ${s.color};"></div>
      </div>
    </div>
  `).join('');

  const weaknesses = p.type_effectiveness && p.type_effectiveness.weaknesses.length > 0 
    ? p.type_effectiveness.weaknesses.map(t => `<span class="type-badge type-${t.toLowerCase()}">${t}</span>`).join('') 
    : '<span style="color:#64748b; font-size:0.8rem;">None (Solid Typing)</span>';

  const resistances = p.type_effectiveness && p.type_effectiveness.resistances.length > 0 
    ? p.type_effectiveness.resistances.map(t => `<span class="type-badge type-${t.toLowerCase()}">${t}</span>`).join('') 
    : '<span style="color:#64748b; font-size:0.8rem;">None</span>';

  const immunities = p.type_effectiveness && p.type_effectiveness.immunities.length > 0 
    ? p.type_effectiveness.immunities.map(t => `<span class="type-badge type-${t.toLowerCase()}">${t}</span>`).join('') 
    : '<span style="color:#64748b; font-size:0.8rem;">None</span>';

  modalContent.innerHTML = `
    <div class="detail-header">
      <div class="detail-img-wrap">
        <img src="${p.image}" alt="${p.name}" onerror="this.onerror=null; this.src='${p.official_pokedex_image}';">
      </div>
      <div class="detail-intro">
        <div class="detail-badges">
          <span class="card-tier-badge ${tierClass}">${p.tier} TIER</span>
          <span style="font-family:'JetBrains Mono'; font-weight:700; color:#94a3b8; font-size:0.85rem;">${formattedDexId} &bull; Gen ${p.generation}</span>
          <span style="background:rgba(255,255,255,0.08); padding:0.15rem 0.6rem; border-radius:4px; font-size:0.75rem; font-weight:600;">${p.rarity}</span>
        </div>
        <h2 class="detail-title">${p.name}</h2>
        <p class="detail-category">${p.category || 'Pokémon'}</p>
        <div class="type-pill-list">${typesBadges}</div>

        <div class="detail-meta-grid">
          <div class="meta-chip">
            <div class="chip-label">Height</div>
            <div class="chip-val">${p.height} m</div>
          </div>
          <div class="meta-chip">
            <div class="chip-label">Weight</div>
            <div class="chip-val">${p.weight} kg</div>
          </div>
          <div class="meta-chip">
            <div class="chip-label">Evolution</div>
            <div class="chip-val">Stage ${p.evolution.stage} ${p.evolution.evolves_from_name ? `(from ${p.evolution.evolves_from_name})` : '(Basic)'}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Auction Price Showcase -->
    <div class="auction-showcase-box">
      <div class="auction-showcase-text">
        <h4>Estimated Auction Market Value</h4>
        <p>Valuation formula based on Power Rating (${p.power_rating.toFixed(1)}), ${p.rarity} rarity prestige, and ${p.stats.total} BST combat potency.</p>
      </div>
      <div class="auction-price-tag">
        🪙 ${p.auction_value_score.toLocaleString()} <span style="font-size:0.9rem; color:#94a3b8; font-weight:400;">coins</span>
      </div>
    </div>

    <!-- Base Stats Breakdown -->
    <h3 class="detail-section-title">Base Stats Breakdown (BST: ${p.stats.total})</h3>
    <div class="stats-breakdown-grid">
      ${statsBreakdown}
    </div>

    <!-- Abilities & Defensive Matchups -->
    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:1.5rem; margin-bottom:1.5rem;">
      <div>
        <h3 class="detail-section-title">Abilities</h3>
        <p style="font-size:0.9rem; color:#f0f4fc;">
          ${p.abilities.length > 0 ? p.abilities.join(', ') : 'None recorded'}
        </p>
      </div>
      <div>
        <h3 class="detail-section-title">Type Defenses</h3>
        <div style="font-size:0.75rem; color:#94a3b8; margin-bottom:0.3rem;">Weak Against (Damage 2x / 4x):</div>
        <div class="type-matchup-list">${weaknesses}</div>
        <div style="font-size:0.75rem; color:#94a3b8; margin-bottom:0.3rem;">Resistant To (Damage 0.5x):</div>
        <div class="type-matchup-list">${resistances}</div>
        ${immunities !== '<span style="color:#64748b; font-size:0.8rem;">None</span>' ? `
          <div style="font-size:0.75rem; color:#94a3b8; margin-bottom:0.3rem;">Immune To (0x Damage):</div>
          <div class="type-matchup-list">${immunities}</div>
        ` : ''}
      </div>
    </div>

    <!-- Interactive Auction Bidding Simulator -->
    <div class="bid-simulator">
      <h3 style="font-size:0.95rem; color:#f59e0b; margin-bottom:0.25rem;">Auction Game Simulation</h3>
      <p style="font-size:0.8rem; color:#94a3b8;">Place a test bid for this card in the auction simulator:</p>
      <div class="bid-controls">
        <input type="number" id="sim-bid-input" class="bid-input" value="${p.auction_value_score + 100}" step="50" min="${p.auction_value_score}">
        <button id="sim-bid-btn" class="bid-btn">Place Bid</button>
      </div>
      <div id="sim-bid-feedback" style="margin-top:0.5rem; font-size:0.82rem; font-weight:600; display:none;"></div>
    </div>

    <!-- Modal Footer Actions -->
    <div class="modal-footer-actions">
      <a href="${p.official_pokedex_url}" target="_blank" rel="noopener" class="btn btn-outline">
        View on Official Pokédex ↗
      </a>
      <button class="btn btn-primary" onclick="closeModal()">Done</button>
    </div>
  `;

  // Attach simulator event
  const bidInput = document.getElementById('sim-bid-input');
  const bidBtn = document.getElementById('sim-bid-btn');
  const bidFeedback = document.getElementById('sim-bid-feedback');

  bidBtn.addEventListener('click', () => {
    const val = parseInt(bidInput.value, 10);
    if (val >= p.auction_value_score) {
      bidFeedback.style.display = 'block';
      bidFeedback.style.color = '#10b981';
      bidFeedback.textContent = `Bid of 🪙 ${val.toLocaleString()} coins accepted! You are currently the highest bidder for ${p.name}.`;
    } else {
      bidFeedback.style.display = 'block';
      bidFeedback.style.color = '#ef4444';
      bidFeedback.textContent = `Bid too low! Minimum opening bid is 🪙 ${p.auction_value_score.toLocaleString()} coins.`;
    }
  });

  modalBackdrop.classList.add('active');
}

function closeModal() {
  modalBackdrop.classList.remove('active');
}

// Start
init();
