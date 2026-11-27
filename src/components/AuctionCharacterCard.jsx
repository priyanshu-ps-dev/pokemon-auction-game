import React from 'react';
import './AuctionCharacterCard.css';

export default function AuctionCharacterCard({ character, round = 1 }) {
  if (!character) return null;

  const fallbackUrl = `/api/avatar/${encodeURIComponent(
    character.id || String(character.name || 'char').toLowerCase().replace(/\s+/g, '_')
  )}`;
  const imgSrc = character.image || fallbackUrl;

  const types = Array.isArray(character.types) ? character.types : [];
  const hasForm = character.current_form && character.current_form !== 'Base';
  const franchiseLabel = character.anime_name || 'FEATURED';
  const power = Number(character.power_rating || 0).toFixed(1);
  const tier = character.power_tier || 'B';
  const role = character.role || character.category || character.species || 'Fighter';
  const description = character.description || 'Verified combat profile available for this fighter.';
  const techniques = (character.techniques || character.abilities || []).slice(0, 3);
  const stats = character.stats || {};
  const statRows = [
    ['STR', stats.strength],
    ['SPD', stats.speed],
    ['DUR', stats.durability],
    ['ENG', stats.energy_projection ?? stats.special_abilities],
  ].filter(([, value]) => Number.isFinite(Number(value)));

  return (
    <div className="otaku-char-card-wrap" key={`${character.id || character.name}-${round}`}>
      <div className="otaku-cyan-card">
        <div className="otaku-cyan-card-inner">
          <div className="otaku-cyan-card-art">
            <img
              src={imgSrc}
              alt={character.name || 'Character'}
              className="otaku-cyan-card-img"
              onError={(e) => {
                if (e.currentTarget.dataset.fallbackApplied) return;
                e.currentTarget.dataset.fallbackApplied = '1';
                e.currentTarget.src = fallbackUrl;
              }}
            />
            <div className="otaku-cyan-card-scrim" />
          </div>

          <div className="otaku-cyan-card-meta">
            <h2 className="otaku-cyan-card-name">{character.name || 'Unknown Character'}</h2>
            {(hasForm || types.length > 0) && (
              <div className="otaku-cyan-card-sub">
                {hasForm ? `⚡ ${character.current_form}` : ''}
                {hasForm && types.length > 0 ? ' • ' : ''}
                {types.join(' • ')}
              </div>
            )}
            <div className="otaku-cyan-card-badge">
              <span className="otaku-featured-star">★</span>
              <span>{franchiseLabel}</span>
            </div>
            <div className="otaku-power-row" aria-label={`Power rating ${power}, tier ${tier}`}>
              <span><b>{power}</b> POWER</span>
              <span className={`otaku-tier-chip tier-${tier.replace('+', '-plus')}`}>{tier} TIER</span>
            </div>
            <p className="otaku-character-role">{role}</p>
            {statRows.length > 0 && (
              <div className="otaku-public-stats">
                {statRows.map(([label, value]) => (
                  <span key={label}><b>{label}</b> {value}</span>
                ))}
              </div>
            )}
            <details className="otaku-info-card">
              <summary>Character Info</summary>
              <p>{description}</p>
              {techniques.length > 0 && (
                <div className="otaku-technique-list">
                  {techniques.map((technique) => <span key={technique}>{technique}</span>)}
                </div>
              )}
            </details>
          </div>
        </div>
      </div>
    </div>
  );
}
