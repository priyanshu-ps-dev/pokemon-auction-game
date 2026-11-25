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
          </div>
        </div>
      </div>
    </div>
  );
}
