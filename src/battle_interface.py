"""
Shared Battle Interface (Phase 2)
=================================
Defines the common combatant, action, and battle-result contracts used by
both the Pokémon Battle Engine (src/battle_engine.py) and the Anime Battle
Engine (src/anime_battle_engine.py), without forcing identical mechanics.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BattleAction:
    """Represents a single turn decision for a combatant."""
    action_type: str  # "attack", "switch", "transform", "pass"
    move_id: Optional[Any] = None
    switch_index: Optional[int] = None
    transformation_id: Optional[str] = None


class BaseCombatant(ABC):
    """Common read/act interface exposed by both Pokémon and Anime combatants."""

    @property
    @abstractmethod
    def combatant_id(self) -> str:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def system(self) -> str:
        """'pokemon' or 'anime'"""
        ...

    @property
    @abstractmethod
    def current_hp(self) -> int:
        ...

    @property
    @abstractmethod
    def max_hp(self) -> int:
        ...

    @property
    @abstractmethod
    def is_fainted(self) -> bool:
        ...

    @property
    @abstractmethod
    def status(self) -> Optional[str]:
        ...

    @property
    @abstractmethod
    def effective_speed(self) -> float:
        ...

    @abstractmethod
    def get_available_moves(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def get_available_transformations(self) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def to_summary_dict(self) -> Dict[str, Any]:
        ...


@dataclass
class BattleResult:
    """Outcome of a simulated 1v1 team battle."""
    winner_id: Optional[str]
    loser_id: Optional[str]
    is_draw: bool
    reason: str
    turns_played: int
    seed: int
    player_a_remaining_hp: int
    player_b_remaining_hp: int
    player_a_remaining_count: int
    player_b_remaining_count: int
    turn_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "winner_id": self.winner_id,
            "loser_id": self.loser_id,
            "is_draw": self.is_draw,
            "reason": self.reason,
            "turns_played": self.turns_played,
            "seed": self.seed,
            "player_a_remaining_hp": self.player_a_remaining_hp,
            "player_b_remaining_hp": self.player_b_remaining_hp,
            "player_a_remaining_count": self.player_a_remaining_count,
            "player_b_remaining_count": self.player_b_remaining_count,
            "turn_log": self.turn_log,
        }
