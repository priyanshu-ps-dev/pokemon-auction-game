import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import TearTicket from './TearTicket.jsx';
import CodeSlots from './CodeSlots.jsx';
import AuctionCharacterCard from './AuctionCharacterCard.jsx';
import './AuctionTicketModal.css';

/* Crisp custom SVG icons matching the reference ticket */
const IconGear = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="#ffc928" aria-hidden="true">
    <path d="M19.14 12.94c.04-.31.06-.63.06-.94s-.02-.63-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.61-.22l-2.39.96a7.03 7.03 0 0 0-1.63-.94l-.36-2.54a.49.49 0 0 0-.49-.42h-3.84a.49.49 0 0 0-.49.42l-.36 2.54c-.59.24-1.13.56-1.63.94l-2.39-.96a.5.5 0 0 0-.61.22L2.7 8.84a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94L2.82 14.52a.5.5 0 0 0-.12.64l1.92 3.32c.14.24.43.34.68.22l2.32-.96c.5.38 1.04.7 1.63.94l.36 2.54c.04.24.25.42.49.42h3.84c.24 0 .45-.18.49-.42l.36-2.54c.59-.24 1.13-.56 1.63-.94l2.32.96c.25.12.54.02.68-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.5A3.5 3.5 0 1 1 12 8.5a3.5 3.5 0 0 1 0 7z" />
  </svg>
);

const IconPurse = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
    <path d="M8.5 6.5L7 3.5h10l-1.5 3" fill="#f59e0b" />
    <path d="M5.5 14.5c0-4.2 2.7-7.5 6.5-7.5s6.5 3.3 6.5 7.5c0 3.2-2.2 5.5-6.5 5.5s-6.5-2.3-6.5-5.5z" fill="#ffc928" />
    <ellipse cx="17.5" cy="17.5" rx="3.5" ry="2.2" fill="#fde047" stroke="#b45309" strokeWidth="1" />
    <path d="M9 7h6" stroke="#b45309" strokeWidth="1.6" strokeLinecap="round" />
  </svg>
);

const IconStar = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="#ffc928" aria-hidden="true">
    <path d="M12 2.4l2.85 5.78 6.38.93-4.61 4.5 1.09 6.35L12 16.96l-5.71 3 1.09-6.35-4.61-4.5 6.38-.93L12 2.4z" />
  </svg>
);

const IconSwap = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#ffc928" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 8h14l-3-3" />
    <path d="M20 16H6l3 3" />
  </svg>
);

const IconGlobe = () => (
  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="#38bdf8" strokeWidth="1.8" aria-hidden="true">
    <circle cx="12" cy="12" r="9.5" fill="rgba(56, 189, 248, 0.18)" />
    <ellipse cx="12" cy="12" rx="4.3" ry="9.5" />
    <path d="M3 9h18M3 15h18" />
  </svg>
);

const IconBolt = () => (
  <svg viewBox="0 0 24 24" width="26" height="26" fill="#ffc928" aria-hidden="true">
    <path d="M13.5 2L5.5 13h5.5l-1.5 9 8.5-11.5h-5.5L13.5 2z" />
  </svg>
);

const IconTarget = () => (
  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" aria-hidden="true">
    <circle cx="12" cy="12" r="9" fill="#ef4444" />
    <circle cx="12" cy="12" r="5.8" fill="#ffffff" />
    <circle cx="12" cy="12" r="2.7" fill="#ef4444" />
    <path d="M19.5 4.5l-7 7" stroke="#38bdf8" strokeWidth="2.2" strokeLinecap="round" />
    <path d="M19.5 4.5l-3.2.5.5 2.7 2.7-3.2z" fill="#38bdf8" />
  </svg>
);

const IconSwords = () => (
  <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="#e2e8f0" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 19l14-14M15 5h4v4" />
    <path d="M7 13l4 4M4 16l4 4" stroke="#f472b6" />
    <path d="M19 19L5 5M9 5H5v4" />
    <path d="M17 13l-4 4M20 16l-4 4" stroke="#38bdf8" />
  </svg>
);

const AUCTION_MODES = [
  { id: 'all', icon: <IconGlobe />, label: 'All Anime' },
  { id: 'pokemon', icon: <IconBolt />, label: 'Pokémon Only' },
  { id: 'single', icon: <IconTarget />, label: 'Single Anime' },
  { id: 'multiple', icon: <IconSwords />, label: 'Selected Anime' },
];

const PETALS = [
  { id: 1, left: '16%', top: '34%', delay: '0s', size: 12 },
  { id: 2, left: '19%', top: '76%', delay: '1.4s', size: 14 },
  { id: 3, left: '46%', top: '16%', delay: '2.1s', size: 10 },
  { id: 4, left: '74%', top: '80%', delay: '0.7s', size: 13 },
  { id: 5, left: '88%', top: '65%', delay: '1.9s', size: 14 },
];

function SlashBars({ count = 4 }) {
  return (
    <span className="ticket-slash-group" aria-hidden="true">
      {Array.from({ length: count }).map((_, idx) => (
        <span key={idx} className="ticket-slash-bar" />
      ))}
    </span>
  );
}

function DecorativeClouds({ side }) {
  return (
    <div className={`ticket-clouds ticket-clouds--${side}`} aria-hidden="true">
      <svg viewBox="0 0 600 120" preserveAspectRatio="none">
        <defs>
          <linearGradient id={`cloudGrad-${side}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.48" />
            <stop offset="55%" stopColor="#0284c7" stopOpacity="0.65" />
            <stop offset="100%" stopColor="#030b25" stopOpacity="0.95" />
          </linearGradient>
        </defs>
        <path
          d="M0,120 L0,85 Q35,45 85,68 Q125,22 185,55 Q240,18 300,58 Q365,25 425,62 Q485,30 540,66 Q575,45 600,72 L600,120 Z"
          fill={`url(#cloudGrad-${side})`}
        />
        <path
          d="M0,120 L0,96 Q50,65 110,88 Q170,55 235,84 Q305,52 375,86 Q445,58 515,88 Q565,68 600,90 L600,120 Z"
          fill="#0ea5e9"
          fillOpacity="0.28"
        />
      </svg>
    </div>
  );
}

function TicketStubArtwork({ verb }) {
  return (
    <div className="ticket-stub-inner">
      <div className="ticket-stub-perforation" aria-hidden="true" />
      <DecorativeClouds side="right" />
      {PETALS.slice(3).map(p => (
        <span
          key={p.id}
          className="ticket-petal"
          style={{ left: p.left, top: p.top, animationDelay: p.delay, width: p.size, height: p.size * 0.72 }}
          aria-hidden="true"
        />
      ))}

      <div className="ticket-stub-hero">
        <div className="ticket-stub-tearto">TEAR TO</div>
        <div className="ticket-stub-verb-row">
          <svg className="ticket-speed-marks ticket-speed-marks--left" viewBox="0 0 42 52" fill="none" aria-hidden="true">
            <path d="M36 10 L10 6 Q6 6 8 10 L34 16 Z" stroke="#00d9ff" strokeWidth="2" />
            <path d="M36 26 L4 26 Q1 26 4 30 L36 30 Z" stroke="#00d9ff" strokeWidth="2" />
            <path d="M36 42 L12 46 Q8 47 10 42 L34 37 Z" stroke="#00d9ff" strokeWidth="2" />
          </svg>
          <span className="ticket-stub-verb">{verb}</span>
          <svg className="ticket-speed-marks ticket-speed-marks--right" viewBox="0 0 42 52" fill="none" aria-hidden="true">
            <path d="M6 10 L32 6 Q36 6 34 10 L8 16 Z" stroke="#00d9ff" strokeWidth="2" />
            <path d="M6 26 L38 26 Q41 26 38 30 L6 30 Z" stroke="#00d9ff" strokeWidth="2" />
            <path d="M6 42 L30 46 Q34 47 32 42 L8 37 Z" stroke="#00d9ff" strokeWidth="2" />
          </svg>
        </div>
        <svg className="ticket-brush-underline" viewBox="0 0 300 22" aria-hidden="true">
          <path d="M10 17 Q145 2 292 8 Q210 11 10 17 Z" fill="#ffc928" />
        </svg>

        <div className="ticket-drag-hand" aria-hidden="true">
          <svg viewBox="0 0 72 72" width="66" height="66" fill="none">
            {/* Cyan Burst Rays */}
            <path d="M27 12 L27 3 M17 16 L11 9 M37 16 L43 9 M13 26 L5 26 M41 26 L49 26" stroke="#00d9ff" strokeWidth="3" strokeLinecap="round" />
            {/* White-outlined Hand */}
            <path
              d="M25 36 V19.5 C25 16.5 29.5 16.5 29.5 19.5 V34 L33 31.2 C35.2 29.6 38.5 31.2 38.5 34 V36 L41.8 33.4 C44 31.8 46.8 33.4 46.8 36 V38.5 L49.8 36.8 C52 35.6 54.5 37.2 54.5 40 V49 C54.5 57.5 47.5 63 39 63 H32.5 C25.5 63 20.5 57.5 17.8 51 L14 42.5 C12.8 40 15.6 37.6 18.4 39.2 L25 44.5 Z"
              fill="rgba(5, 17, 51, 0.85)"
              stroke="#ffffff"
              strokeWidth="3"
              strokeLinejoin="round"
            />
          </svg>
        </div>
      </div>
    </div>
  );
}

function AuctionTicketModalApp() {
  const [modalMode, setModalMode] = useState(null); // 'create' | 'join' | null
  const [isMobile, setIsMobile] = useState(typeof window !== 'undefined' ? window.innerWidth < 740 : false);
  const [franchises, setFranchises] = useState([]);

  // Create Room State
  const [purse, setPurse] = useState(500);
  const [animeMode, setAnimeMode] = useState('all');
  const [singleAnime, setSingleAnime] = useState('');
  const [selectedAnimeSet, setSelectedAnimeSet] = useState([]);
  const [formsMode, setFormsMode] = useState('SINGLE_BASE');
  const [createTorn, setCreateTorn] = useState(false);
  const [createError, setCreateError] = useState('');

  // Join Room State
  const [roomCode, setRoomCode] = useState('');
  const [codeStatus, setCodeStatus] = useState('idle');
  const [inviteBanner, setInviteBanner] = useState('');
  const [joinTorn, setJoinTorn] = useState(false);
  const [joinError, setJoinError] = useState('');

  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 740);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  useEffect(() => {
    window.AuctionTicketUI = {
      isOpen: () => modalMode !== null,
      openCreate: () => {
        setCreateTorn(false);
        setCreateError('');
        setModalMode('create');
      },
      closeCreate: () => setModalMode(m => (m === 'create' ? null : m)),
      openJoin: (prefillCode = '') => {
        setJoinTorn(false);
        setJoinError('');
        setCodeStatus('idle');
        if (prefillCode) {
          const clean = String(prefillCode).replace(/[^a-zA-Z0-9]/g, '').toUpperCase().slice(0, 8);
          setRoomCode(clean);
          setInviteBanner(`Invited to Room ${clean.length === 8 ? `${clean.slice(0, 4)}-${clean.slice(4)}` : clean}`);
        } else {
          setRoomCode('');
          setInviteBanner('');
        }
        setModalMode('join');
      },
      closeJoin: () => setModalMode(m => (m === 'join' ? null : m)),
      closeAll: () => setModalMode(null),
      handleServerError: message => {
        setModalMode(curr => {
          if (curr === 'join') {
            setJoinTorn(false);
            setCodeStatus('error');
            setJoinError(message || 'Room not found. Please check the code and try again.');
          } else if (curr === 'create') {
            setCreateTorn(false);
            setCreateError(message || 'Could not create room. Please try again.');
          }
          return curr;
        });
      },
      setFranchises: list => {
        if (Array.isArray(list) && list.length > 0) {
          setFranchises(list);
          setSingleAnime(prev => prev || list[0].id);
        }
      },
    };

    const onKeyDown = e => {
      if (e.key === 'Escape') setModalMode(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [modalMode]);

  const toggleFranchiseChip = fid => {
    setSelectedAnimeSet(prev =>
      prev.includes(fid) ? prev.filter(x => x !== fid) : [...prev, fid]
    );
    setCreateError('');
  };

  const handleCreateTear = () => {
    let selectedAnime = [];
    if (animeMode === 'single') {
      if (singleAnime) selectedAnime = [singleAnime];
    } else if (animeMode === 'multiple') {
      if (selectedAnimeSet.length === 0) {
        setCreateError('Please select at least one franchise for Selected Anime mode.');
        setCreateTorn(true);
        setTimeout(() => setCreateTorn(false), 120);
        return;
      }
      selectedAnime = selectedAnimeSet;
    }

    setCreateTorn(true);
    setCreateError('');
    if (typeof window.triggerCreateRoomFromTicket === 'function') {
      window.triggerCreateRoomFromTicket({
        starting_purse: Number(purse) || 500,
        anime_mode: animeMode,
        selected_anime: selectedAnime,
        forms_mode: formsMode,
      });
    }
  };

  const handleJoinTear = () => {
    const raw = roomCode.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
    if (raw.length < 4) {
      setCodeStatus('error');
      setJoinError('Please enter the 8-character Room Code before tearing!');
      setJoinTorn(true);
      setTimeout(() => setJoinTorn(false), 120);
      return;
    }
    const formatted = raw.length === 8 ? `${raw.slice(0, 4)}-${raw.slice(4)}` : raw;
    setJoinTorn(true);
    setJoinError('');
    if (typeof window.triggerJoinRoomFromTicket === 'function') {
      window.triggerJoinRoomFromTicket(formatted);
    }
  };

  if (!modalMode) return null;

  const ticketWidth = isMobile ? 420 : 1140;
  const ticketHeight = isMobile ? 730 : 540;
  const stubSize = isMobile ? 235 : 460;

  return (
    <div
      className="ticket-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={modalMode === 'create' ? 'Create Auction Room Ticket' : 'Join Existing Room Ticket'}
      onClick={e => {
        if (e.target === e.currentTarget) setModalMode(null);
      }}
    >
      <div className="auction-ticket-shell">
        <button
          type="button"
          className="ticket-shell-close"
          aria-label="Close"
          onClick={() => setModalMode(null)}
        >
          &times;
        </button>

        {modalMode === 'create' ? (
          <TearTicket
            orientation={isMobile ? 'vertical' : 'horizontal'}
            width={ticketWidth}
            height={ticketHeight}
            stubSize={stubSize}
            radius={24}
            holes={14}
            holeSize={8}
            notch={11}
            roughness={0}
            tearAngle={30}
            stretch={30}
            resistance={0.45}
            rotate={0}
            tilt={!isMobile}
            tiltMax={3}
            tiltReach={260}
            parallax={8}
            perspective={1200}
            background="#061438"
            stubBackground="#061438"
            color="#ffffff"
            border
            borderColor="#00d9ff"
            borderWidth={2}
            recenter
            torn={createTorn}
            onTear={handleCreateTear}
            ariaLabel="Tear off stub to create auction room"
            className="auction-tear-ticket"
            stub={<TicketStubArtwork verb="START" />}
          >
            <div className="ticket-left-panel">
              <div className="ticket-scenery-bg" aria-hidden="true" />
              <DecorativeClouds side="left" />
              {PETALS.slice(0, 3).map(p => (
                <span
                  key={p.id}
                  className="ticket-petal"
                  style={{ left: p.left, top: p.top, animationDelay: p.delay, width: p.size, height: p.size * 0.72 }}
                  aria-hidden="true"
                />
              ))}

              <div className="ticket-settings-inner">
                <div className="ticket-panel-header">
                  <SlashBars count={4} />
                  <IconGear />
                  <h2>
                    MANAGE <span>SETTINGS</span>
                  </h2>
                  <SlashBars count={5} />
                </div>

                {/* A. Starting Purse Per Player */}
                <div className="ticket-field-group">
                  <label htmlFor="ticket-purse-select" className="ticket-field-label">
                    <IconPurse /> STARTING PURSE PER PLAYER
                  </label>
                  <select
                    id="ticket-purse-select"
                    className="ticket-select"
                    value={purse}
                    onChange={e => setPurse(Number(e.target.value))}
                  >
                    <option value={250}>₹250 (Fast / Tactical)</option>
                    <option value={500}>₹500 (Official Default)</option>
                    <option value={1000}>₹1,000 (Deep Strategy)</option>
                    <option value={2000}>₹2,000 (High Roller)</option>
                  </select>
                </div>

                {/* B. Choose Auction Mode */}
                <div className="ticket-field-group">
                  <div className="ticket-field-label">
                    <IconStar /> CHOOSE AUCTION MODE
                  </div>
                  <div className="ticket-mode-grid">
                    {AUCTION_MODES.map(m => (
                      <button
                        key={m.id}
                        type="button"
                        className={`ticket-mode-card ${animeMode === m.id ? 'selected' : ''}`}
                        onClick={() => {
                          setAnimeMode(m.id);
                          setCreateError('');
                        }}
                      >
                        <span className="ticket-mode-icon">{m.icon}</span>
                        <span className="ticket-mode-label">{m.label}</span>
                      </button>
                    ))}
                  </div>

                  {animeMode === 'single' && (
                    <div className="ticket-dynamic-sub">
                      <select
                        id="ticket-single-anime-select"
                        className="ticket-select ticket-select--compact"
                        value={singleAnime}
                        onChange={e => setSingleAnime(e.target.value)}
                      >
                        {franchises.map(f => (
                          <option key={f.id} value={f.id}>
                            {f.name} ({f.character_count || 0})
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {animeMode === 'multiple' && (
                    <div className="ticket-dynamic-sub ticket-chips-scroll">
                      {franchises.map(f => (
                        <button
                          key={f.id}
                          type="button"
                          className={`ticket-franchise-chip ${selectedAnimeSet.includes(f.id) ? 'active' : ''}`}
                          onClick={() => toggleFranchiseChip(f.id)}
                        >
                          {f.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* C. Character Forms & Transformations */}
                <div className="ticket-field-group">
                  <label htmlFor="ticket-forms-select" className="ticket-field-label">
                    <IconSwap /> CHARACTER FORMS &amp; TRANSFORMATIONS
                  </label>
                  <select
                    id="ticket-forms-select"
                    className="ticket-select"
                    value={formsMode}
                    onChange={e => setFormsMode(e.target.value)}
                  >
                    <option value="SINGLE_BASE">Base Form Only (One entry per character)</option>
                    <option value="SEPARATE_ENTRIES">Transformations as Separate Entries (SSJ, Ultra Instinct, Gear 5, etc.)</option>
                  </select>
                </div>

                {createError && <div className="ticket-error-msg">{createError}</div>}
              </div>
            </div>
          </TearTicket>
        ) : (
          <TearTicket
            orientation={isMobile ? 'vertical' : 'horizontal'}
            width={ticketWidth}
            height={ticketHeight}
            stubSize={stubSize}
            radius={24}
            holes={14}
            holeSize={8}
            notch={11}
            roughness={0}
            tearAngle={30}
            stretch={30}
            resistance={0.45}
            rotate={0}
            tilt={!isMobile}
            tiltMax={3}
            tiltReach={260}
            parallax={8}
            perspective={1200}
            background="#061438"
            stubBackground="#061438"
            color="#ffffff"
            border
            borderColor="#00d9ff"
            borderWidth={2}
            recenter
            torn={joinTorn}
            onTear={handleJoinTear}
            ariaLabel="Tear off stub to join existing room"
            className="auction-tear-ticket"
            stub={<TicketStubArtwork verb="JOIN" />}
          >
            <div className="ticket-left-panel">
              <div className="ticket-scenery-bg" aria-hidden="true" />
              <DecorativeClouds side="left" />
              {PETALS.slice(0, 3).map(p => (
                <span
                  key={p.id}
                  className="ticket-petal"
                  style={{ left: p.left, top: p.top, animationDelay: p.delay, width: p.size, height: p.size * 0.72 }}
                  aria-hidden="true"
                />
              ))}

              <div className="ticket-settings-inner ticket-join-inner">
                <div className="ticket-panel-header">
                  <SlashBars count={4} />
                  <IconStar />
                  <h2>
                    JOIN <span>EXISTING ROOM</span>
                  </h2>
                  <SlashBars count={5} />
                </div>

                {inviteBanner && <div className="ticket-invite-pill">{inviteBanner}</div>}

                <div className="ticket-field-group">
                  <div className="ticket-field-label">
                    <IconPurse /> ENTER ROOM CODE
                  </div>
                  <div className="ticket-codeslots-wrap">
                    <CodeSlots
                      length={8}
                      value={roomCode}
                      status={codeStatus}
                      autoFocus
                      onChange={val => {
                        setRoomCode(val);
                        if (codeStatus !== 'idle' && val) setCodeStatus('idle');
                        if (joinError && val) setJoinError('');
                      }}
                      accentColor="#00d9ff"
                      inkColor="#67e8f9"
                      slotColor="#07183e"
                      digitColor="#030b25"
                      dangerColor="#ff3b30"
                      slotSize={isMobile ? 34 : 44}
                      gap={isMobile ? 5 : 8}
                      radius={10}
                      bounce={0.2}
                      settle={0.3}
                      rise={8}
                      cascade={20}
                      ariaLabel="Enter 8-character room code"
                    />
                  </div>
                  <p className="ticket-join-note">
                    Type or paste the 8-character room code (e.g. ANME-8F42), then drag the right stub to tear &amp; enter!
                  </p>
                </div>

                {joinError && <div className="ticket-error-msg">{joinError}</div>}
              </div>
            </div>
          </TearTicket>
        )}
      </div>
    </div>
  );
}

let characterCardRoot = null;

window.AuctionCharacterTicketUI = {
  renderCharacter: (character, round = 1, maxPool = 16) => {
    const container = document.getElementById('active-pokemon-card');
    if (!container) return;
    container.className = 'active-auction-card is-profile-card-mode';
    container.style.background = 'transparent';
    container.style.border = 'none';
    container.style.boxShadow = 'none';
    container.style.padding = '0';
    if (!characterCardRoot) {
      characterCardRoot = createRoot(container);
    }
    characterCardRoot.render(
      <AuctionCharacterCard character={character} round={round} maxPool={maxPool} />
    );
  },
};

// Mount React app into dedicated root container
function mountAuctionTicketUI() {
  let rootEl = document.getElementById('auction-ticket-react-root');
  if (!rootEl) {
    rootEl = document.createElement('div');
    rootEl.id = 'auction-ticket-react-root';
    document.body.appendChild(rootEl);
  }
  const root = createRoot(rootEl);
  root.render(<AuctionTicketModalApp />);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', mountAuctionTicketUI);
} else {
  mountAuctionTicketUI();
}
