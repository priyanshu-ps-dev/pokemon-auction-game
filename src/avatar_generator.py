"""
Dynamic SVG Avatar Generator for Anime Characters
=================================================
Produces high-aesthetic, lightweight, 100% reliable SVG avatars
with custom franchise color palettes, energy symbols, and power tier badges.
Guarantees zero broken image links across any device.
"""

from typing import Dict, Optional

FRANCHISE_PALETTES: Dict[str, Dict[str, str]] = {
    "dragon_ball": {"bg1": "#dc2626", "bg2": "#f59e0b", "accent": "#fef08a", "symbol": "💥"},
    "naruto": {"bg1": "#ea580c", "bg2": "#eab308", "accent": "#fed7aa", "symbol": "🌀"},
    "one_piece": {"bg1": "#0284c7", "bg2": "#f59e0b", "accent": "#bae6fd", "symbol": "☠️"},
    "bleach": {"bg1": "#4338ca", "bg2": "#06b6d4", "accent": "#c7d2fe", "symbol": "⚔️"},
    "jujutsu_kaisen": {"bg1": "#581c87", "bg2": "#ec4899", "accent": "#f5d0fe", "symbol": "👁️"},
    "demon_slayer": {"bg1": "#0f766e", "bg2": "#10b981", "accent": "#ccfbf1", "symbol": "🌊"},
    "attack_on_titan": {"bg1": "#3f6212", "bg2": "#84cc16", "accent": "#ecfccb", "symbol": "🛡️"},
    "one_punch_man": {"bg1": "#be123c", "bg2": "#fbbf24", "accent": "#ffe4e6", "symbol": "👊"},
    "hunter_x_hunter": {"bg1": "#15803d", "bg2": "#3b82f6", "accent": "#dcfce7", "symbol": "⚡"},
    "my_hero_academia": {"bg1": "#1d4ed8", "bg2": "#ef4444", "accent": "#bfdbfe", "symbol": "🦸"},
    "black_clover": {"bg1": "#374151", "bg2": "#f59e0b", "accent": "#f3f4f6", "symbol": "♣️"},
    "chainsaw_man": {"bg1": "#b91c1c", "bg2": "#111827", "accent": "#fca5a5", "symbol": "🩸"},
    "solo_leveling": {"bg1": "#0369a1", "bg2": "#6366f1", "accent": "#7dd3fc", "symbol": "🗡️"},
    "jojo": {"bg1": "#7c3aed", "bg2": "#ec4899", "accent": "#ddd6fe", "symbol": "⭐"},
    "fullmetal_alchemist": {"bg1": "#b45309", "bg2": "#dc2626", "accent": "#fef3c7", "symbol": "☿"},
    "tokyo_ghoul": {"bg1": "#881337", "bg2": "#0f172a", "accent": "#fda4af", "symbol": "☕"},
    "death_note": {"bg1": "#18181b", "bg2": "#991b1b", "accent": "#e4e4e7", "symbol": "🍎"},
    "fairy_tail": {"bg1": "#c2410c", "bg2": "#e11d48", "accent": "#ffedd5", "symbol": "🔥"},
    "haikyuu": {"bg1": "#c2410c", "bg2": "#0284c7", "accent": "#ffedd5", "symbol": "🏐"},
    "blue_lock": {"bg1": "#1e40af", "bg2": "#06b6d4", "accent": "#dbeafe", "symbol": "⚽"},
    "pokemon": {"bg1": "#2563eb", "bg2": "#eab308", "accent": "#dbeafe", "symbol": "⚡"},
    "marvel": {"bg1": "#b91c1c", "bg2": "#f59e0b", "accent": "#fef08a", "symbol": "M"}
}

DEFAULT_PALETTE = {"bg1": "#1e293b", "bg2": "#3b82f6", "accent": "#93c5fd", "symbol": "✨"}


def generate_character_svg(char: dict) -> str:
    """Generates a fallback SVG avatar when external artwork is unavailable."""
    anime_id = char.get("anime_id", "pokemon")
    name = char.get("name", "Unknown Character")
    anime_name = char.get("anime_name", "Anime")
    tier = char.get("power_tier", "B")
    
    palette = FRANCHISE_PALETTES.get(anime_id, DEFAULT_PALETTE)
    bg1 = palette["bg1"]
    bg2 = palette["bg2"]
    accent = palette["accent"]
    symbol = palette["symbol"]

    # Extract initials
    words = [w for w in name.replace("(", "").replace(")", "").split() if w]
    initials = (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1:2])).upper() if words else "AN"
    
    # Truncate display name
    short_name = name if len(name) <= 16 else name[:14] + "…"
    short_anime = anime_name if len(anime_name) <= 18 else anime_name[:16] + "…"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 280 280" width="280" height="280">
  <defs>
    <radialGradient id="halo_{anime_id}" cx="50%" cy="40%" r="60%">
      <stop offset="0%" stop-color="{bg2}" stop-opacity="0.45"/>
      <stop offset="65%" stop-color="{bg1}" stop-opacity="0.15"/>
      <stop offset="100%" stop-color="#0a0d14" stop-opacity="0.95"/>
    </radialGradient>
    <linearGradient id="grad_{anime_id}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{bg1}"/>
      <stop offset="100%" stop-color="{bg2}"/>
    </linearGradient>
    <linearGradient id="tier_grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#ffd700"/>
      <stop offset="100%" stop-color="#f59e0b"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="{bg1}" flood-opacity="0.4"/>
    </filter>
  </defs>

  <!-- Background Base -->
  <rect width="280" height="280" rx="28" fill="#0d111a"/>
  <rect width="280" height="280" rx="28" fill="url(#halo_{anime_id})"/>
  <rect width="278" height="278" x="1" y="1" rx="27" fill="none" stroke="{bg1}" stroke-opacity="0.4" stroke-width="1.5"/>

  <!-- Tier Badge (Top-Right) -->
  <rect x="210" y="18" width="52" height="26" rx="13" fill="#182030" stroke="url(#tier_grad)" stroke-width="1.5"/>
  <text x="236" y="36" font-family="'Outfit', system-ui, sans-serif" font-size="12" font-weight="900" fill="#ffd700" text-anchor="middle">{tier}</text>

  <!-- Anime Symbol (Top-Left) -->
  <text x="32" y="38" font-size="20">{symbol}</text>

  <!-- Central Avatar Disc -->
  <g filter="url(#shadow)">
    <circle cx="140" cy="115" r="58" fill="#141c2b" stroke="url(#grad_{anime_id})" stroke-width="3.5"/>
    <circle cx="140" cy="115" r="50" fill="url(#grad_{anime_id})" opacity="0.25"/>
    <text x="140" y="132" font-family="'Outfit', system-ui, sans-serif" font-size="38" font-weight="900" fill="{accent}" text-anchor="middle" letter-spacing="1">{initials}</text>
  </g>

  <!-- Character & Anime Meta Pill (Bottom) -->
  <g transform="translate(140, 215)">
    <!-- Character Name -->
    <text x="0" y="0" font-family="'Outfit', system-ui, sans-serif" font-size="16" font-weight="800" fill="#f8fafc" text-anchor="middle">{short_name}</text>
    <!-- Franchise Subtitle -->
    <rect x="-65" y="12" width="130" height="22" rx="11" fill="#182030" stroke="{bg1}" stroke-opacity="0.6" stroke-width="1"/>
    <text x="0" y="27" font-family="'Outfit', system-ui, sans-serif" font-size="11" font-weight="700" fill="{accent}" text-anchor="middle" text-transform="uppercase" letter-spacing="0.5">{short_anime}</text>
  </g>
</svg>"""
