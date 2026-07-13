#!/usr/bin/env python3
"""
================================================================================
 THE EXCHANGE — Historical U.S. Currency Trading Card Game
================================================================================
A complete, single-file, monolithic TCG where every card is a real historical
U.S. coin or banknote. Players build "purses" through math-based exchanges,
historical synergies, and strategic trades to outmaneuver opponents.

Tagline: "Collect history. Master the exchange. Build your fortune."

HOW TO RUN:
    python TCG.py

FEATURES:
    - 200+ unique cards covering all major U.S. coins & notes (1792-present)
    - Rarity system: Common (55%), Uncommon (28%), Rare (12%),
      Ultra-Rare (3.5%), Legendary (1%), Secret Rare (0.5%)
    - Full interactive human vs AI mode with draw, play, make change,
      challenge, and ability activation
    - Booster pack generator respecting rarity ratios
    - Deck builder with validation (min Commons, size limits)
    - Save/load game state (JSON)
    - Card database browser
    - AI simulation mode
    - Event cards (Inflation, Panic, Gold Standard, etc.)
    - Real ability resolution (bonuses, multipliers, steals, immunity)
    - Colorful terminal output with emojis

CONTROLS (in-game):
    Type the number or letter of your choice at each prompt.
    Type 'help' for rules. Type 'quit' to exit.

REQUIRES: Python 3.8+ (no external packages needed)
================================================================================
"""

from __future__ import annotations

import random
import json
import copy
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Set

# UTF-8 stdout on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
except (AttributeError, TypeError):
    pass

# =============================================================================
# SECTION 1 - CONSTANTS & COLORS
# =============================================================================

class C:
    """ANSI color codes for terminal output."""
    RESET   = '\033[0m'
    BOLD    = '\033[1m'
    DIM     = '\033[2m'
    RED     = '\033[91m'
    GREEN   = '\033[92m'
    YELLOW  = '\033[93m'
    BLUE    = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN    = '\033[96m'
    WHITE   = '\033[97m'
    GREY    = '\033[90m'

def clr(text, color):
    return f"{color}{text}{C.RESET}"

RARITY_NAMES  = {'C': 'Common', 'U': 'Uncommon', 'R': 'Rare',
                 'UR': 'Ultra-Rare', 'L': 'Legendary', 'SR': 'Secret Rare'}
RARITY_EMOJI  = {'C': '\u26aa', 'U': '\U0001f535', 'R': '\U0001f7e1',
                 'UR': '\U0001f7e3', 'L': '\U0001f534', 'SR': '\u2b50'}
RARITY_COLOR  = {'C': C.WHITE, 'U': C.CYAN, 'R': C.YELLOW,
                 'UR': C.MAGENTA, 'L': C.RED, 'SR': C.BOLD + C.YELLOW}
RARITY_RATIOS = {'C': 0.55, 'U': 0.28, 'R': 0.12, 'UR': 0.035, 'L': 0.01, 'SR': 0.005}
TYPE_EMOJI = {'Coin': '\U0001fa99', 'Note': '\U0001f4c4', 'Event': '\u26a1'}

# =============================================================================
# SECTION 2 - CARD DATACLASS
# =============================================================================

@dataclass
class Card:
    """A single trading card representing a historical U.S. coin or note."""
    name: str
    value: float
    card_type: str
    composition: str
    era: str
    rarity: str
    ability: str
    ability_desc: str
    flavor: str
    card_id: str
    denomination: str = ''
    year_range: str = ''
    tags: List[str] = field(default_factory=list)

    def display_name(self) -> str:
        return f"{self.name} ({self.year_range})" if self.year_range else self.name

    def rarity_str(self) -> str:
        return f"{RARITY_EMOJI.get(self.rarity, '?')} {RARITY_NAMES.get(self.rarity, '?')}"

    def short_str(self) -> str:
        return f"[{self.rarity}] {self.name} ${self.value:.4f}"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> 'Card':
        return Card(**d)

# =============================================================================
# SECTION 3 - DECK & PURSE
# =============================================================================

class Deck:
    """A player's draw deck."""
    def __init__(self, cards: List[Card]):
        self.cards: List[Card] = cards[:]
        self.discard: List[Card] = []

    def draw(self, n: int = 1) -> List[Card]:
        drawn = []
        for _ in range(n):
            if not self.cards:
                self.reshuffle()
            if self.cards:
                drawn.append(self.cards.pop(0))
        return drawn

    def reshuffle(self):
        self.cards = self.discard[:]
        self.discard = []
        self.shuffle()

    def shuffle(self):
        random.shuffle(self.cards)

    def remaining(self) -> int:
        return len(self.cards)

    def add_to_discard(self, cards: List[Card]):
        self.discard.extend(cards)

    def to_dict(self) -> dict:
        return {'cards': [c.to_dict() for c in self.cards],
                'discard': [c.to_dict() for c in self.discard]}

    @staticmethod
    def from_dict(d: dict) -> Deck:
        deck = Deck([Card.from_dict(c) for c in d.get('cards', [])])
        deck.discard = [Card.from_dict(c) for c in d.get('discard', [])]
        return deck

class Purse:
    """A player's tableau of played cards - their 'portfolio'."""
    def __init__(self):
        self.cards: List[Card] = []
        self.bonuses: List[Tuple[str, float]] = []
        self.multipliers: List[Tuple[str, float]] = []  # whole-purse multipliers
        self.card_multipliers: Dict[str, List[Tuple[str, float]]] = {}  # per-card multipliers by card_id

    def add(self, card: Card):
        self.cards.append(card)

    def remove(self, card: Card) -> bool:
        if card in self.cards:
            self.cards.remove(card)
            self.card_multipliers.pop(card.card_id, None)
            return True
        return False

    def base_value(self) -> float:
        return sum(c.value for c in self.cards)

    def total_value(self) -> float:
        val = 0.0
        for card in self.cards:
            card_val = card.value
            for desc, mult in self.card_multipliers.get(card.card_id, []):
                card_val *= mult
            val += card_val
        for desc, amount in self.bonuses:
            val += amount
        for desc, mult in self.multipliers:
            val *= mult
        return val

    def clear_bonuses(self):
        self.bonuses = []
        self.multipliers = []
        self.card_multipliers = {}

    def add_bonus(self, desc: str, amount: float):
        self.bonuses.append((desc, amount))

    def add_multiplier(self, desc: str, mult: float):
        self.multipliers.append((desc, mult))

    def add_card_multiplier(self, card_id: str, desc: str, mult: float):
        if card_id not in self.card_multipliers:
            self.card_multipliers[card_id] = []
        self.card_multipliers[card_id].append((desc, mult))

    def has_tag(self, tag: str) -> bool:
        return any(tag in c.tags for c in self.cards)

    def count_tag(self, tag: str) -> int:
        return sum(1 for c in self.cards if tag in c.tags)

    def count_composition(self, comp: str) -> int:
        return sum(1 for c in self.cards if c.composition == comp)

    def count_denomination(self, denom: str) -> int:
        return sum(1 for c in self.cards if c.denomination == denom)

    def count_era(self, era: str) -> int:
        return sum(1 for c in self.cards if c.era == era)

    def __str__(self):
        return f"Purse: ${self.total_value():.2f} ({len(self.cards)} cards)"

    def to_dict(self) -> dict:
        return {
            'cards': [c.to_dict() for c in self.cards],
            'bonuses': self.bonuses,
            'multipliers': self.multipliers,
            'card_multipliers': self.card_multipliers,
        }

    @staticmethod
    def from_dict(d: dict) -> Purse:
        p = Purse()
        p.cards = [Card.from_dict(c) for c in d.get('cards', [])]
        p.bonuses = [tuple(b) for b in d.get('bonuses', [])]
        p.multipliers = [tuple(m) for m in d.get('multipliers', [])]
        p.card_multipliers = {k: [tuple(x) for x in v] for k, v in d.get('card_multipliers', {}).items()}
        return p

# =============================================================================
# SECTION 4 - PLAYER
# =============================================================================

class Player:
    """A game player (human or AI)."""
    def __init__(self, name: str, deck: Deck, is_ai: bool = False):
        self.name = name
        self.deck = deck
        self.hand: List[Card] = []
        self.purse = Purse()
        self.is_ai = is_ai
        self.abilities_used: Dict[str, int] = {}
        self.immune: bool = False
        self.skipped_next: bool = False
        self.challenge_cooldown: int = 0  # turns until can challenge again

    def draw(self, n: int = 1):
        drawn = self.deck.draw(n)
        self.hand.extend(drawn)
        return drawn

    def play_to_purse(self, card: Card) -> bool:
        if card in self.hand:
            self.hand.remove(card)
            self.purse.add(card)
            return True
        return False

    def discard_card(self, card: Card) -> bool:
        if card in self.hand:
            self.hand.remove(card)
            self.deck.add_to_discard([card])
            return True
        return False

    def hand_value(self) -> float:
        return sum(c.value for c in self.hand)

    def hand_limit(self) -> int:
        return 10

    def to_dict(self) -> dict:
        return {
            'name': self.name, 'deck': self.deck.to_dict(),
            'hand': [c.to_dict() for c in self.hand],
            'purse': self.purse.to_dict(), 'is_ai': self.is_ai,
            'abilities_used': self.abilities_used,
            'immune': self.immune, 'skipped_next': self.skipped_next,
            'challenge_cooldown': self.challenge_cooldown,
        }

    @staticmethod
    def from_dict(d: dict) -> Player:
        p = Player(d['name'], Deck.from_dict(d['deck']), d.get('is_ai', False))
        p.hand = [Card.from_dict(c) for c in d.get('hand', [])]
        p.purse = Purse.from_dict(d.get('purse', {}))
        p.abilities_used = d.get('abilities_used', {})
        p.immune = d.get('immune', False)
        p.skipped_next = d.get('skipped_next', False)
        p.challenge_cooldown = d.get('challenge_cooldown', 0)
        return p

# =============================================================================
# SECTION 5 - CARD DATABASE (200+ unique cards)
# =============================================================================

def _c(name, value, ctype, comp, era, rarity, ability, ability_desc,
       flavor, cid, denom='', years='', tags=None):
    """Helper to create a Card with less verbosity."""
    return Card(name=name, value=value, card_type=ctype, composition=comp,
                era=era, rarity=rarity, ability=ability, ability_desc=ability_desc,
                flavor=flavor, card_id=cid, denomination=denom,
                year_range=years, tags=tags or [])

def create_base_set() -> List[Card]:
    """Create the full Base Set of 200+ unique cards."""
    cards = []
    # Placeholder - cards added in _build_card_db
    return _build_card_db()

def _build_card_db() -> List[Card]:
    """Build the complete card database."""
    cards = []

    # === COMMONS (C) - Low-value building blocks, <$0.25 ===

    # -- Half Cents --
    cards.append(_c("1793 Flowing Hair Half Cent",0.005,"Coin","Copper","1790s","C","half_measure","+0.01 if paired with a Cent","Smallest U.S. coin ever minted.","HC-001","Half Cent","1793",["copper","half_cent"]))
    cards.append(_c("1794 Draped Bust Half Cent",0.005,"Coin","Copper","1790s","C","half_measure","+0.01 if paired with a Cent","Improved design after first year.","HC-002","Half Cent","1794-1797",["copper","half_cent"]))
    cards.append(_c("1809 Classic Head Half Cent",0.005,"Coin","Copper","1800s","C","copper_rush","+0.005 per copper coin (max 0.05)","Introduced during copper shortage.","HC-003","Half Cent","1809-1836",["copper","half_cent"]))
    cards.append(_c("1840 Braided Hair Half Cent",0.005,"Coin","Copper","1800s","C","copper_rush","+0.005 per copper coin (max 0.05)","Last design of the half cent series.","HC-004","Half Cent","1840-1857",["copper","half_cent"]))

    # -- Large Cents --
    cards.append(_c("1793 Flowing Hair Large Cent",0.01,"Coin","Copper","1790s","C","foundation","+0.01 base bonus","First coins struck at Philadelphia Mint.","LC-001","Large Cent","1793",["copper","large_cent"]))
    cards.append(_c("1795 Draped Bust Large Cent",0.01,"Coin","Copper","1790s","C","foundation","+0.01 base bonus","Designed by Robert Scot.","LC-002","Large Cent","1795-1807",["copper","large_cent"]))
    cards.append(_c("1816 Classic Head Large Cent",0.01,"Coin","Copper","1800s","C","copper_rush","+0.005 per copper coin (max 0.05)","Resumed after 1815 mint fire.","LC-003","Large Cent","1816-1839",["copper","large_cent"]))
    cards.append(_c("1843 Coronet Large Cent",0.01,"Coin","Copper","1800s","C","copper_rush","+0.005 per copper coin (max 0.05)","Also called Matron Head.","LC-004","Large Cent","1839-1857",["copper","large_cent"]))
    cards.append(_c("1857 Braided Hair Large Cent",0.01,"Coin","Copper","1850s","C","last_of_kind","+0.02 if last of denomination","Final year of large cent.","LC-005","Large Cent","1857",["copper","large_cent"]))

    # -- Small Cents --
    cards.append(_c("1856 Flying Eagle Cent",0.01,"Coin","Copper-Nickel","1850s","C","foundation","+0.01 base bonus","Pattern/transition year.","SC-001","Small Cent","1856-1858",["copper","small_cent"]))
    cards.append(_c("1859 Indian Head Cent",0.01,"Coin","Copper-Nickel","1850s","C","foundation","+0.01 base bonus","Designed by James Longacre.","SC-002","Small Cent","1859-1864",["copper","small_cent"]))
    cards.append(_c("1864 Indian Head Cent Bronze",0.01,"Coin","Bronze","1860s","C","copper_rush","+0.005 per copper coin (max 0.05)","Switched to bronze during Civil War.","SC-003","Small Cent","1864-1909",["copper","small_cent","civil_war"]))
    cards.append(_c("1909-S VDB Lincoln Wheat Cent",0.01,"Coin","Bronze","1900s","C","foundation","+0.01 base bonus","First Lincoln cent with designer initials.","SC-004","Small Cent","1909",["copper","small_cent","lincoln"]))
    cards.append(_c("1910 Lincoln Wheat Cent",0.01,"Coin","Bronze","1900s","C","foundation","+0.01 base bonus","The Lincoln wheat cent icon.","SC-005","Small Cent","1910-1958",["copper","small_cent","lincoln"]))
    cards.append(_c("1943 Steel Lincoln Cent",0.01,"Coin","Steel","1940s","C","wartime","+0.02 if paired with wartime nickel","Steel cents to conserve copper for WWII.","SC-006","Small Cent","1943",["steel","small_cent","lincoln","wwii"]))
    cards.append(_c("1959 Lincoln Memorial Cent",0.01,"Coin","Bronze","1950s","C","foundation","+0.01 base bonus","Redesigned for Lincoln 150th birthday.","SC-007","Small Cent","1959-2008",["copper","small_cent","lincoln"]))
    cards.append(_c("2009 Lincoln Bicentennial Cent",0.01,"Coin","Copper Zinc","2000s","C","foundation","+0.01 base bonus","Four reverse designs honoring Lincoln.","SC-008","Small Cent","2009",["copper","small_cent","lincoln"]))
    cards.append(_c("2010 Lincoln Shield Cent",0.01,"Coin","Copper Zinc","2010s","C","foundation","+0.01 base bonus","Shield symbolizes Union preservation.","SC-009","Small Cent","2010-present",["copper","small_cent","lincoln"]))

    # -- Two-Cent --
    cards.append(_c("1864 Two-Cent Piece",0.02,"Coin","Bronze","1860s","C","first_trust","+0.01 if purse has 3+ copper","First U.S. coin with 'In God We Trust'.","TC-001","Two-Cent","1864-1873",["copper","two_cent","civil_war"]))

    # -- Three-Cent --
    cards.append(_c("1865 Three-Cent Nickel",0.03,"Coin","Copper-Nickel","1860s","C","small_change","+0.01 if purse has 5+ coins","Created for postage stamp purchases.","TN-001","Three-Cent","1865-1889",["copper","three_cent","civil_war"]))
    cards.append(_c("1851 Three-Cent Silver Trime",0.03,"Coin","Silver","1850s","C","silver_spark","+0.02 if paired with silver coin","Smallest U.S. silver coin ever.","TN-002","Three-Cent","1851-1873",["silver","three_cent"]))

    # -- Half Dimes --
    cards.append(_c("1794 Flowing Hair Half Dime",0.05,"Coin","Silver","1790s","C","silver_spark","+0.02 if paired with silver coin","First silver coins struck by U.S.","HD-001","Half Dime","1794-1795",["silver","half_dime"]))
    cards.append(_c("1829 Capped Bust Half Dime",0.05,"Coin","Silver","1800s","C","silver_spark","+0.02 if paired with silver coin","Reduced size from earlier issues.","HD-002","Half Dime","1829-1837",["silver","half_dime"]))
    cards.append(_c("1837 Liberty Seated Half Dime",0.05,"Coin","Silver","1800s","C","silver_spark","+0.02 if paired with silver coin","Gobrecht Seated Liberty design.","HD-003","Half Dime","1837-1873",["silver","half_dime"]))

    # -- Nickels --
    cards.append(_c("1866 Shield Nickel",0.05,"Coin","Copper-Nickel","1860s","C","foundation","+0.01 base bonus","First nickel five-cent piece.","NK-001","Nickel","1866-1883",["copper","nickel","civil_war"]))
    cards.append(_c("1883 Liberty V Nickel",0.05,"Coin","Copper-Nickel","1880s","C","foundation","+0.01 base bonus","Initially missing CENTS on reverse.","NK-002","Nickel","1883-1912",["copper","nickel"]))
    cards.append(_c("1913 Buffalo Nickel",0.05,"Coin","Copper-Nickel","1910s","C","foundation","+0.01 base bonus","Iconic American West design.","NK-003","Nickel","1913-1938",["copper","nickel"]))
    cards.append(_c("1938 Jefferson Nickel",0.05,"Coin","Copper-Nickel","1930s","C","foundation","+0.01 base bonus","Jefferson and Monticello for 70+ years.","NK-004","Nickel","1938-present",["copper","nickel"]))
    cards.append(_c("1942-P Wartime Silver Nickel",0.05,"Coin","Silver","1940s","C","wartime","+0.02 if paired with steel cent","Silver added to save nickel for war.","NK-005","Nickel","1942-1945",["silver","nickel","wwii"]))

    # -- Dimes --
    cards.append(_c("1796 Draped Bust Dime",0.10,"Coin","Silver","1790s","C","silver_spark","+0.02 if paired with silver coin","First dime design, small mintage.","DM-001","Dime","1796-1807",["silver","dime"]))
    cards.append(_c("1809 Capped Bust Dime",0.10,"Coin","Silver","1800s","C","silver_spark","+0.02 if paired with silver coin","John Reich Capped Bust design.","DM-002","Dime","1809-1837",["silver","dime"]))
    cards.append(_c("1837 Liberty Seated Dime",0.10,"Coin","Silver","1800s","C","silver_spark","+0.02 if paired with silver coin","Gobrecht Seated Liberty.","DM-003","Dime","1837-1891",["silver","dime"]))
    cards.append(_c("1892 Barber Dime",0.10,"Coin","Silver","1890s","C","silver_spark","+0.02 if paired with silver coin","Barber design across denominations.","DM-004","Dime","1892-1916",["silver","dime"]))
    cards.append(_c("1916 Mercury Dime",0.10,"Coin","Silver","1910s","C","silver_spark","+0.02 if paired with silver coin","Winged Liberty, mistaken for Mercury.","DM-005","Dime","1916-1945",["silver","dime"]))
    cards.append(_c("1946 Roosevelt Dime",0.10,"Coin","Silver","1940s","C","silver_spark","+0.02 if paired with silver coin","Honors FDR, founder of March of Dimes.","DM-006","Dime","1946-1964",["silver","dime"]))
    cards.append(_c("1965 Clad Roosevelt Dime",0.10,"Coin","Copper-Nickel","1960s","C","foundation","+0.01 base bonus","Silver removed from dimes in 1965.","DM-007","Dime","1965-present",["copper","dime"]))

    # -- Twenty-Cent --
    cards.append(_c("1875 Twenty-Cent Piece",0.20,"Coin","Silver","1870s","C","odd_denomination","+0.05 if no other 20c in purse","Short-lived, confused with quarter.","TW-001","Twenty-Cent","1875-1878",["silver","twenty_cent"]))

    # -- Quarters --
    cards.append(_c("1796 Draped Bust Quarter",0.25,"Coin","Silver","1790s","C","silver_spark","+0.02 if paired with silver coin","First quarter dollar, 6,146 minted.","QT-001","Quarter","1796-1807",["silver","quarter"]))
    cards.append(_c("1815 Capped Bust Quarter",0.25,"Coin","Silver","1800s","C","silver_spark","+0.02 if paired with silver coin","Reintroduced after production gap.","QT-002","Quarter","1815-1838",["silver","quarter"]))
    cards.append(_c("1838 Liberty Seated Quarter",0.25,"Coin","Silver","1800s","C","silver_spark","+0.02 if paired with silver coin","Long-running Seated Liberty.","QT-003","Quarter","1838-1891",["silver","quarter"]))
    cards.append(_c("1892 Barber Quarter",0.25,"Coin","Silver","1890s","C","silver_spark","+0.02 if paired with silver coin","Barber classical design.","QT-004","Quarter","1892-1916",["silver","quarter"]))
    cards.append(_c("1916 Standing Liberty Quarter",0.25,"Coin","Silver","1910s","C","silver_spark","+0.02 if paired with silver coin","MacNeil artistic Liberty design.","QT-005","Quarter","1916-1930",["silver","quarter"]))
    cards.append(_c("1932 Washington Quarter",0.25,"Coin","Silver","1930s","C","silver_spark","+0.02 if paired with silver coin","Commemorative for Washington 200th.","QT-006","Quarter","1932-1964",["silver","quarter"]))
    cards.append(_c("1965 Clad Washington Quarter",0.25,"Coin","Copper-Nickel","1960s","C","foundation","+0.01 base bonus","Transition to clad composition.","QT-007","Quarter","1965-1998",["copper","quarter"]))
    cards.append(_c("1999 State Quarter Delaware",0.25,"Coin","Copper-Nickel","1990s","C","foundation","+0.01 base bonus","First of 50 State Quarters program.","QT-008","Quarter","1999",["copper","quarter","state_quarter"]))
    cards.append(_c("2000 State Quarter Virginia",0.25,"Coin","Copper-Nickel","2000s","C","foundation","+0.01 base bonus","Jamestown and three ships.","QT-009","Quarter","2000",["copper","quarter","state_quarter"]))
    cards.append(_c("2009 DC Territories Quarter",0.25,"Coin","Copper-Nickel","2000s","C","foundation","+0.01 base bonus","Extended to D.C. and territories.","QT-010","Quarter","2009",["copper","quarter","state_quarter"]))
    cards.append(_c("2010 America the Beautiful Quarter",0.25,"Coin","Copper-Nickel","2010s","C","foundation","+0.01 base bonus","National Parks quarters, 56 designs.","QT-011","Quarter","2010-2021",["copper","quarter","state_quarter"]))

    # -- Half Dollars --
    cards.append(_c("1794 Flowing Hair Half Dollar",0.50,"Coin","Silver","1790s","C","silver_spark","+0.02 if paired with silver coin","First year of half dollar production.","HF-001","Half Dollar","1794-1795",["silver","half_dollar"]))
    cards.append(_c("1807 Capped Bust Half Dollar",0.50,"Coin","Silver","1800s","C","silver_spark","+0.02 if paired with silver coin","Most collected early half dollar.","HF-002","Half Dollar","1807-1839",["silver","half_dollar"]))
    cards.append(_c("1839 Liberty Seated Half Dollar",0.50,"Coin","Silver","1800s","C","silver_spark","+0.02 if paired with silver coin","Seated Liberty across denominations.","HF-003","Half Dollar","1839-1891",["silver","half_dollar"]))
    cards.append(_c("1892 Barber Half Dollar",0.50,"Coin","Silver","1890s","C","silver_spark","+0.02 if paired with silver coin","Barber utilitarian design.","HF-004","Half Dollar","1892-1915",["silver","half_dollar"]))
    cards.append(_c("1916 Walking Liberty Half Dollar",0.50,"Coin","Silver","1910s","C","silver_spark","+0.02 if paired with silver coin","Weinman masterpiece, revived on Eagle.","HF-005","Half Dollar","1916-1947",["silver","half_dollar"]))
    cards.append(_c("1948 Franklin Half Dollar",0.50,"Coin","Silver","1940s","C","silver_spark","+0.02 if paired with silver coin","Franklin and Liberty Bell.","HF-006","Half Dollar","1948-1963",["silver","half_dollar"]))
    cards.append(_c("1964 Kennedy Half Dollar",0.50,"Coin","Silver","1960s","C","silver_spark","+0.02 if paired with silver coin","Rushed after JFK assassination.","HF-007","Half Dollar","1964",["silver","half_dollar"]))
    cards.append(_c("1971 Clad Kennedy Half Dollar",0.50,"Coin","Copper-Nickel","1970s","C","foundation","+0.01 base bonus","Silver eliminated from halves.","HF-008","Half Dollar","1971-present",["copper","half_dollar"]))

    # -- Modern Dollar Coins (Commons) --
    cards.append(_c("1971 Eisenhower Dollar",1.00,"Coin","Copper-Nickel","1970s","C","foundation","+0.01 base bonus","Honors General and President Eisenhower.","DC-001","Dollar Coin","1971-1978",["copper","dollar_coin"]))
    cards.append(_c("1979 Susan B Anthony Dollar",1.00,"Coin","Copper-Nickel","1970s","C","foundation","+0.01 base bonus","Unpopular, similar to quarter size.","DC-002","Dollar Coin","1979-1999",["copper","dollar_coin"]))
    cards.append(_c("2000 Sacagawea Dollar",1.00,"Coin","Manganese Brass","2000s","C","foundation","+0.01 base bonus","Golden color, Lewis and Clark guide.","DC-003","Dollar Coin","2000-present",["copper","dollar_coin"]))
    cards.append(_c("2007 Presidential Dollar",1.00,"Coin","Manganese Brass","2000s","C","foundation","+0.01 base bonus","Edge-lettered, honoring Presidents.","DC-004","Dollar Coin","2007-2016",["copper","dollar_coin"]))
    cards.append(_c("2018 American Innovation Dollar",1.00,"Coin","Manganese Brass","2010s","C","foundation","+0.01 base bonus","Honoring innovators from each state.","DC-005","Dollar Coin","2018-present",["copper","dollar_coin"]))

    # -- Fractional Currency (Commons) --
    cards.append(_c("1862 5c Fractional Currency",0.05,"Note","Paper","1860s","C","fractional","+0.01 per note (max 0.05)","Postage currency during coin shortage.","FR-001","Fractional","1862-1876",["paper","fractional","civil_war"]))
    cards.append(_c("1862 10c Fractional Currency",0.10,"Note","Paper","1860s","C","fractional","+0.01 per note (max 0.05)","Paper substitute for silver coins.","FR-002","Fractional","1862-1876",["paper","fractional","civil_war"]))
    cards.append(_c("1863 25c Fractional Currency",0.25,"Note","Paper","1860s","C","fractional","+0.01 per note (max 0.05)","Fourth issue fractional currency.","FR-003","Fractional","1863-1876",["paper","fractional","civil_war"]))
    cards.append(_c("1863 50c Fractional Currency",0.50,"Note","Paper","1860s","C","fractional","+0.01 per note (max 0.05)","Largest fractional denomination.","FR-004","Fractional","1863-1876",["paper","fractional","civil_war"]))

    # -- Colonial/Continental (Commons) --
    cards.append(_c("1775 Continental Currency 1/3 Dollar",0.33,"Note","Paper","1770s","C","colonial","+0.05 if paired with another colonial","Early paper money of the Revolution.","CC-001","Continental","1775",["paper","colonial","colonial_era"]))
    cards.append(_c("1776 Continental Currency 1 Dollar",1.00,"Note","Paper","1770s","C","colonial","+0.05 if paired with another colonial","Not worth a Continental!","CC-002","Continental","1776",["paper","colonial","colonial_era"]))
    cards.append(_c("1779 Continental Currency 5 Dollar",5.00,"Note","Paper","1770s","C","colonial","+0.05 if paired with another colonial","Hyperinflation devastated value.","CC-003","Continental","1779",["paper","colonial","colonial_era"]))

    # === UNCOMMONS (U) - Mid-value cards, $1-$10 ===

    # -- Silver Dollars --
    cards.append(_c("1794 Flowing Hair Silver Dollar",1.00,"Coin","Silver","1790s","U","silver_spark","+0.05 if paired with silver coin","First silver dollar minted in U.S.","SD-001","Silver Dollar","1794-1795",["silver","dollar_coin"]))
    cards.append(_c("1795 Draped Bust Silver Dollar",1.00,"Coin","Silver","1790s","U","silver_spark","+0.05 if paired with silver coin","Scot Draped Bust classic dollar.","SD-002","Silver Dollar","1795-1804",["silver","dollar_coin"]))
    cards.append(_c("1840 Liberty Seated Silver Dollar",1.00,"Coin","Silver","1840s","U","silver_spark","+0.05 if paired with silver coin","Resumed after 36-year gap.","SD-003","Silver Dollar","1840-1873",["silver","dollar_coin"]))
    cards.append(_c("1878 Morgan Silver Dollar",1.00,"Coin","Silver","1870s","U","morgan_synergy","+0.10 if 3+ Morgan dollars","Most collected U.S. silver dollar.","SD-004","Silver Dollar","1878-1921",["silver","dollar_coin","morgan"]))
    cards.append(_c("1921 Peace Silver Dollar",1.00,"Coin","Silver","1920s","U","peace_bonus","+0.15 if no event cards active","Commemorating peace after WWI.","SD-005","Silver Dollar","1921-1935",["silver","dollar_coin"]))

    # -- $1 Gold Coins --
    cards.append(_c("1849 Type 1 Gold Dollar",1.00,"Coin","Gold","1840s","U","gold_standard","+0.10 if 2+ gold coins","Tiny gold coin from California Gold Rush.","GD-001","Gold Dollar","1849-1854",["gold","dollar_coin","gold_rush"]))
    cards.append(_c("1854 Type 2 Gold Dollar",1.00,"Coin","Gold","1850s","U","gold_standard","+0.10 if 2+ gold coins","Enlarged Indian Princess design.","GD-002","Gold Dollar","1854-1856",["gold","dollar_coin","gold_rush"]))
    cards.append(_c("1856 Type 3 Gold Dollar",1.00,"Coin","Gold","1850s","U","gold_standard","+0.10 if 2+ gold coins","Final type with longer head.","GD-003","Gold Dollar","1856-1889",["gold","dollar_coin"]))

    # -- $1 Notes --
    cards.append(_c("1862 US Note $1",1.00,"Note","Paper","1860s","U","greenback","+0.05 if 3+ paper notes","First $1 US Note, Greenback origin.","UN-001","$1 Note","1862",["paper","us_note","civil_war"]))
    cards.append(_c("1886 Silver Certificate $1",1.00,"Note","Paper","1880s","U","silver_cert","+0.05 if has silver coin","Martha Washington on reverse.","UN-002","$1 Note","1886",["paper","silver_cert"]))
    cards.append(_c("1896 Educational Silver Cert $1",1.00,"Note","Paper","1890s","U","educational","+0.10 if 5+ cards total","Most beautiful U.S. paper design.","UN-003","$1 Note","1896",["paper","silver_cert"]))
    cards.append(_c("1923 Silver Certificate $1",1.00,"Note","Paper","1920s","U","silver_cert","+0.05 if has silver coin","Last large-size $1 silver cert.","UN-004","$1 Note","1923",["paper","silver_cert"]))
    cards.append(_c("1928 Federal Reserve Note $1",1.00,"Note","Paper","1920s","U","fed_note","+0.05 if 3+ paper notes","First small-size $1 FRN.","UN-005","$1 Note","1928-present",["paper","fed_note"]))
    cards.append(_c("1963 Federal Reserve Note $1",1.00,"Note","Paper","1960s","U","fed_note","+0.05 if 3+ paper notes","Added In God We Trust to $1 bill.","UN-006","$1 Note","1963-present",["paper","fed_note"]))

    # -- $2 Notes --
    cards.append(_c("1862 US Note $2",2.00,"Note","Paper","1860s","U","greenback","+0.10 if 3+ paper notes","Early $2 Legal Tender Note.","UN-007","$2 Note","1862",["paper","us_note","civil_war"]))
    cards.append(_c("1880 Silver Certificate $2",2.00,"Note","Paper","1880s","U","silver_cert","+0.10 if has silver coin","William Windom portrait.","UN-008","$2 Note","1880",["paper","silver_cert"]))
    cards.append(_c("1928 Federal Reserve Note $2",2.00,"Note","Paper","1920s","U","fed_note","+0.10 if 3+ paper notes","Jefferson on face, Monticello back.","UN-009","$2 Note","1928",["paper","fed_note"]))
    cards.append(_c("1976 Federal Reserve Note $2",2.00,"Note","Paper","1970s","U","bicentennial","+0.20 if Bicentennial event","Declaration of Independence on back.","UN-010","$2 Note","1976-present",["paper","fed_note"]))

    # -- $5 Notes --
    cards.append(_c("1861 Demand Note $5",5.00,"Note","Paper","1860s","U","greenback_origin","+0.25 if first note played","The original Greenback, first Demand Note.","UN-011","$5 Note","1861",["paper","demand_note","civil_war"]))
    cards.append(_c("1862 US Note $5",5.00,"Note","Paper","1860s","U","greenback","+0.15 if 3+ paper notes","Legal Tender $5 from Civil War.","UN-012","$5 Note","1862",["paper","us_note","civil_war"]))
    cards.append(_c("1886 Silver Certificate $5",5.00,"Note","Paper","1880s","U","silver_cert","+0.15 if has silver coin","Five Silver Dollars payable on demand.","UN-013","$5 Note","1886",["paper","silver_cert"]))
    cards.append(_c("1905 Gold Certificate $5",5.00,"Note","Paper","1900s","U","gold_cert","+0.15 if has gold coin","Technicolor note, red seal gold tint.","UN-014","$5 Note","1905",["paper","gold_cert"]))
    cards.append(_c("1914 Federal Reserve Note $5",5.00,"Note","Paper","1910s","U","fed_note","+0.15 if 3+ paper notes","First large-size $5 FRN.","UN-015","$5 Note","1914",["paper","fed_note"]))
    cards.append(_c("1928 Federal Reserve Note $5",5.00,"Note","Paper","1920s","U","fed_note","+0.15 if 3+ paper notes","Lincoln on face, Memorial back.","UN-016","$5 Note","1928-present",["paper","fed_note"]))
    cards.append(_c("1953 Silver Certificate $5",5.00,"Note","Paper","1950s","U","silver_cert","+0.15 if has silver coin","Blue seal silver certificate $5.","UN-017","$5 Note","1953",["paper","silver_cert"]))
    cards.append(_c("2004 Federal Reserve Note $5",5.00,"Note","Paper","2000s","U","fed_note","+0.15 if 3+ paper notes","Added purple 3D security ribbon.","UN-018","$5 Note","2004-present",["paper","fed_note"]))

    # -- $10 Notes --
    cards.append(_c("1861 Demand Note $10",10.00,"Note","Paper","1860s","U","greenback_origin","+0.50 if first note played","$10 Demand Note, early Greenback.","UN-019","$10 Note","1861",["paper","demand_note","civil_war"]))
    cards.append(_c("1862 US Note $10",10.00,"Note","Paper","1860s","U","greenback","+0.25 if 3+ paper notes","Legal Tender $10 Civil War era.","UN-020","$10 Note","1862",["paper","us_note","civil_war"]))
    cards.append(_c("1880 Silver Certificate $10",10.00,"Note","Paper","1880s","U","silver_cert","+0.25 if has silver coin","Robert Morris portrait.","UN-021","$10 Note","1880",["paper","silver_cert"]))
    cards.append(_c("1907 Gold Certificate $10",10.00,"Note","Paper","1900s","U","gold_cert","+0.25 if has gold coin","Michael Hillegas, first Treasurer.","UN-022","$10 Note","1907",["paper","gold_cert"]))
    cards.append(_c("1914 Federal Reserve Note $10",10.00,"Note","Paper","1910s","U","fed_note","+0.25 if 3+ paper notes","First large-size $10 FRN.","UN-023","$10 Note","1914",["paper","fed_note"]))
    cards.append(_c("1929 Federal Reserve Note $10",10.00,"Note","Paper","1920s","U","fed_note","+0.25 if 3+ paper notes","First small-size $10 FRN.","UN-024","$10 Note","1929-present",["paper","fed_note"]))
    cards.append(_c("1990 Federal Reserve Note $10",10.00,"Note","Paper","1990s","U","fed_note","+0.25 if 3+ paper notes","Added microprinting security feature.","UN-025","$10 Note","1990-present",["paper","fed_note"]))
    cards.append(_c("2006 Federal Reserve Note $10",10.00,"Note","Paper","2000s","U","fed_note","+0.25 if 3+ paper notes","Redesigned with orange color shift.","UN-026","$10 Note","2006-present",["paper","fed_note"]))

    # -- $2.50 Quarter Eagle (Uncommon) --
    cards.append(_c("1796 Quarter Eagle",2.50,"Coin","Gold","1790s","U","gold_standard","+0.10 if 2+ gold coins","First quarter eagle, no stars on obverse.","QE-001","Quarter Eagle","1796-1807",["gold","quarter_eagle"]))
    cards.append(_c("1834 Classic Head Quarter Eagle",2.50,"Coin","Gold","1830s","U","gold_standard","+0.10 if 2+ gold coins","Reduced gold content, new design.","QE-002","Quarter Eagle","1834-1839",["gold","quarter_eagle"]))
    cards.append(_c("1840 Liberty Head Quarter Eagle",2.50,"Coin","Gold","1840s","U","gold_standard","+0.10 if 2+ gold coins","Long-running Liberty Head type.","QE-003","Quarter Eagle","1840-1907",["gold","quarter_eagle"]))
    cards.append(_c("1908 Indian Head Quarter Eagle",2.50,"Coin","Gold","1900s","U","gold_standard","+0.10 if 2+ gold coins","Incuse design by Bela Lyon Pratt.","QE-004","Quarter Eagle","1908-1929",["gold","quarter_eagle"]))

    # -- $3 Gold Coin --
    cards.append(_c("1854 Three Dollar Gold Piece",3.00,"Coin","Gold","1850s","U","gold_standard","+0.15 if 2+ gold coins","Created for purchasing silver dollars.","TG-001","Three Dollar","1854-1889",["gold","three_dollar"]))

    # -- $5 Half Eagle (Uncommon) --
    cards.append(_c("1795 Half Eagle",5.00,"Coin","Gold","1790s","U","gold_standard","+0.15 if 2+ gold coins","First gold coin minted by the U.S.","HE-001","Half Eagle","1795-1807",["gold","half_eagle"]))
    cards.append(_c("1834 Classic Head Half Eagle",5.00,"Coin","Gold","1830s","U","gold_standard","+0.15 if 2+ gold coins","Reduced weight, new classic design.","HE-002","Half Eagle","1834-1838",["gold","half_eagle"]))
    cards.append(_c("1839 Liberty Head Half Eagle",5.00,"Coin","Gold","1830s","U","gold_standard","+0.15 if 2+ gold coins","Longest produced U.S. gold coin design.","HE-003","Half Eagle","1839-1908",["gold","half_eagle"]))
    cards.append(_c("1908 Indian Head Half Eagle",5.00,"Coin","Gold","1900s","U","gold_standard","+0.15 if 2+ gold coins","Incuse design, Pratt sculptor.","HE-004","Half Eagle","1908-1929",["gold","half_eagle"]))

    # -- National Bank Notes (Uncommon) --
    cards.append(_c("1865 National Bank Note $5",5.00,"Note","Paper","1860s","U","national_bank","+0.20 if has another National Bank Note","Issued by chartered national banks.","NB-001","National Bank Note","1865-1935",["paper","national_bank","civil_war"]))
    cards.append(_c("1902 National Bank Note $10",10.00,"Note","Paper","1900s","U","national_bank","+0.20 if has another National Bank Note","Blue seal, individual bank names.","NB-002","National Bank Note","1902-1929",["paper","national_bank"]))
    cards.append(_c("1929 National Bank Note $20",20.00,"Note","Paper","1920s","U","national_bank","+0.20 if has another National Bank Note","Small-size national bank note.","NB-003","National Bank Note","1929-1935",["paper","national_bank"]))

    # -- $20 Notes --
    cards.append(_c("1861 Demand Note $20",20.00,"Note","Paper","1860s","U","greenback_origin","+0.50 if first note played","Highest denomination Demand Note.","UN-027","$20 Note","1861",["paper","demand_note","civil_war"]))
    cards.append(_c("1862 US Note $20",20.00,"Note","Paper","1860s","U","greenback","+0.30 if 3+ paper notes","Legal Tender $20 Civil War.","UN-028","$20 Note","1862",["paper","us_note","civil_war"]))
    cards.append(_c("1880 Silver Certificate $20",20.00,"Note","Paper","1880s","U","silver_cert","+0.30 if has silver coin","Twenty Silver Dollars payable.","UN-029","$20 Note","1880",["paper","silver_cert"]))
    cards.append(_c("1905 Gold Certificate $20",20.00,"Note","Paper","1900s","U","gold_cert","+0.30 if has gold coin","Washington on gold certificate.","UN-030","$20 Note","1905",["paper","gold_cert"]))
    cards.append(_c("1914 Federal Reserve Note $20",20.00,"Note","Paper","1910s","U","fed_note","+0.30 if 3+ paper notes","First large-size $20 FRN.","UN-031","$20 Note","1914",["paper","fed_note"]))
    cards.append(_c("1929 Federal Reserve Note $20",20.00,"Note","Paper","1920s","U","fed_note","+0.30 if 3+ paper notes","First small-size $20 FRN.","UN-032","$20 Note","1929-present",["paper","fed_note"]))
    cards.append(_c("1990 Federal Reserve Note $20",20.00,"Note","Paper","1990s","U","fed_note","+0.30 if 3+ paper notes","Added security thread.","UN-033","$20 Note","1990-present",["paper","fed_note"]))
    cards.append(_c("2003 Federal Reserve Note $20",20.00,"Note","Paper","2000s","U","fed_note","+0.30 if 3+ paper notes","Color-shifting ink, peach background.","UN-034","$20 Note","2003-present",["paper","fed_note"]))

    # === RARES (R) - Gold coins $10-$20, silver dollars, $50-$100 notes ===

    # -- $10 Eagle --
    cards.append(_c("1795 Eagle",10.00,"Coin","Gold","1790s","R","gold_standard","+0.50 if 2+ gold coins","First ten dollar gold coin.","EA-001","Eagle","1795-1804",["gold","eagle","colonial_era"]))
    cards.append(_c("1838 Liberty Head Eagle",10.00,"Coin","Gold","1830s","R","gold_standard","+0.50 if 2+ gold coins","Christian Gobrecht design.","EA-002","Eagle","1838-1907",["gold","eagle"]))
    cards.append(_c("1907 Indian Head Eagle",10.00,"Coin","Gold","1900s","R","gold_standard","+0.50 if 2+ gold coins","Saint-Gaudens masterpiece, no motto.","EA-003","Eagle","1907-1933",["gold","eagle"]))

    # -- $20 Double Eagle --
    cards.append(_c("1849 Liberty Head Double Eagle",20.00,"Coin","Gold","1840s","R","gold_standard","+1.00 if 2+ gold coins","First double eagle, Gold Rush era.","DE-001","Double Eagle","1849-1907",["gold","double_eagle","gold_rush"]))
    cards.append(_c("1907 Saint-Gaudens Double Eagle",20.00,"Coin","Gold","1900s","R","gold_standard","+1.00 if 2+ gold coins","Considered the most beautiful U.S. coin.","DE-002","Double Eagle","1907-1933",["gold","double_eagle"]))
    cards.append(_c("1933 Saint-Gaudens Double Eagle",20.00,"Coin","Gold","1930s","R","gold_standard","+1.00 if 2+ gold coins","Most valuable coin, only 1 legal to own.","DE-003","Double Eagle","1933",["gold","double_eagle"]))

    # -- $50 Notes --
    cards.append(_c("1861 Demand Note $50",50.00,"Note","Paper","1860s","R","greenback_origin","+1.00 if first note played","Rare high-denomination Demand Note.","UN-035","$50 Note","1861",["paper","demand_note","civil_war"]))
    cards.append(_c("1862 US Note $50",50.00,"Note","Paper","1860s","R","greenback","+0.75 if 3+ paper notes","Legal Tender $50 Civil War.","UN-036","$50 Note","1862",["paper","us_note","civil_war"]))
    cards.append(_c("1880 Silver Certificate $50",50.00,"Note","Paper","1880s","R","silver_cert","+0.75 if has silver coin","Fifty Silver Dollars payable.","UN-037","$50 Note","1880",["paper","silver_cert"]))
    cards.append(_c("1914 Federal Reserve Note $50",50.00,"Note","Paper","1910s","R","fed_note","+0.75 if 3+ paper notes","First large-size $50 FRN.","UN-038","$50 Note","1914",["paper","fed_note"]))
    cards.append(_c("1929 Federal Reserve Note $50",50.00,"Note","Paper","1920s","R","fed_note","+0.75 if 3+ paper notes","First small-size $50 FRN, Grant.","UN-039","$50 Note","1929-present",["paper","fed_note"]))
    cards.append(_c("1996 Federal Reserve Note $50",50.00,"Note","Paper","1990s","R","fed_note","+0.75 if 3+ paper notes","Redesigned with security features.","UN-040","$50 Note","1996-present",["paper","fed_note"]))

    # -- $100 Notes --
    cards.append(_c("1862 US Note $100",100.00,"Note","Paper","1860s","R","greenback","+1.50 if 3+ paper notes","Legal Tender $100 Civil War.","UN-041","$100 Note","1862",["paper","us_note","civil_war"]))
    cards.append(_c("1880 Silver Certificate $100",100.00,"Note","Paper","1880s","R","silver_cert","+1.50 if has silver coin","One hundred Silver Dollars payable.","UN-042","$100 Note","1880",["paper","silver_cert"]))
    cards.append(_c("1907 Gold Certificate $100",100.00,"Note","Paper","1900s","R","gold_cert","+1.50 if has gold coin","Thomas Benton portrait.","UN-043","$100 Note","1907",["paper","gold_cert"]))
    cards.append(_c("1914 Federal Reserve Note $100",100.00,"Note","Paper","1910s","R","fed_note","+1.50 if 3+ paper notes","First large-size $100 FRN.","UN-044","$100 Note","1914",["paper","fed_note"]))
    cards.append(_c("1929 Federal Reserve Note $100",100.00,"Note","Paper","1920s","R","fed_note","+1.50 if 3+ paper notes","First small-size $100, Franklin.","UN-045","$100 Note","1929-present",["paper","fed_note"]))
    cards.append(_c("1996 Federal Reserve Note $100",100.00,"Note","Paper","1990s","R","fed_note","+1.50 if 3+ paper notes","Redesigned with larger portrait.","UN-046","$100 Note","1996-present",["paper","fed_note"]))
    cards.append(_c("2013 Federal Reserve Note $100",100.00,"Note","Paper","2010s","R","fed_note","+1.50 if 3+ paper notes","3D security ribbon, blue bell.","UN-047","$100 Note","2013-present",["paper","fed_note"]))

    # -- $4 Stella (Rare) --
    cards.append(_c("1879 Stella $4 Pattern",4.00,"Coin","Gold","1870s","R","stellaria","+0.50 if has another gold coin","Proposed for international trade, never adopted.","ST-001","Stella","1879-1880",["gold","stella"]))

    # -- Commemorative Coins (Rare) --
    cards.append(_c("1892 Columbian Exposition Half Dollar",0.50,"Coin","Silver","1890s","R","commemorative","+0.25 if has another commemorative","First U.S. commemorative coin.","CM-001","Commemorative","1892-1893",["silver","commemorative"]))
    cards.append(_c("1915 Panama-Pacific Octagonal $50",50.00,"Coin","Gold","1910s","R","commemorative","+1.00 if has another commemorative","Octagonal commemorative gold coin.","CM-002","Commemorative","1915",["gold","commemorative"]))
    cards.append(_c("1921 Alabama Centennial Half Dollar",0.50,"Coin","Silver","1920s","R","commemorative","+0.25 if has another commemorative","Early state commemorative.","CM-003","Commemorative","1921",["silver","commemorative"]))
    cards.append(_c("1984 Olympic Silver Dollar",1.00,"Coin","Silver","1980s","R","commemorative","+0.25 if has another commemorative","Los Angeles Olympics commemorative.","CM-004","Commemorative","1984",["silver","commemorative"]))

    # -- Bullion Coins (Rare) --
    cards.append(_c("1986 American Silver Eagle",1.00,"Coin","Silver","1980s","R","silver_spark","+0.05 if paired with silver coin","Official silver bullion coin.","BL-001","Bullion","1986-present",["silver","bullion"]))
    cards.append(_c("1986 American Gold Eagle",50.00,"Coin","Gold","1980s","R","gold_standard","+1.00 if 2+ gold coins","Official gold bullion coin.","BL-002","Bullion","1986-present",["gold","bullion"]))
    cards.append(_c("1997 American Platinum Eagle",100.00,"Coin","Platinum","1990s","R","platinum_power","+2.00 if has gold coin","First U.S. platinum bullion coin.","BL-003","Bullion","1997-present",["platinum","bullion"]))
    cards.append(_c("2006 American Buffalo Gold",50.00,"Coin","Gold","2000s","R","gold_standard","+1.00 if 2+ gold coins","24-karat gold, Fraser buffalo design.","BL-004","Bullion","2006-present",["gold","bullion"]))

    # -- Federal Reserve Bank Notes (Rare) --
    cards.append(_c("1915 Federal Reserve Bank Note $5",5.00,"Note","Paper","1910s","R","fed_bank_note","+0.30 if has another FRBN","Issued by individual Federal Reserve Banks.","FB-001","FR Bank Note","1915-1935",["paper","fed_bank_note"]))
    cards.append(_c("1929 Federal Reserve Bank Note $100",100.00,"Note","Paper","1920s","R","fed_bank_note","+1.00 if has another FRBN","Small-size FRBN, brown seal.","FB-002","FR Bank Note","1929-1935",["paper","fed_bank_note"]))

    # === ULTRA-RARES (UR) - $500-$1000 notes, key errors ===

    # -- $500 Notes --
    cards.append(_c("1928 Federal Reserve Note $500",500.00,"Note","Paper","1920s","UR","high_denom","+5.00 if has 3+ paper notes","Discontinued high denomination, McKinley.","HD-001","$500 Note","1928-1934",["paper","fed_note","high_denom"]))
    cards.append(_c("1928 Gold Certificate $500",500.00,"Note","Paper","1920s","UR","gold_cert_high","+5.00 if has gold coin","Gold certificate $500, Star portrait.","HD-002","$500 Note","1928",["paper","gold_cert","high_denom"]))

    # -- $1000 Notes --
    cards.append(_c("1928 Federal Reserve Note $1000",1000.00,"Note","Paper","1920s","UR","high_denom","+10.00 if has 3+ paper notes","Cleveland on $1000 FRN.","HD-003","$1000 Note","1928-1934",["paper","fed_note","high_denom"]))
    cards.append(_c("1928 Gold Certificate $1000",1000.00,"Note","Paper","1920s","UR","gold_cert_high","+10.00 if has gold coin","Gold certificate $1000, Cleveland.","HD-004","$1000 Note","1928",["paper","gold_cert","high_denom"]))

    # -- Key Error Coins --
    cards.append(_c("1955 Doubled Die Lincoln Cent",0.01,"Coin","Bronze","1950s","UR","error_double","x2 value if has 3+ copper coins","Famous doubled die error variety.","ER-001","Error Cent","1955",["copper","small_cent","lincoln","error"]))
    cards.append(_c("1937-D 3-Legged Buffalo Nickel",0.05,"Coin","Copper-Nickel","1930s","UR","error_missing","x2 value if has 3+ copper coins","Missing foreleg die error.","ER-002","Error Nickel","1937",["copper","nickel","error"]))
    cards.append(_c("1942/41 Mercury Dime Overdate",0.10,"Coin","Silver","1940s","UR","error_overdate","x2 value if has 3+ silver coins","Overdate error, 1942 over 1941.","ER-003","Error Dime","1942",["silver","dime","error"]))
    cards.append(_c("1922 Plain Lincoln Cent",0.01,"Coin","Bronze","1920s","UR","error_missing","x2 value if has 3+ copper coins","No mintmark due to grease-filled die.","ER-004","Error Cent","1922",["copper","small_cent","lincoln","error"]))

    # -- $50 Gold Slug --
    cards.append(_c("1851 $50 Gold Slug",50.00,"Coin","Gold","1850s","UR","gold_standard","+2.00 if 2+ gold coins","California private issue, massive gold piece.","GS-001","Gold Slug","1851",["gold","gold_rush"]))

    # -- Star Notes --
    cards.append(_c("1934 Silver Certificate Star $1",1.00,"Note","Paper","1930s","UR","star_note","+0.50 if has another star note","Replacement note with star prefix.","SN-001","Star Note","1934",["paper","silver_cert","star"]))
    cards.append(_c("1953 Silver Certificate Star $5",5.00,"Note","Paper","1950s","UR","star_note","+0.50 if has another star note","Replacement $5 silver certificate.","SN-002","Star Note","1953",["paper","silver_cert","star"]))

    # === LEGENDARIES (L) - $5000+, ultra-historic ===

    # -- $5000 Note --
    cards.append(_c("1928 Federal Reserve Note $5000",5000.00,"Note","Paper","1920s","L","fort_knox","x1.5 purse value once per game (requires 3+ coins)","Madison on $5000 FRN, discontinued.","HD-005","$5000 Note","1928-1934",["paper","fed_note","high_denom"]))

    # -- $10000 Note --
    cards.append(_c("1928 Federal Reserve Note $10000",10000.00,"Note","Paper","1920s","L","fort_knox","x1.5 purse value once per game (requires 3+ coins)","Chase on $10000, highest circulating note.","HD-006","$10000 Note","1928-1934",["paper","fed_note","high_denom"]))

    # -- $100000 Gold Certificate --
    cards.append(_c("1934 Gold Certificate $100000",100000.00,"Note","Paper","1930s","L","fort_knox_reserve","x1.5 purse value once per game (requires 5+ cards)","Largest denomination ever printed, bank-only.","HD-007","$100000 Note","1934",["paper","gold_cert","high_denom"]))

    # -- 1913 Liberty Head Nickel --
    cards.append(_c("1913 Liberty Head Nickel",0.05,"Coin","Copper-Nickel","1910s","L","phantom_nickel","x10 value if has 5+ coins (once per game)","Only 5 known, legendary rarity.","NK-006","Liberty Nickel","1913",["copper","nickel","legendary"]))

    # -- 1804 Silver Dollar --
    cards.append(_c("1804 Silver Dollar (Class I)",1.00,"Coin","Silver","1800s","L","king_of_coins","x20 value if has 5+ coins (once per game)","King of American Coins, 15 known.","SD-006","Silver Dollar","1804",["silver","dollar_coin","legendary"]))

    # -- 1793 Chain Cent --
    cards.append(_c("1793 Chain Cent",0.01,"Coin","Copper","1790s","L","first_strike","x15 value if has 5+ coins (once per game)","First cent produced, controversial chain reverse.","LC-006","Large Cent","1793",["copper","large_cent","colonial_era","legendary"]))

    # -- Brasher Doubloon --
    cards.append(_c("1787 Brasher Doubloon",16.00,"Coin","Gold","1780s","L","colonial_gold","x10 value if has 3+ colonial cards","Pre-federal gold coin, Ephraim Brasher.","BD-001","Colonial Gold","1787",["gold","colonial","colonial_era","legendary"]))

    # -- 1822 Half Eagle --
    cards.append(_c("1822 Capped Bust Half Eagle",5.00,"Coin","Gold","1820s","L","rarest_eagle","x15 value if has 5+ cards (once per game)","Only 3 known, rarest U.S. gold coin.","HE-005","Half Eagle","1822",["gold","half_eagle","legendary"]))

    # -- 1870-S Liberty Seated Dollar --
    cards.append(_c("1870-S Liberty Seated Dollar",1.00,"Coin","Silver","1870s","L","phantom_dollar","x20 value if has 5+ cards (once per game)","Only ~12 known, great rarity.","SD-007","Silver Dollar","1870",["silver","dollar_coin","legendary"]))

    # -- 1792 Silver Center Cent --
    cards.append(_c("1792 Silver Center Cent",0.01,"Coin","Copper-Silver","1790s","L","pattern_origin","x15 value if has 5+ cards (once per game)","Pattern coin, silver plug center, pre-Mint.","SC-010","Pattern Cent","1792",["copper","silver","colonial_era","legendary"]))

    # === SECRET RARES (SR) - Special variants ===

    cards.append(_c("1943 Bronze Lincoln Cent",0.01,"Coin","Bronze","1940s","SR","secret_error","x30 value if has 5+ cards (once per game)","Accidentally struck in bronze, ~20 known.","SC-011","Secret Cent","1943",["copper","small_cent","lincoln","wwii","secret"]))
    cards.append(_c("1913/2 Buffalo Nickel Overdate",0.05,"Coin","Copper-Nickel","1910s","SR","secret_overdate","x20 value if has 5+ cards (once per game)","Overdate variety, rare and sought after.","NK-007","Secret Nickel","1913",["copper","nickel","secret"]))
    cards.append(_c("1909-S VDB Matte Proof Lincoln",0.01,"Coin","Bronze","1900s","SR","secret_proof","x25 value if has 5+ cards (once per game)","Matte proof finish, extremely rare.","SC-012","Secret Proof","1909",["copper","small_cent","lincoln","secret"]))
    cards.append(_c("1921 High Relief Peace Dollar Proof",1.00,"Coin","Silver","1920s","SR","secret_proof","x25 value if has 5+ cards (once per game)","High relief proof, first year only.","SD-008","Secret Dollar","1921",["silver","dollar_coin","secret"]))
    cards.append(_c("1885 Trade Dollar Proof",1.00,"Coin","Silver","1880s","SR","secret_proof","x25 value if has 5+ cards (once per game)","Proof-only issue, 5 known.","TD-001","Secret Trade","1885",["silver","dollar_coin","secret"]))

    # === EVENT CARDS ===

    cards.append(_c("Panic of 1837",0.00,"Event","Event","1830s","U","event_panic","Halves all paper note values for 2 rounds","Financial panic, banks collapsed.","EV-001","Event","1837",["event"]))
    cards.append(_c("Inflation Event 1970s",0.00,"Event","Event","1970s","U","event_inflation","Halves all note values for 1 round","Stagflation era, dollar devaluation.","EV-002","Event","1970s",["event"]))
    cards.append(_c("Gold Standard Act 1900",0.00,"Event","Event","1900s","R","event_gold_standard","x1.5 all gold coin values for 2 rounds","Pegged dollar to gold at $20.67/oz.","EV-003","Event","1900",["event","gold"]))
    cards.append(_c("Bretton Woods 1944",0.00,"Event","Event","1940s","R","event_bretton_woods","x1.3 gold values, x0.8 note values for 2 rounds","International gold exchange standard.","EV-004","Event","1944",["event","gold"]))
    cards.append(_c("Nixon Shock 1971",0.00,"Event","Event","1970s","R","event_nixon_shock","Removes gold bonuses, x1.2 note values for 2 rounds","Ended gold convertibility of the dollar.","EV-005","Event","1971",["event"]))
    cards.append(_c("California Gold Rush 1849",0.00,"Event","Event","1840s","R","event_gold_rush","x1.5 gold coin values, draw 2 extra cards","Gold discovered at Sutter's Mill.","EV-006","Event","1849",["event","gold"]))
    cards.append(_c("1969 Discontinuation",0.00,"Event","Event","1960s","UR","event_discontinuation","Remove highest note from opponent purse","$500+ notes discontinued from circulation.","EV-007","Event","1969",["event"]))
    cards.append(_c("Bicentennial 1976",0.00,"Event","Event","1970s","U","event_bicentennial","x1.2 all values for 2 rounds","America's 200th birthday celebration.","EV-008","Event","1976",["event"]))
    cards.append(_c("Coinage Act 1792",0.00,"Event","Event","1790s","R","event_coinage_act","x1.3 all coin values for 2 rounds","Established the U.S. Mint and dollar.","EV-009","Event","1792",["event"]))
    cards.append(_c("Civil War Greenback 1862",0.00,"Event","Event","1860s","U","event_greenback","x1.2 paper note values for 2 rounds","First paper money not backed by specie.","EV-010","Event","1862",["event","civil_war"]))
    cards.append(_c("Silver Demonetization 1965",0.00,"Event","Event","1960s","R","event_silver_demon","x0.7 silver coin values, x1.2 clad for 2 rounds","Removed silver from circulating coins.","EV-011","Event","1965",["event"]))
    cards.append(_c("Panic of 1907",0.00,"Event","Event","1900s","U","event_panic_1907","x0.8 all note values for 1 round","Bank panic led to Federal Reserve creation.","EV-012","Event","1907",["event"]))

    # -- Additional Commons to reach 200+ --
    cards.append(_c("1858 Flying Eagle Cent (Large Letter)",0.01,"Coin","Copper-Nickel","1850s","C","small_change","+0.01 if 5+ cards in purse","Short-lived two-year type, large letter variety.","LC-007","Small Cent","1858",["copper","small_cent","flying_eagle"]))
    cards.append(_c("1864 Two-Cent Piece (Small Motto)",0.02,"Coin","Bronze","1860s","C","first_trust","+0.01 if 3+ copper coins","Rare small motto variety of first 2c coin.","TC-002","Two-Cent","1864",["copper","two_cent","civil_war"]))
    cards.append(_c("1913 Type 1 Buffalo Nickel (Bumpy Bison)",0.05,"Coin","Copper-Nickel","1910s","C","copper_rush","+0.005 per copper (max 0.05)","Early variety with bumpy reverse bison.","NK-008","Nickel","1913",["copper","nickel","buffalo"]))
    cards.append(_c("1942-P Jefferson Nickel (Silver War)",0.05,"Coin","Silver-Manganese","1940s","C","wartime","+0.02 if has WWII card","Wartime silver composition, 35% silver.","NK-009","Nickel","1942-1945",["silver","nickel","wartime","wwii"]))
    cards.append(_c("1916-D Mercury Dime (Key Date)",0.10,"Coin","Silver","1910s","C","silver_spark","+0.02 if paired with silver coin","Key date Mercury dime, low mintage.","DM-011","Dime","1916",["silver","dime","mercury"]))
    cards.append(_c("1932-D Washington Quarter (Key Date)",0.25,"Coin","Silver","1930s","C","silver_spark","+0.02 if paired with silver coin","Key date Washington quarter, low mintage.","WQ-011","Quarter","1932",["silver","quarter","washington"]))
    cards.append(_c("1916 Standing Liberty Quarter (Type 1)",0.25,"Coin","Silver","1910s","C","silver_spark","+0.02 if paired with silver coin","First year, exposed breast design controversial.","WQ-012","Quarter","1916-1917",["silver","quarter","standing_liberty"]))
    cards.append(_c("1921-D Walking Liberty Half (Key Date)",0.50,"Coin","Silver","1920s","C","silver_spark","+0.02 if paired with silver coin","Key date Walking Liberty half dollar.","WL-009","Half Dollar","1921",["silver","half_dollar","walking_liberty"]))
    cards.append(_c("1938-D Walking Liberty Half (Key Date)",0.50,"Coin","Silver","1930s","C","silver_spark","+0.02 if paired with silver coin","Low mintage key date half dollar.","WL-010","Half Dollar","1938",["silver","half_dollar","walking_liberty"]))
    cards.append(_c("2000 Sacagawea Dollar (Cheerios)",1.00,"Coin","Manganese-Brass","2000s","C","copper_rush","+0.005 per copper (max 0.05)","Cheerios promotional dollar, enhanced surface.","MD-011","Modern Dollar","2000",["copper","dollar_coin","sacagawea"]))
    cards.append(_c("2007 Presidential Dollar (Washington)",1.00,"Coin","Manganese-Brass","2000s","C","copper_rush","+0.005 per copper (max 0.05)","First Presidential dollar, edge lettering.","PD-001","Presidential Dollar","2007",["copper","dollar_coin","presidential"]))
    cards.append(_c("2009 Presidential Dollar (Lincoln)",1.00,"Coin","Manganese-Brass","2000s","C","copper_rush","+0.005 per copper (max 0.05)","Lincoln Presidential dollar issue.","PD-002","Presidential Dollar","2009",["copper","dollar_coin","presidential"]))
    cards.append(_c("1869 Rainbow Note $1",1.00,"Note","Paper","1860s","U","rainbow","+0.10 if has 3+ paper notes","Colorful Rainbow series note.","UN-048","$1 Note","1869",["paper","us_note","civil_war"]))
    cards.append(_c("1890 Treasury Note $1 (Windom)",1.00,"Note","Paper","1890s","U","treasury_note","+0.10 if has 3+ paper notes","Treasury Note, Windom portrait.","UN-049","$1 Note","1890",["paper","treasury_note"]))
    cards.append(_c("1976 Federal Reserve Note $2 (Uncut Sheet)",2.00,"Note","Paper","1970s","U","bicentennial","+0.20 if Bicentennial event","Uncut Bicentennial $2 sheet souvenir.","UN-050","$2 Note","1976",["paper","fed_note"]))

    return cards


# =============================================================================
# SECTION 6 - ABILITY RESOLUTION SYSTEM
# =============================================================================

class AbilityResolver:
    """Resolves card abilities during gameplay."""

    @staticmethod
    def resolve_passive(card: Card, purse: Purse) -> Optional[Tuple[str, float]]:
        """Resolve passive abilities that trigger when a card is played.
        Returns (description, bonus_amount) or None."""
        ab = card.ability
        p = purse

        if ab == 'foundation':
            return ("Foundation bonus", 0.01)

        elif ab == 'half_measure':
            if p.count_denomination('Small Cent') > 0 or p.count_denomination('Large Cent') > 0:
                return ("Half-Measure (paired with Cent)", 0.01)

        elif ab == 'copper_rush':
            copper = p.count_composition('Copper') + p.count_composition('Bronze') + \
                     p.count_composition('Copper-Nickel')
            bonus = min(0.005 * copper, 0.05)
            if bonus > 0:
                return (f"Copper Rush ({copper} copper)", bonus)

        elif ab == 'silver_spark':
            silver = p.count_composition('Silver')
            if silver >= 2:
                amt = 0.02 if card.rarity == 'C' else 0.05
                return (f"Silver Spark ({silver} silver)", amt)

        elif ab == 'gold_standard':
            gold = p.count_composition('Gold')
            if gold >= 2:
                amt = 0.10 if card.rarity == 'U' else 0.50
                return (f"Gold Standard ({gold} gold)", amt)

        elif ab == 'first_trust':
            if p.count_composition('Copper') + p.count_composition('Bronze') >= 3:
                return ("In God We Trust (3+ copper)", 0.01)

        elif ab == 'small_change':
            if len(p.cards) >= 5:
                return ("Small Change (5+ cards)", 0.01)

        elif ab == 'wartime':
            if p.has_tag('wwii'):
                return ("Wartime Synergy", 0.02)

        elif ab == 'odd_denomination':
            if p.count_denomination('Twenty-Cent') <= 1:
                return ("Odd Denomination", 0.05)

        elif ab == 'last_of_kind':
            if p.count_denomination(card.denomination) == 1:
                return ("Last of Kind", 0.02)

        elif ab == 'morgan_synergy':
            if p.count_tag('morgan') >= 3:
                return ("Morgan Synergy (3+)", 0.10)

        elif ab == 'peace_bonus':
            if not any(c.card_type == 'Event' for c in p.cards):
                return ("Peace Bonus", 0.15)

        elif ab == 'greenback':
            notes = sum(1 for c in p.cards if c.card_type == 'Note')
            if notes >= 3:
                return ("Greenback (3+ notes)", 0.05 if card.rarity == 'U' else 0.30)

        elif ab == 'greenback_origin':
            if len([c for c in p.cards if c.card_type == 'Note']) == 1:
                return ("Original Greenback", 0.25 if card.value <= 5 else 0.50)

        elif ab == 'silver_cert':
            if p.count_composition('Silver') > 0:
                return ("Silver Certificate backed", 0.05 if card.value <= 2 else 0.30)

        elif ab == 'gold_cert':
            if p.count_composition('Gold') > 0:
                return ("Gold Certificate backed", 0.15 if card.value <= 5 else 0.30)

        elif ab == 'gold_cert_high':
            if p.count_composition('Gold') > 0:
                return ("Gold Certificate (high)", 5.00 if card.value <= 500 else 10.00)

        elif ab == 'fed_note':
            notes = sum(1 for c in p.cards if c.card_type == 'Note')
            if notes >= 3:
                base = 0.05 if card.value <= 1 else (0.15 if card.value <= 5 else (0.25 if card.value <= 10 else 0.30))
                return ("Federal Reserve Note (3+ notes)", base)

        elif ab == 'educational':
            if len(p.cards) >= 5:
                return ("Educational Series", 0.10)

        elif ab == 'bicentennial':
            return ("Bicentennial Spirit", 0.20)

        elif ab == 'fractional':
            notes = sum(1 for c in p.cards if c.card_type == 'Note')
            bonus = min(0.01 * notes, 0.05)
            if bonus > 0:
                return (f"Fractional Currency ({notes} notes)", bonus)

        elif ab == 'colonial':
            if p.count_tag('colonial') >= 2:
                return ("Colonial Synergy", 0.05)

        elif ab == 'national_bank':
            if p.count_tag('national_bank') >= 2:
                return ("National Bank Network", 0.20)

        elif ab == 'fed_bank_note':
            if p.count_tag('fed_bank_note') >= 2:
                return ("FR Bank Network", 0.30 if card.value >= 50 else 0.15)

        elif ab == 'high_denom':
            notes = sum(1 for c in p.cards if c.card_type == 'Note')
            if notes >= 3:
                return ("High Denomination Bonus", 5.00 if card.value <= 500 else 10.00)

        elif ab == 'commemorative':
            if p.count_tag('commemorative') >= 2:
                return ("Commemorative Set", 0.25 if card.value < 10 else 1.00)

        elif ab == 'stellaria':
            if p.count_composition('Gold') >= 2:
                return ("Stella International", 0.50)

        elif ab == 'platinum_power':
            if p.count_composition('Gold') > 0:
                return ("Platinum Power", 2.00)

        elif ab == 'star_note':
            if p.count_tag('star') >= 2:
                return ("Star Note Pair", 0.50)

        elif ab == 'rainbow':
            notes = sum(1 for c in p.cards if c.card_type == 'Note')
            if notes >= 3:
                return ("Rainbow Series (3+ notes)", 0.10)

        elif ab == 'treasury_note':
            notes = sum(1 for c in p.cards if c.card_type == 'Note')
            if notes >= 3:
                return ("Treasury Note (3+ notes)", 0.10)

        return None

    @staticmethod
    def can_activate(card: Card, player: Player, game: 'ExchangeGame') -> bool:
        """Check if an ability can be activated (for once-per-game abilities)."""
        ab = card.ability
        used = player.abilities_used.get(card.card_id, 0)

        if ab in ('fort_knox', 'fort_knox_reserve', 'phantom_nickel', 'king_of_coins',
                   'first_strike', 'colonial_gold', 'rarest_eagle', 'phantom_dollar',
                   'pattern_origin', 'secret_error', 'secret_overdate', 'secret_proof',
                   'secret_proof_alt'):
            return used == 0

        return True

    @staticmethod
    def activate(card: Card, player: Player, opponent: Player,
                 game: 'ExchangeGame') -> Optional[str]:
        """Activate an ability. Returns description string or None."""
        ab = card.ability
        p = player.purse

        # Once-per-game Legendary/Secret abilities
        if ab == 'fort_knox':
            coins = sum(1 for c in p.cards if c.card_type == 'Coin')
            if coins >= 3:
                p.add_multiplier("Fort Knox Reserve", 1.5)
                player.abilities_used[card.card_id] = 1
                player.immune = True
                return f"Fort Knox Reserve activated! Purse value x1.5! Immune to challenges!"

        elif ab == 'fort_knox_reserve':
            if len(p.cards) >= 5:
                p.add_multiplier("Fort Knox Reserve", 1.5)
                player.abilities_used[card.card_id] = 1
                player.immune = True
                return f"Fort Knox Reserve activated! Purse value x1.5! Immune to challenges!"

        elif ab in ('phantom_nickel', 'king_of_coins', 'first_strike', 'rarest_eagle',
                     'phantom_dollar', 'pattern_origin'):
            if len(p.cards) >= 5:
                mult = {'phantom_nickel': 10, 'king_of_coins': 20, 'first_strike': 15,
                        'rarest_eagle': 15, 'phantom_dollar': 20, 'pattern_origin': 15}[ab]
                p.add_card_multiplier(card.card_id, f"{card.name} legendary power", mult)
                player.abilities_used[card.card_id] = 1
                return f"{card.name} legendary power! Card value x{mult}!"

        elif ab == 'colonial_gold':
            if player.purse.count_tag('colonial') >= 3:
                p.add_card_multiplier(card.card_id, "Colonial Gold", 10)
                player.abilities_used[card.card_id] = 1
                return "Colonial Gold activated! Card value x10!"

        elif ab in ('secret_error', 'secret_overdate', 'secret_proof'):
            if len(p.cards) >= 5:
                mult = {'secret_error': 30, 'secret_overdate': 20, 'secret_proof': 25}[ab]
                p.add_card_multiplier(card.card_id, f"Secret Rare: {card.name}", mult)
                player.abilities_used[card.card_id] = 1
                return f"Secret Rare activated! {card.name} value x{mult}!"

        # Error coin passive multipliers (auto-activate when conditions met)
        elif ab == 'error_double':
            if p.count_composition('Copper') + p.count_composition('Bronze') >= 3:
                p.add_card_multiplier(card.card_id, "Doubled Die Error", 2)
                player.abilities_used[card.card_id] = 1
                return "Doubled Die Error! Card value x2!"

        elif ab == 'error_missing':
            if p.count_composition('Copper') + p.count_composition('Bronze') >= 3:
                p.add_card_multiplier(card.card_id, "Missing Element Error", 2)
                player.abilities_used[card.card_id] = 1
                return "Missing Element Error! Card value x2!"

        elif ab == 'error_overdate':
            if p.count_composition('Silver') >= 3:
                p.add_card_multiplier(card.card_id, "Overdate Error", 2)
                player.abilities_used[card.card_id] = 1
                return "Overdate Error! Card value x2!"

        return None

    @staticmethod
    def activate_event(card: Card, player: Player, opponent: Player,
                       game: 'ExchangeGame') -> Optional[str]:
        """Activate an event card. Returns description string."""
        ab = card.ability

        if ab == 'event_panic':
            game.add_event_modifier('note_value_mult', 0.5, 2)
            return "Panic of 1837! All paper note values halved for 2 rounds!"

        elif ab == 'event_inflation':
            game.add_event_modifier('note_value_mult', 0.5, 1)
            return "Inflation! All note values halved for 1 round!"

        elif ab == 'event_gold_standard':
            game.add_event_modifier('gold_value_mult', 1.5, 2)
            return "Gold Standard Act! Gold coin values x1.5 for 2 rounds!"

        elif ab == 'event_bretton_woods':
            game.add_event_modifier('gold_value_mult', 1.3, 2)
            game.add_event_modifier('note_value_mult', 0.8, 2)
            return "Bretton Woods! Gold x1.3, notes x0.8 for 2 rounds!"

        elif ab == 'event_nixon_shock':
            game.add_event_modifier('gold_value_mult', 0.0, 2)  # removes gold bonuses
            game.add_event_modifier('note_value_mult', 1.2, 2)
            return "Nixon Shock! Gold bonuses removed, notes x1.2 for 2 rounds!"

        elif ab == 'event_gold_rush':
            game.add_event_modifier('gold_value_mult', 1.5, 2)
            player.draw(2)
            return "California Gold Rush! Gold x1.5, drew 2 extra cards!"

        elif ab == 'event_discontinuation':
            if not opponent.immune:
                notes = [c for c in opponent.purse.cards if c.card_type == 'Note']
                if notes:
                    highest = max(notes, key=lambda c: c.value)
                    opponent.purse.remove(highest)
                    opponent.deck.add_to_discard([highest])
                    return f"1969 Discontinuation! Removed {highest.name} from opponent!"
                return "1969 Discontinuation! Opponent had no notes to remove."
            return "1969 Discontinuation! Opponent was immune!"

        elif ab == 'event_bicentennial':
            game.add_event_modifier('all_value_mult', 1.2, 2)
            return "Bicentennial! All values x1.2 for 2 rounds!"

        elif ab == 'event_coinage_act':
            game.add_event_modifier('coin_value_mult', 1.3, 2)
            return "Coinage Act of 1792! All coin values x1.3 for 2 rounds!"

        elif ab == 'event_greenback':
            game.add_event_modifier('note_value_mult', 1.2, 2)
            return "Civil War Greenback! Paper note values x1.2 for 2 rounds!"

        elif ab == 'event_silver_demon':
            game.add_event_modifier('silver_value_mult', 0.7, 2)
            game.add_event_modifier('clad_value_mult', 1.2, 2)
            return "Silver Demonetization! Silver x0.7, clad x1.2 for 2 rounds!"

        elif ab == 'event_panic_1907':
            game.add_event_modifier('note_value_mult', 0.8, 1)
            opponent.skipped_next = True
            return "Panic of 1907! Note values x0.8 for 1 round! Opponent skips next turn!"

        return None


# =============================================================================
# SECTION 7 - BOOSTER PACK GENERATOR
# =============================================================================

class BoosterPack:
    """Generates booster packs respecting rarity ratios."""

    def __init__(self, card_pool: List[Card]):
        self.pool_by_rarity: Dict[str, List[Card]] = {'C': [], 'U': [], 'R': [], 'UR': [], 'L': [], 'SR': []}
        for card in card_pool:
            if card.rarity in self.pool_by_rarity:
                self.pool_by_rarity[card.rarity].append(card)

    def generate_pack(self, pack_size: int = 12) -> List[Card]:
        """Generate a single booster pack.
        Distribution: 7-8 C, 2-3 U, 1 R, 0-1 UR, L/SR ~1:100 packs."""
        pack = []
        # Commons: 7-8
        commons = random.randint(7, 8)
        for _ in range(commons):
            if self.pool_by_rarity['C']:
                pack.append(copy.deepcopy(random.choice(self.pool_by_rarity['C'])))
        # Uncommons: 2-3
        uncommons = 12 - commons - 1  # leave room for 1 rare
        for _ in range(max(2, uncommons)):
            if self.pool_by_rarity['U']:
                pack.append(copy.deepcopy(random.choice(self.pool_by_rarity['U'])))
        # Rare: 1
        if self.pool_by_rarity['R']:
            pack.append(copy.deepcopy(random.choice(self.pool_by_rarity['R'])))
        # Ultra-Rare or better: 0-1 (3.5% + 1% + 0.5% = 5% chance to upgrade)
        roll = random.random()
        if roll < 0.005:  # Secret Rare 0.5%
            if self.pool_by_rarity['SR']:
                pack.append(copy.deepcopy(random.choice(self.pool_by_rarity['SR'])))
            elif self.pool_by_rarity['L']:
                pack.append(copy.deepcopy(random.choice(self.pool_by_rarity['L'])))
        elif roll < 0.015:  # Legendary 1%
            if self.pool_by_rarity['L']:
                pack.append(copy.deepcopy(random.choice(self.pool_by_rarity['L'])))
        elif roll < 0.05:  # Ultra-Rare 3.5%
            if self.pool_by_rarity['UR']:
                pack.append(copy.deepcopy(random.choice(self.pool_by_rarity['UR'])))

        return pack

    def generate_box(self, num_packs: int = 24) -> List[List[Card]]:
        """Generate a booster box."""
        return [self.generate_pack() for _ in range(num_packs)]


# =============================================================================
# SECTION 8 - DECK BUILDER & VALIDATION
# =============================================================================

class DeckBuilder:
    """Builds and validates decks."""

    MIN_DECK_SIZE = 40
    MAX_DECK_SIZE = 60
    MIN_COMMONS = 15

    @staticmethod
    def validate_deck(deck: List[Card]) -> Tuple[bool, List[str]]:
        """Validate a deck. Returns (is_valid, list_of_errors)."""
        errors = []
        if len(deck) < DeckBuilder.MIN_DECK_SIZE:
            errors.append(f"Deck too small: {len(deck)} cards (min {DeckBuilder.MIN_DECK_SIZE})")
        if len(deck) > DeckBuilder.MAX_DECK_SIZE:
            errors.append(f"Deck too large: {len(deck)} cards (max {DeckBuilder.MAX_DECK_SIZE})")
        commons = sum(1 for c in deck if c.rarity == 'C')
        if commons < DeckBuilder.MIN_COMMONS:
            errors.append(f"Too few Commons: {commons} (min {DeckBuilder.MIN_COMMONS})")
        events = sum(1 for c in deck if c.card_type == 'Event')
        if events > 5:
            errors.append(f"Too many Event cards: {events} (max 5)")
        return (len(errors) == 0, errors)

    @staticmethod
    def auto_build_deck(card_pool: List[Card], target_size: int = 45) -> List[Card]:
        """Auto-generate a valid deck from the card pool."""
        pool_by_rarity: Dict[str, List[Card]] = {'C': [], 'U': [], 'R': [], 'UR': [], 'L': [], 'SR': []}
        for card in card_pool:
            if card.rarity in pool_by_rarity:
                pool_by_rarity[card.rarity].append(card)

        deck = []
        # Ensure minimum commons
        commons_needed = max(DeckBuilder.MIN_COMMONS, int(target_size * 0.45))
        for _ in range(commons_needed):
            if pool_by_rarity['C']:
                deck.append(copy.deepcopy(random.choice(pool_by_rarity['C'])))

        # Fill with uncommons
        uncommons_needed = int(target_size * 0.30)
        for _ in range(uncommons_needed):
            if pool_by_rarity['U']:
                deck.append(copy.deepcopy(random.choice(pool_by_rarity['U'])))

        # Some rares
        rares_needed = int(target_size * 0.15)
        for _ in range(rares_needed):
            if pool_by_rarity['R']:
                deck.append(copy.deepcopy(random.choice(pool_by_rarity['R'])))

        # Few ultra-rares
        ur_needed = int(target_size * 0.05)
        for _ in range(ur_needed):
            if pool_by_rarity['UR']:
                deck.append(copy.deepcopy(random.choice(pool_by_rarity['UR'])))

        # Maybe a legendary
        if random.random() < 0.3 and pool_by_rarity['L']:
            deck.append(copy.deepcopy(random.choice(pool_by_rarity['L'])))

        # Maybe an event or two
        events = [c for c in card_pool if c.card_type == 'Event']
        if events:
            num_events = random.randint(1, 3)
            for _ in range(num_events):
                deck.append(copy.deepcopy(random.choice(events)))

        # Trim or pad to target
        while len(deck) > target_size:
            deck.pop()
        while len(deck) < target_size and pool_by_rarity['C']:
            deck.append(copy.deepcopy(random.choice(pool_by_rarity['C'])))

        random.shuffle(deck)
        return deck

    @staticmethod
    def build_starter_deck(card_pool: List[Card], name: str = "Starter") -> List[Card]:
        """Build a balanced starter deck."""
        pool_by_rarity: Dict[str, List[Card]] = {'C': [], 'U': [], 'R': [], 'UR': [], 'L': [], 'SR': []}
        for card in card_pool:
            if card.rarity in pool_by_rarity:
                pool_by_rarity[card.rarity].append(card)

        deck = []
        # 20 commons
        for _ in range(20):
            if pool_by_rarity['C']:
                deck.append(copy.deepcopy(random.choice(pool_by_rarity['C'])))
        # 12 uncommons
        for _ in range(12):
            if pool_by_rarity['U']:
                deck.append(copy.deepcopy(random.choice(pool_by_rarity['U'])))
        # 8 rares
        for _ in range(8):
            if pool_by_rarity['R']:
                deck.append(copy.deepcopy(random.choice(pool_by_rarity['R'])))
        # 3 ultra-rares
        for _ in range(3):
            if pool_by_rarity['UR']:
                deck.append(copy.deepcopy(random.choice(pool_by_rarity['UR'])))
        # 1 legendary
        if pool_by_rarity['L']:
            deck.append(copy.deepcopy(random.choice(pool_by_rarity['L'])))
        # 2 events
        events = [c for c in card_pool if c.card_type == 'Event']
        for _ in range(2):
            if events:
                deck.append(copy.deepcopy(random.choice(events)))

        random.shuffle(deck)
        return deck


# =============================================================================
# SECTION 9 - GAME ENGINE
# =============================================================================

class ExchangeGame:
    """Main game engine for The Exchange TCG."""

    def __init__(self, players: List[Player], target_value: float = 100.0,
                 max_rounds: int = 30):
        self.players = players
        self.target_value = target_value
        self.max_rounds = max_rounds
        self.current_round = 1
        self.current_player_idx = 0
        self.event_modifiers: Dict[str, List[Tuple[float, int]]] = {}
        self.active_events: List[Tuple[str, int]] = []
        self.game_over = False
        self.winner: Optional[Player] = None
        self.log: List[str] = []
        self.card_pool = create_base_set()
        self.ai_difficulty = 'medium'

    def add_event_modifier(self, mod_type: str, multiplier: float, rounds: int):
        if mod_type not in self.event_modifiers:
            self.event_modifiers[mod_type] = []
        self.event_modifiers[mod_type].append((multiplier, rounds))

    def get_event_multiplier(self, mod_type: str) -> float:
        if mod_type not in self.event_modifiers:
            return 1.0
        total = 1.0
        for mult, rounds in self.event_modifiers[mod_type]:
            if rounds > 0:
                total *= mult
        return total

    def tick_event_modifiers(self):
        for mod_type in self.event_modifiers:
            self.event_modifiers[mod_type] = [(m, r - 1) for m, r in self.event_modifiers[mod_type] if r > 1]
        self.active_events = [(name, r - 1) for name, r in self.active_events if r > 1]

    def compute_purse_value(self, player: Player) -> float:
        purse = player.purse
        val = 0.0
        for card in purse.cards:
            card_val = card.value
            if card.card_type == 'Note':
                card_val *= self.get_event_multiplier('note_value_mult')
            if card.composition == 'Gold':
                card_val *= self.get_event_multiplier('gold_value_mult')
            if card.composition == 'Silver':
                card_val *= self.get_event_multiplier('silver_value_mult')
            if card.card_type == 'Coin':
                card_val *= self.get_event_multiplier('coin_value_mult')
            card_val *= self.get_event_multiplier('all_value_mult')
            if 'Copper-Nickel' in card.composition:
                card_val *= self.get_event_multiplier('clad_value_mult')
            for desc, mult in purse.card_multipliers.get(card.card_id, []):
                card_val *= mult
            val += card_val
        for desc, amount in purse.bonuses:
            val += amount
        for desc, mult in purse.multipliers:
            val *= mult
        return val

    def setup(self):
        for player in self.players:
            player.deck.shuffle()
            commons_in_deck = [c for c in player.deck.cards if c.rarity == 'C']
            # Seed with lowest-value commons for a balanced start
            commons_in_deck.sort(key=lambda c: c.value)
            starter = commons_in_deck[:5]
            for c in starter:
                player.deck.cards.remove(c)
                player.purse.add(c)
            player.draw(5)
        best_idx = 0
        best_val = -1
        for i, p in enumerate(self.players):
            if p.hand:
                max_card = max(p.hand, key=lambda c: c.value)
                if max_card.value > best_val:
                    best_val = max_card.value
                    best_idx = i
        self.current_player_idx = best_idx

    def check_win_conditions(self) -> bool:
        for p in self.players:
            val = self.compute_purse_value(p)
            if val >= self.target_value:
                self.game_over = True
                self.winner = p
                return True
        if self.current_round > self.max_rounds:
            self.game_over = True
            self.winner = max(self.players, key=lambda p: self.compute_purse_value(p))
            return True
        return False

    def play_card(self, player: Player, card: Card) -> str:
        if not player.play_to_purse(card):
            return "Failed to play card."
        msg = f"  {player.name} played {card.short_str()}"
        bonus = AbilityResolver.resolve_passive(card, player.purse)
        if bonus:
            desc, amount = bonus
            player.purse.add_bonus(desc, amount)
            msg += f" | {clr('+' + f'${amount:.2f}', C.GREEN)} {desc}"
        if card.ability in ('error_double', 'error_missing', 'error_overdate'):
            opp = self.players[0] if player != self.players[0] else self.players[-1]
            result = AbilityResolver.activate(card, player, opp, self)
            if result:
                msg += f" | {clr(result, C.MAGENTA)}"
        return msg

    def make_change(self, player: Player, large_card: Card,
                    small_cards: List[Card]) -> str:
        if large_card not in player.purse.cards:
            return "Card not in purse."
        total_small = sum(c.value for c in small_cards)
        if total_small > large_card.value + 0.01:
            return f"Cannot make change: ${total_small:.4f} > ${large_card.value:.4f}"
        player.purse.remove(large_card)
        player.deck.add_to_discard([large_card])
        bonus_msgs = []
        for c in small_cards:
            if c in player.hand:
                player.hand.remove(c)
                player.purse.add(c)
                bonus = AbilityResolver.resolve_passive(c, player.purse)
                if bonus:
                    desc, amount = bonus
                    player.purse.add_bonus(desc, amount)
                    bonus_msgs.append(f"+${amount:.2f} {desc}")
        msg = (f"  {player.name} made change: {large_card.name} -> "
               f"{', '.join(c.name for c in small_cards)}")
        if bonus_msgs:
            msg += f" | {clr(' | '.join(bonus_msgs), C.GREEN)}"
        return msg

    def challenge(self, challenger: Player, opponent: Player) -> str:
        if challenger.challenge_cooldown > 0:
            return f"  {clr('Challenge on cooldown!', C.RED)} Wait {challenger.challenge_cooldown} more turn(s)."
        ch_val = self.compute_purse_value(challenger)
        op_val = self.compute_purse_value(opponent)
        if op_val < 1.0 and len(opponent.purse.cards) == 0:
            return f"  {opponent.name} has nothing to challenge!"
        if ch_val > op_val:
            advantage = (ch_val - op_val) / max(op_val, 0.01)
            if opponent.purse.cards and not opponent.immune:
                # Steal highest value card, or random card if advantage is small
                if advantage > 0.10:
                    stolen = max(opponent.purse.cards, key=lambda c: c.value)
                else:
                    stolen = random.choice(opponent.purse.cards)
                opponent.purse.remove(stolen)
                challenger.purse.add(stolen)
                # Re-resolve passives for stolen card in new purse
                bonus = AbilityResolver.resolve_passive(stolen, challenger.purse)
                if bonus:
                    challenger.purse.add_bonus(bonus[0], bonus[1])
                bonus_amt = 0.0
                if advantage > 0.20:
                    bonus_amt = stolen.value * 0.10
                    challenger.purse.add_bonus("Challenge advantage (+10%)", bonus_amt)
                challenger.challenge_cooldown = 2
                return (f"  {clr('CHALLENGE WON', C.GREEN)} by {challenger.name}! "
                        f"(${ch_val:.2f} vs ${op_val:.2f}) "
                        f"Stole {stolen.name}!" +
                        (f" +${bonus_amt:.2f} advantage bonus!" if bonus_amt > 0 else ""))
            elif opponent.immune:
                return f"  {opponent.name} is immune! Challenge failed."
            else:
                return f"  {opponent.name} has no cards to steal!"
        else:
            challenger.challenge_cooldown = 2
            if challenger.hand:
                lost = max(challenger.hand, key=lambda c: c.value)
                challenger.discard_card(lost)
                return (f"  {clr('CHALLENGE LOST', C.RED)} by {challenger.name}! "
                        f"(${ch_val:.2f} vs ${op_val:.2f}) "
                        f"Discarded {lost.name}.")
            return (f"  {clr('CHALLENGE LOST', C.RED)} by {challenger.name}! "
                    f"(${ch_val:.2f} vs ${op_val:.2f})")

    def activate_ability(self, player: Player, card: Card) -> str:
        if card not in player.purse.cards:
            return "Card not in purse."
        if not AbilityResolver.can_activate(card, player, self):
            return f"{card.name} ability already used this game."
        opponent = self.players[0] if player != self.players[0] else self.players[-1]
        result = AbilityResolver.activate(card, player, opponent, self)
        if result:
            return f"  {clr('ABILITY:', C.YELLOW)} {result}"
        return f"  Cannot activate {card.name} - conditions not met."

    def play_event(self, player: Player, card: Card) -> str:
        if card not in player.hand:
            return "Card not in hand."
        player.hand.remove(card)
        player.deck.add_to_discard([card])
        opponent = self.players[0] if player != self.players[0] else self.players[-1]
        result = AbilityResolver.activate_event(card, player, opponent, self)
        if result:
            self.active_events.append((card.name, 2))
            return f"  {clr('EVENT:', C.CYAN)} {result}"
        return f"  Event {card.name} had no effect."

    def end_turn(self, player: Player):
        while len(player.hand) > player.hand_limit():
            lowest = min(player.hand, key=lambda c: c.value)
            player.discard_card(lowest)

    def next_turn(self):
        self.current_player_idx = (self.current_player_idx + 1) % len(self.players)
        if self.current_player_idx == 0:
            self.current_round += 1
            self.tick_event_modifiers()
            for p in self.players:
                if p.immune:
                    p.immune = False
                if p.challenge_cooldown > 0:
                    p.challenge_cooldown -= 1
        # Check if next player should be skipped
        current = self.players[self.current_player_idx]
        if current.skipped_next:
            current.skipped_next = False
            self.log.append(f"{current.name} was skipped!")
            self.current_player_idx = (self.current_player_idx + 1) % len(self.players)
            if self.current_player_idx == 0:
                self.current_round += 1
                self.tick_event_modifiers()

    # ── AI Logic ─────────────────────────────────────────────────────────────

    def _ai_evaluate_card(self, card: Card, purse: Purse) -> float:
        """Estimate the effective value of playing a card (base + synergy bonus)."""
        val = card.value
        bonus = AbilityResolver.resolve_passive(card, purse)
        if bonus:
            val += bonus[1]
        # Prefer cards that synergize with existing purse
        if card.composition == 'Silver' and purse.count_composition('Silver') >= 1:
            val += 0.05
        if card.composition == 'Gold' and purse.count_composition('Gold') >= 1:
            val += 0.20
        if card.card_type == 'Note' and sum(1 for c in purse.cards if c.card_type == 'Note') >= 2:
            val += 0.15
        if 'morgan' in card.tags and purse.count_tag('morgan') >= 2:
            val += 0.15
        return val

    def _ai_pick_event(self, events: List[Card], player: Player, opponent: Player) -> Optional[Card]:
        """Pick the best event card for the current situation."""
        my_val = self.compute_purse_value(player)
        op_val = self.compute_purse_value(opponent)
        my_notes = sum(1 for c in player.purse.cards if c.card_type == 'Note')
        my_gold = sum(1 for c in player.purse.cards if c.composition == 'Gold')
        my_silver = sum(1 for c in player.purse.cards if c.composition == 'Silver')
        op_notes = sum(1 for c in opponent.purse.cards if c.card_type == 'Note')
        op_high_notes = [c for c in opponent.purse.cards if c.card_type == 'Note' and c.value >= 100]

        scored = []
        for ev in events:
            score = 0
            ab = ev.ability
            if ab == 'event_panic' and op_notes >= 3:
                score = 10 + op_notes
            elif ab == 'event_inflation' and op_notes >= 3:
                score = 8 + op_notes
            elif ab == 'event_gold_standard' and my_gold >= 2:
                score = 15 + my_gold * 2
            elif ab == 'event_bretton_woods' and my_gold >= 2 and op_notes >= 2:
                score = 12 + my_gold
            elif ab == 'event_nixon_shock' and op_val > my_val and my_notes >= 3:
                score = 10 + my_notes
            elif ab == 'event_gold_rush' and my_gold >= 1:
                score = 15 + my_gold * 3
            elif ab == 'event_discontinuation' and op_high_notes:
                score = 20 + len(op_high_notes) * 5
            elif ab == 'event_bicentennial':
                score = 8 + len(player.purse.cards)
            elif ab == 'event_coinage_act' and sum(1 for c in player.purse.cards if c.card_type == 'Coin') >= 3:
                score = 12
            elif ab == 'event_greenback' and my_notes >= 3:
                score = 10 + my_notes
            elif ab == 'event_silver_demon' and my_silver < 2 and op_val > my_val:
                score = 8
            elif ab == 'event_panic_1907' and op_notes >= 2:
                score = 15 + op_notes
            else:
                score = 1  # generic low priority
            scored.append((score, ev))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] > 0:
            return scored[0][1]
        return None

    def _ai_make_change(self, player: Player) -> List[str]:
        """AI decides whether to make change: break a high-value purse card into smaller hand cards."""
        actions = []
        if not player.purse.cards or not player.hand:
            return actions
        # Find purse cards worth breaking (high value, not benefiting from multipliers)
        for large in sorted(player.purse.cards, key=lambda c: c.value, reverse=True):
            if large.value < 5.0:
                continue
            # Find hand cards whose total is close to but not exceeding large card value
            small_candidates = sorted([c for c in player.hand if c.value < large.value],
                                      key=lambda c: c.value, reverse=True)
            if not small_candidates:
                continue
            # Greedy: pick cards until we approach the large card's value
            selected = []
            total = 0.0
            for c in small_candidates:
                if total + c.value <= large.value + 0.01:
                    selected.append(c)
                    total += c.value
            if not selected or total < large.value * 0.5:
                continue
            # Only make change if the small cards have synergy potential
            has_synergy = any(AbilityResolver.resolve_passive(c, player.purse) for c in selected)
            if has_synergy or len(selected) >= 3:
                result = self.make_change(player, large, selected)
                actions.append(result)
                break  # One make-change per turn
        return actions

    def ai_take_turn(self, player: Player) -> List[str]:
        actions = []
        opponent = self.players[0] if player != self.players[0] else self.players[-1]
        player.draw(2)
        actions.append(f"  {player.name} drew 2 cards.")
        diff = self.ai_difficulty
        challenged_this_turn = False

        # ── Event play logic ──
        events = [c for c in player.hand if c.card_type == 'Event']
        if events:
            if diff == 'easy':
                if random.random() < 0.3:
                    result = self.play_event(player, random.choice(events))
                    actions.append(result)
            elif diff == 'medium':
                op_val = self.compute_purse_value(opponent)
                my_val = self.compute_purse_value(player)
                if op_val > my_val * 1.3 and random.random() < 0.6:
                    result = self.play_event(player, random.choice(events))
                    actions.append(result)
            else:  # hard
                best_event = self._ai_pick_event(events, player, opponent)
                if best_event:
                    result = self.play_event(player, best_event)
                    actions.append(result)

        # ── Card play logic ──
        non_events = [c for c in player.hand if c.card_type != 'Event']
        if diff == 'easy':
            random.shuffle(non_events)
            cards_to_play = min(len(non_events), random.randint(1, 2))
        elif diff == 'medium':
            non_events.sort(key=lambda c: c.value, reverse=True)
            cards_to_play = min(len(non_events), random.randint(2, 3))
        else:  # hard
            non_events.sort(key=lambda c: self._ai_evaluate_card(c, player.purse), reverse=True)
            cards_to_play = min(len(non_events), 3)
        for i in range(cards_to_play):
            if i < len(non_events):
                result = self.play_card(player, non_events[i])
                actions.append(result)

        # ── Make change (hard AI only) ──
        if diff == 'hard':
            change_actions = self._ai_make_change(player)
            actions.extend(change_actions)

        # ── Ability activation (activate all available, not just first) ──
        for card in player.purse.cards:
            if card.ability in ('fort_knox', 'fort_knox_reserve', 'phantom_nickel',
                                'king_of_coins', 'first_strike', 'colonial_gold',
                                'rarest_eagle', 'phantom_dollar', 'pattern_origin',
                                'secret_error', 'secret_overdate', 'secret_proof'):
                if AbilityResolver.can_activate(card, player, self):
                    result = self.activate_ability(player, card)
                    if "Cannot" not in result:
                        actions.append(result)

        # ── Challenge logic (once per turn, respects cooldown) ──
        my_val = self.compute_purse_value(player)
        op_val = self.compute_purse_value(opponent)
        can_challenge = player.challenge_cooldown == 0
        if diff == 'easy':
            if can_challenge and my_val > op_val and random.random() < 0.2:
                result = self.challenge(player, opponent)
                actions.append(result)
                challenged_this_turn = True
        elif diff == 'medium':
            if can_challenge and my_val > op_val * 1.2 and random.random() < 0.5:
                result = self.challenge(player, opponent)
                actions.append(result)
                challenged_this_turn = True
        else:  # hard
            if can_challenge and my_val > op_val * 1.1 and not opponent.immune and op_val > 1.0:
                result = self.challenge(player, opponent)
                actions.append(result)
                challenged_this_turn = True

        self.end_turn(player)
        actions.append(f"  {player.name} ended turn. Purse: ${self.compute_purse_value(player):.2f}")
        return actions

    # ── Human Turn ───────────────────────────────────────────────────────────

    def human_take_turn(self, player: Player) -> List[str]:
        actions = []
        opponent = self.players[0] if player != self.players[0] else self.players[-1]
        player.draw(2)
        actions.append(f"  {clr('You drew 2 cards.', C.GREEN)}")
        challenged_this_turn = False

        action_phase = True
        while action_phase:
            self.display_game_state(player, opponent)
            print(f"\n  {clr('=== YOUR TURN ===', C.BOLD + C.CYAN)}")
            print(f"  {clr('Purse Value:', C.YELLOW)} ${self.compute_purse_value(player):.2f}")
            print(f"  {clr('Opponent Purse:', C.RED)} ${self.compute_purse_value(opponent):.2f}")
            print(f"  {clr('Target:', C.GREEN)} ${self.target_value:.2f}")
            if self.active_events:
                events_str = ', '.join(f"{n} ({r}r)" for n, r in self.active_events)
                print(f"  {clr('Active Events:', C.MAGENTA)} {events_str}")

            print(f"\n  {clr('Hand:', C.WHITE)}")
            for i, card in enumerate(player.hand):
                color = RARITY_COLOR.get(card.rarity, C.WHITE)
                print(f"    {i+1}. {clr(card.short_str(), color)} | {card.ability_desc}")

            print(f"\n  {clr('Actions:', C.BOLD)}")
            print(f"    {clr('p', C.GREEN)} - Play card to purse")
            print(f"    {clr('c', C.GREEN)} - Make change (break large into small)")
            print(f"    {clr('a', C.GREEN)} - Activate ability")
            print(f"    {clr('e', C.GREEN)} - Play event card")
            print(f"    {clr('x', C.GREEN)} - Challenge opponent (Demand Exchange)")
            print(f"    {clr('d', C.GREEN)} - Discard a card")
            print(f"    {clr('v', C.GREEN)} - View purse details (bonuses/multipliers)")
            print(f"    {clr('s', C.GREEN)} - Save game")
            print(f"    {clr('h', C.GREEN)} - Help / Rules")
            print(f"    {clr('q', C.GREEN)} - End turn")

            choice = input(f"\n  {clr('Choice:', C.BOLD)} ").strip().lower()

            if choice == 'q':
                action_phase = False
            elif choice == 'h':
                self.display_help()
            elif choice == 'p':
                idx = self._get_card_index(player.hand, "Play which card?")
                if idx is not None:
                    result = self.play_card(player, player.hand[idx])
                    actions.append(result)
                    print(f"\n  {result}")
            elif choice == 'c':
                self._make_change_ui(player, actions)
            elif choice == 'a':
                self._activate_ability_ui(player, actions)
            elif choice == 'e':
                events_in_hand = [c for c in player.hand if c.card_type == 'Event']
                if not events_in_hand:
                    print(f"\n  {clr('No event cards in hand.', C.RED)}")
                else:
                    idx = self._get_card_index(events_in_hand, "Play which event?")
                    if idx is not None:
                        result = self.play_event(player, events_in_hand[idx])
                        actions.append(result)
                        print(f"\n  {result}")
            elif choice == 'x':
                if challenged_this_turn:
                    print(f"\n  {clr('Already challenged this turn!', C.RED)}")
                elif player.challenge_cooldown > 0:
                    print(f"\n  {clr(f'Challenge on cooldown! Wait {player.challenge_cooldown} more turn(s).', C.RED)}")
                else:
                    result = self.challenge(player, opponent)
                    actions.append(result)
                    print(f"\n  {result}")
                    if "WON" in result or "LOST" in result:
                        challenged_this_turn = True
            elif choice == 'd':
                idx = self._get_card_index(player.hand, "Discard which card?")
                if idx is not None:
                    card = player.hand[idx]
                    player.discard_card(card)
                    actions.append(f"  Discarded {card.name}.")
                    print(f"\n  {clr('Discarded', C.YELLOW)} {card.name}.")
            elif choice == 'v':
                self._display_purse_details(player)
            elif choice == 's':
                name = input(f"  {clr('Save name (blank for auto):', C.BOLD)} ").strip()
                path = save_game(self, name if name else None)
                print(f"\n  {clr(f'Game saved to {path}', C.GREEN)}")

        self.end_turn(player)
        actions.append(f"  {clr('You ended turn.', C.CYAN)} Purse: ${self.compute_purse_value(player):.2f}")
        return actions

    def _get_card_index(self, cards: List[Card], prompt: str) -> Optional[int]:
        if not cards:
            print(f"  {clr('No cards available.', C.RED)}")
            return None
        print(f"\n  {prompt}")
        for i, card in enumerate(cards):
            color = RARITY_COLOR.get(card.rarity, C.WHITE)
            print(f"    {i+1}. {clr(card.short_str(), color)}")
        try:
            choice = input(f"  {clr('Number:', C.BOLD)} ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(cards):
                return idx
            print(f"  {clr('Invalid selection.', C.RED)}")
        except (ValueError, IndexError):
            print(f"  {clr('Invalid input.', C.RED)}")
        return None

    def _display_purse_details(self, player: Player):
        """Show detailed purse breakdown including per-card values, bonuses, and multipliers."""
        purse = player.purse
        print(f"\n  {clr('='*60, C.BOLD)}")
        print(f"  {clr('PURSE DETAILS', C.BOLD + C.CYAN)}")
        print(f"  {clr('='*60, C.BOLD)}")
        if not purse.cards:
            print(f"  {clr('Purse is empty.', C.DIM)}")
            return
        base_total = 0.0
        for card in purse.cards:
            color = RARITY_COLOR.get(card.rarity, C.WHITE)
            card_val = card.value
            multipliers = purse.card_multipliers.get(card.card_id, [])
            for desc, mult in multipliers:
                card_val *= mult
            base_total += card_val
            mult_str = f" (x{' x'.join(str(m) for _, m in multipliers)})" if multipliers else ""
            print(f"    {clr(card.short_str(), color)} = ${card_val:.2f}{mult_str}")
            for desc, mult in multipliers:
                print(f"      {clr(f'x{mult} {desc}', C.MAGENTA)}")
        print(f"\n  {clr('Card value subtotal:', C.YELLOW)} ${base_total:.2f}")
        if purse.bonuses:
            print(f"  {clr('Bonuses:', C.GREEN)}")
            for desc, amount in purse.bonuses:
                print(f"    +${amount:.2f} {desc}")
            bonus_total = sum(a for _, a in purse.bonuses)
            print(f"  {clr('Bonus subtotal:', C.YELLOW)} +${bonus_total:.2f}")
        if purse.multipliers:
            print(f"  {clr('Purse multipliers:', C.MAGENTA)}")
            for desc, mult in purse.multipliers:
                print(f"    x{mult} {desc}")
        total = self.compute_purse_value(player)
        print(f"\n  {clr('TOTAL PURSE VALUE:', C.BOLD + C.GREEN)} ${total:.2f}")
        print(f"  {clr('Target:', C.YELLOW)} ${self.target_value:.2f}")
        progress = total / self.target_value * 100
        bar_len = 20
        filled = min(int(progress / 100 * bar_len), bar_len)
        bar = '#' * filled + '-' * (bar_len - filled)
        print(f"  {clr('Progress:', C.CYAN)} [{bar}] {progress:.0f}%")

    def _make_change_ui(self, player: Player, actions: List[str]):
        if not player.purse.cards:
            print(f"\n  {clr('No cards in purse to break.', C.RED)}")
            return
        print(f"\n  {clr('Select large card from purse to break:', C.YELLOW)}")
        for i, card in enumerate(player.purse.cards):
            print(f"    {i+1}. {card.short_str()}")
        try:
            choice = input(f"  {clr('Number:', C.BOLD)} ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(player.purse.cards):
                large = player.purse.cards[idx]
                if not player.hand:
                    print(f"  {clr('No cards in hand to make change with.', C.RED)}")
                    return
                print(f"\n  {clr('Select small cards from hand (comma-separated):', C.YELLOW)}")
                for i, card in enumerate(player.hand):
                    print(f"    {i+1}. {card.short_str()}")
                choice = input(f"  {clr('Numbers:', C.BOLD)} ").strip()
                indices = [int(x.strip()) - 1 for x in choice.split(',') if x.strip().isdigit()]
                small_cards = [player.hand[i] for i in indices if 0 <= i < len(player.hand)]
                if small_cards:
                    result = self.make_change(player, large, small_cards)
                    actions.append(result)
                    print(f"\n  {result}")
        except (ValueError, IndexError):
            print(f"  {clr('Invalid input.', C.RED)}")

    def _activate_ability_ui(self, player: Player, actions: List[str]):
        activatable = [c for c in player.purse.cards if AbilityResolver.can_activate(c, player, self)]
        if not activatable:
            print(f"\n  {clr('No abilities available to activate.', C.RED)}")
            return
        print(f"\n  {clr('Activatable abilities:', C.YELLOW)}")
        for i, card in enumerate(activatable):
            print(f"    {i+1}. {card.name} | {card.ability_desc}")
        try:
            choice = input(f"  {clr('Number:', C.BOLD)} ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(activatable):
                result = self.activate_ability(player, activatable[idx])
                actions.append(result)
                print(f"\n  {result}")
        except (ValueError, IndexError):
            print(f"  {clr('Invalid input.', C.RED)}")

    def display_game_state(self, player: Player, opponent: Player):
        print(f"\n  {'='*60}")
        print(f"  {clr('Round', C.BOLD)} {self.current_round}/{self.max_rounds} | "
              f"{clr('Target:', C.GREEN)} ${self.target_value:.2f}")
        print(f"  {'='*60}")
        print(f"  {clr(player.name + ' (You):', C.CYAN)} "
              f"Purse ${self.compute_purse_value(player):.2f} "
              f"({len(player.purse.cards)} cards) | "
              f"Hand: {len(player.hand)} | Deck: {player.deck.remaining()}")
        print(f"  {clr(opponent.name + ' (AI):', C.RED)} "
              f"Purse ${self.compute_purse_value(opponent):.2f} "
              f"({len(opponent.purse.cards)} cards) | "
              f"Hand: {len(opponent.hand)} | Deck: {opponent.deck.remaining()}")
        if player.purse.cards:
            print(f"\n  {clr('Your Purse:', C.CYAN)}")
            for card in player.purse.cards:
                color = RARITY_COLOR.get(card.rarity, C.WHITE)
                print(f"    {clr(card.short_str(), color)}")
        if opponent.purse.cards:
            print(f"\n  {clr('Opponent Purse:', C.RED)}")
            for card in opponent.purse.cards:
                color = RARITY_COLOR.get(card.rarity, C.WHITE)
                print(f"    {clr(card.short_str(), color)}")

    def display_help(self):
        print(f"\n  {clr('='*60, C.BOLD)}")
        print(f"  {clr('THE EXCHANGE - RULES & HELP', C.BOLD + C.CYAN)}")
        print(f"  {clr('='*60, C.BOLD)}")
        print(f"""
  {clr('OBJECTIVE:', C.YELLOW)}
    First to reach ${self.target_value:.2f} in purse value wins!
    Or have the highest value when max rounds ({self.max_rounds}) reached.

  {clr('TURN STRUCTURE:', C.YELLOW)}
    1. Draw 2 cards from your deck
    2. Take actions (play cards, make change, activate abilities, challenge)
    3. End turn (auto-discard to 10 card hand limit)

  {clr('ACTIONS:', C.YELLOW)}
    {clr('Play', C.GREEN)} - Add a card from hand to your purse (tableau)
    {clr('Make Change', C.GREEN)} - Break a large card into smaller ones from hand
    {clr('Activate', C.GREEN)} - Use a once-per-game ability from your purse
    {clr('Event', C.GREEN)} - Play an event card for global effects
    {clr('Challenge', C.GREEN)} - Demand Exchange: compare purse values
             Winner steals a card from loser! (highest if >10% advantage)
             +10% bonus if you have >20% advantage.
             2-turn cooldown after challenging.
             Immune players (Fort Knox) cannot be challenged.

  {clr('SYNERGIES:', C.YELLOW)}
    Copper Rush - Multiple copper coins give bonuses
    Silver Spark - Multiple silver coins boost each other
    Gold Standard - Multiple gold coins give big bonuses
    Greenback - Multiple paper notes synergize
    Morgan Synergy - 3+ Morgan dollars give +0.10 each
    Wartime - WWII-era cards boost each other

  {clr('RARITY:', C.YELLOW)}
    C (Common) - Building blocks, 55% of packs
    U (Uncommon) - Reliable synergies, 28%
    R (Rare) - Strong cards, 12%
    UR (Ultra-Rare) - Chase cards, 3.5%
    L (Legendary) - Game-changing, 1%
    SR (Secret Rare) - Ultra-collectible, 0.5%
        """)

    def save(self, filepath: str) -> bool:
        try:
            state = {
                'target_value': self.target_value,
                'max_rounds': self.max_rounds,
                'current_round': self.current_round,
                'current_player_idx': self.current_player_idx,
                'game_over': self.game_over,
                'event_modifiers': {k: v for k, v in self.event_modifiers.items()},
                'active_events': self.active_events,
                'ai_difficulty': self.ai_difficulty,
                'players': [p.to_dict() for p in self.players],
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"  {clr(f'Save error: {e}', C.RED)}")
            return False

    @staticmethod
    def load(filepath: str) -> Optional['ExchangeGame']:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                state = json.load(f)
            players = [Player.from_dict(pd) for pd in state['players']]
            game = ExchangeGame(players, state['target_value'], state['max_rounds'])
            game.current_round = state['current_round']
            game.current_player_idx = state['current_player_idx']
            game.game_over = state['game_over']
            game.event_modifiers = state.get('event_modifiers', {})
            game.active_events = [tuple(e) for e in state.get('active_events', [])]
            game.ai_difficulty = state.get('ai_difficulty', 'medium')
            return game
        except Exception as e:
            print(f"  {clr(f'Load error: {e}', C.RED)}")
            return None

    def to_json(self) -> str:
        return json.dumps({
            'target_value': self.target_value,
            'max_rounds': self.max_rounds,
            'current_round': self.current_round,
            'current_player_idx': self.current_player_idx,
            'game_over': self.game_over,
            'event_modifiers': self.event_modifiers,
            'active_events': self.active_events,
            'ai_difficulty': self.ai_difficulty,
            'players': [p.to_dict() for p in self.players],
        }, indent=2, ensure_ascii=False)


# =============================================================================
# SECTION 10 - AI SIMULATION
# =============================================================================

def run_simulation(num_games: int = 10, target: float = 500.0,
                   verbose: bool = False) -> Dict:
    card_pool = create_base_set()
    results = {'p1_wins': 0, 'p2_wins': 0, 'rounds': [], 'avg_purse': []}
    for game_num in range(num_games):
        deck1 = DeckBuilder.auto_build_deck(card_pool)
        deck2 = DeckBuilder.auto_build_deck(card_pool)
        p1 = Player("Bank Alpha", Deck(deck1), is_ai=True)
        p2 = Player("Bank Beta", Deck(deck2), is_ai=True)
        game = ExchangeGame([p1, p2], target_value=target, max_rounds=30)
        game.setup()
        while not game.game_over:
            current = game.players[game.current_player_idx]
            actions = game.ai_take_turn(current)
            if verbose:
                for a in actions:
                    print(a)
            game.check_win_conditions()
            if game.game_over:
                break
            game.next_turn()
        if game.winner == p1:
            results['p1_wins'] += 1
        else:
            results['p2_wins'] += 1
        results['rounds'].append(game.current_round)
        results['avg_purse'].append(game.compute_purse_value(game.winner))
        if verbose:
            print(f"\n  Game {game_num+1}: {game.winner.name} wins in "
                  f"{game.current_round} rounds with ${game.compute_purse_value(game.winner):.2f}")
    return results


# =============================================================================
# SECTION 11 - CARD DATABASE BROWSER
# =============================================================================

def browse_cards(card_pool: List[Card]):
    while True:
        print(f"\n  {clr('='*60, C.BOLD)}")
        print(f"  {clr('CARD DATABASE BROWSER', C.BOLD + C.CYAN)}")
        print(f"  {clr('='*60, C.BOLD)}")
        print(f"  Total cards: {len(card_pool)}")
        for r in ['C', 'U', 'R', 'UR', 'L', 'SR']:
            count = sum(1 for c in card_pool if c.rarity == r)
            print(f"    {RARITY_EMOJI[r]} {RARITY_NAMES[r]:12s}: {count} cards")
        events = sum(1 for c in card_pool if c.card_type == 'Event')
        print(f"    {' '*13}: {events} Event cards")
        print(f"\n  {clr('Filter by:', C.YELLOW)}")
        print(f"    1. All cards")
        print(f"    2. By rarity (C/U/R/UR/L/SR)")
        print(f"    3. By type (Coin/Note/Event)")
        print(f"    4. By denomination")
        print(f"    5. Search by name")
        print(f"    6. Show card details (by ID)")
        print(f"    0. Back to main menu")
        choice = input(f"\n  {clr('Choice:', C.BOLD)} ").strip()
        if choice == '0':
            break
        elif choice == '1':
            _display_card_list(card_pool)
        elif choice == '2':
            r = input(f"  {clr('Rarity (C/U/R/UR/L/SR):', C.BOLD)} ").strip().upper()
            filtered = [c for c in card_pool if c.rarity == r]
            _display_card_list(filtered)
        elif choice == '3':
            t = input(f"  {clr('Type (Coin/Note/Event):', C.BOLD)} ").strip().capitalize()
            filtered = [c for c in card_pool if c.card_type == t]
            _display_card_list(filtered)
        elif choice == '4':
            denoms = sorted(set(c.denomination for c in card_pool if c.denomination))
            print(f"\n  {clr('Denominations:', C.YELLOW)}")
            for i, d in enumerate(denoms):
                print(f"    {i+1}. {d}")
            try:
                idx = int(input(f"  {clr('Number:', C.BOLD)} ").strip()) - 1
                if 0 <= idx < len(denoms):
                    filtered = [c for c in card_pool if c.denomination == denoms[idx]]
                    _display_card_list(filtered)
            except (ValueError, IndexError):
                print(f"  {clr('Invalid.', C.RED)}")
        elif choice == '5':
            query = input(f"  {clr('Search:', C.BOLD)} ").strip().lower()
            filtered = [c for c in card_pool if query in c.name.lower()]
            _display_card_list(filtered)
        elif choice == '6':
            cid = input(f"  {clr('Card ID:', C.BOLD)} ").strip().upper()
            card = next((c for c in card_pool if c.card_id == cid), None)
            if card:
                _display_card_detail(card)
            else:
                print(f"  {clr('Card not found.', C.RED)}")

def _display_card_list(cards: List[Card]):
    if not cards:
        print(f"\n  {clr('No cards found.', C.RED)}")
        return
    page_size = 20
    page = 0
    while True:
        start = page * page_size
        end = min(start + page_size, len(cards))
        print(f"\n  {clr(f'Cards {start+1}-{end} of {len(cards)}', C.DIM)}")
        print(f"  {'-'*60}")
        for i in range(start, end):
            card = cards[i]
            color = RARITY_COLOR.get(card.rarity, C.WHITE)
            emoji = RARITY_EMOJI.get(card.rarity, '?')
            temoji = TYPE_EMOJI.get(card.card_type, '?')
            print(f"  {i+1:3d}. {emoji} {clr(f'${card.value:>10.4f}', C.GREEN)} "
                  f"{clr(card.name, color)} {temoji} [{card.card_id}]")
        if end >= len(cards):
            print(f"\n  {clr('End of list.', C.DIM)}")
            break
        nav = input(f"\n  {clr('[n]ext page, [q]uit:', C.BOLD)} ").strip().lower()
        if nav != 'n':
            break
        page += 1

def _display_card_detail(card: Card):
    color = RARITY_COLOR.get(card.rarity, C.WHITE)
    print(f"\n  {clr('='*60, C.BOLD)}")
    print(f"  {clr(card.name, color)}")
    print(f"  {clr('='*60, C.BOLD)}")
    print(f"  {clr('ID:', C.YELLOW)}          {card.card_id}")
    print(f"  {clr('Value:', C.YELLOW)}        ${card.value:.4f}")
    print(f"  {clr('Type:', C.YELLOW)}         {card.card_type}")
    print(f"  {clr('Composition:', C.YELLOW)}  {card.composition}")
    print(f"  {clr('Era:', C.YELLOW)}          {card.era}")
    print(f"  {clr('Years:', C.YELLOW)}        {card.year_range}")
    print(f"  {clr('Rarity:', C.YELLOW)}       {card.rarity_str()}")
    print(f"  {clr('Denomination:', C.YELLOW)} {card.denomination}")
    print(f"  {clr('Ability:', C.YELLOW)}      {card.ability}")
    print(f"  {clr('Description:', C.YELLOW)}  {card.ability_desc}")
    print(f"  {clr('Tags:', C.YELLOW)}         {', '.join(card.tags)}")
    print(f"  {clr('Flavor:', C.YELLOW)}       {clr(card.flavor, C.DIM)}")
    print(f"  {clr('='*60, C.BOLD)}")


# =============================================================================
# SECTION 12 - BOOSTER PACK DEMO
# =============================================================================

def booster_demo(card_pool: List[Card]):
    bp = BoosterPack(card_pool)
    while True:
        print(f"\n  {clr('='*60, C.BOLD)}")
        print(f"  {clr('BOOSTER PACK DEMO', C.BOLD + C.MAGENTA)}")
        print(f"  {clr('='*60, C.BOLD)}")
        print(f"  Pack size: 12 cards")
        print(f"  Ratios: ~7-8 C, ~2-3 U, 1 R, ~5% UR/L/SR chance")
        print(f"  Legendary chance: ~1% | Secret Rare: ~0.5%")
        print(f"\n  {clr('Options:', C.YELLOW)}")
        print(f"    1. Open a single pack")
        print(f"    2. Open a booster box (24 packs)")
        print(f"    3. Open 10 packs (rapid)")
        print(f"    0. Back to main menu")
        choice = input(f"\n  {clr('Choice:', C.BOLD)} ").strip()
        if choice == '0':
            break
        elif choice == '1':
            pack = bp.generate_pack()
            _display_pack(pack, "Booster Pack")
        elif choice == '2':
            box = bp.generate_box(24)
            all_cards = []
            for i, pack in enumerate(box):
                print(f"\n  {clr(f'--- Pack {i+1}/24 ---', C.DIM)}")
                _display_pack(pack, f"Pack {i+1}", compact=True)
                all_cards.extend(pack)
            print(f"\n  {clr('='*60, C.BOLD)}")
            print(f"  {clr('BOX SUMMARY', C.BOLD + C.MAGENTA)}")
            print(f"  {clr('='*60, C.BOLD)}")
            _display_pack_summary(all_cards)
        elif choice == '3':
            all_cards = []
            for _ in range(10):
                pack = bp.generate_pack()
                all_cards.extend(pack)
            _display_pack_summary(all_cards)
            chase = [c for c in all_cards if c.rarity in ('L', 'SR')]
            if chase:
                print(f"\n  {clr('CHASE PULLS!', C.BOLD + C.YELLOW)}")
                for c in chase:
                    color = RARITY_COLOR.get(c.rarity, C.WHITE)
                    print(f"    {RARITY_EMOJI[c.rarity]} {clr(c.name, color)} [{c.card_id}]")
            else:
                print(f"\n  {clr('No chase cards pulled this time.', C.DIM)}")

def _display_pack(pack: List[Card], title: str, compact: bool = False):
    print(f"\n  {clr('='*60, C.BOLD)}")
    print(f"  {clr(title, C.BOLD + C.MAGENTA)}")
    print(f"  {clr('='*60, C.BOLD)}")
    rarity_order = {'SR': 0, 'L': 1, 'UR': 2, 'R': 3, 'U': 4, 'C': 5}
    sorted_pack = sorted(pack, key=lambda c: rarity_order.get(c.rarity, 99))
    for card in sorted_pack:
        color = RARITY_COLOR.get(card.rarity, C.WHITE)
        emoji = RARITY_EMOJI.get(card.rarity, '?')
        temoji = TYPE_EMOJI.get(card.card_type, '?')
        if compact:
            print(f"  {emoji} {clr(f'${card.value:>10.4f}', C.GREEN)} "
                  f"{clr(card.name, color)} {temoji}")
        else:
            print(f"  {emoji} {clr(f'${card.value:>10.4f}', C.GREEN)} "
                  f"{clr(card.name, color)} {temoji} [{card.card_id}]")
            print(f"      {clr(card.ability_desc, C.DIM)}")
            print(f"      {clr(card.flavor, C.DIM)}")
    _display_pack_summary(pack)

def _display_pack_summary(cards: List[Card]):
    print(f"\n  {clr('Summary:', C.YELLOW)}")
    for r in ['C', 'U', 'R', 'UR', 'L', 'SR']:
        count = sum(1 for c in cards if c.rarity == r)
        if count > 0:
            print(f"    {RARITY_EMOJI[r]} {RARITY_NAMES[r]:12s}: {count}")
    total_value = sum(c.value for c in cards)
    print(f"    {'Total Value:':14s} ${total_value:.2f}")


# =============================================================================
# SECTION 13 - SAVE/LOAD MANAGEMENT
# =============================================================================

SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saves')

def ensure_save_dir():
    os.makedirs(SAVE_DIR, exist_ok=True)

def list_saves() -> List[str]:
    ensure_save_dir()
    saves = []
    for f in os.listdir(SAVE_DIR):
        if f.endswith('.json'):
            saves.append(f)
    return sorted(saves)

def save_game(game: ExchangeGame, name: str = None) -> str:
    ensure_save_dir()
    if name is None:
        name = f"save_{len(list_saves())+1}"
    if not name.endswith('.json'):
        name += '.json'
    filepath = os.path.join(SAVE_DIR, name)
    game.save(filepath)
    return filepath

def load_game(name: str) -> Optional[ExchangeGame]:
    ensure_save_dir()
    if not name.endswith('.json'):
        name += '.json'
    filepath = os.path.join(SAVE_DIR, name)
    return ExchangeGame.load(filepath)


# =============================================================================
# SECTION 14 - MAIN MENU & GAME LOOP
# =============================================================================

def print_banner():
    banner = r"""
  +-------------------------------------------------------------+
  |                                                             |
  |    THE  EXCHANGE  -  Historical U.S. Currency TCG          |
  |                                                             |
  |    "Collect history. Master the exchange. Build fortune."   |
  |                                                             |
  +-------------------------------------------------------------+
"""
    print(clr(banner, C.CYAN + C.BOLD))

def launch_gui():
    """Launch the pygame graphical client directly."""
    try:
        import importlib
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        gui_module = importlib.import_module('TCG_GUI')
        gui = gui_module.GameGUI()
        gui.run()
    except Exception as e:
        print(f"  Failed to launch GUI: {e}")
        print(f"  Make sure pygame is installed: pip install pygame")
        input("  Press Enter to continue...")

def main_menu():
    card_pool = create_base_set()
    while True:
        print_banner()
        print(f"  {clr('Card Database:', C.YELLOW)} {len(card_pool)} unique cards")
        print(f"  {clr('Rarities:', C.YELLOW)} C/U/R/UR/L/SR")
        print()
        print(f"  {clr('Main Menu:', C.BOLD + C.CYAN)}")
        print(f"    {clr('1.', C.GREEN)} New Game (Human vs AI)")
        print(f"    {clr('2.', C.GREEN)} Load Game")
        print(f"    {clr('3.', C.GREEN)} Booster Pack Demo")
        print(f"    {clr('4.', C.GREEN)} Card Database Browser")
        print(f"    {clr('5.', C.GREEN)} AI Simulation")
        print(f"    {clr('6.', C.GREEN)} Deck Builder")
        print(f"    {clr('7.', C.GREEN)} Launch GUI (Graphical Client)")
        print(f"    {clr('0.', C.RED)} Quit")
        choice = input(f"\n  {clr('Choice:', C.BOLD)} ").strip()
        if choice == '0':
            print(f"\n  {clr('Thanks for playing The Exchange!', C.CYAN)}")
            break
        elif choice == '1':
            new_game(card_pool)
        elif choice == '2':
            load_game_menu()
        elif choice == '3':
            booster_demo(card_pool)
        elif choice == '4':
            browse_cards(card_pool)
        elif choice == '5':
            simulation_menu()
        elif choice == '6':
            deck_builder_menu(card_pool)
        elif choice == '7':
            launch_gui()

def new_game(card_pool: List[Card]):
    print(f"\n  {clr('='*60, C.BOLD)}")
    print(f"  {clr('NEW GAME', C.BOLD + C.CYAN)}")
    print(f"  {clr('='*60, C.BOLD)}")
    print(f"\n  {clr('Game Length:', C.YELLOW)}")
    print(f"    1. Short (Target: $500, 20 rounds)")
    print(f"    2. Medium (Target: $1000, 30 rounds)")
    print(f"    3. Long (Target: $5000, 40 rounds)")
    print(f"    4. Epic (Target: $10000, 50 rounds)")
    choice = input(f"\n  {clr('Choice:', C.BOLD)} ").strip()
    targets = {'1': (500, 20), '2': (1000, 30), '3': (5000, 40), '4': (10000, 50)}
    target, max_rounds = targets.get(choice, (500, 20))
    print(f"\n  {clr('AI Difficulty:', C.YELLOW)}")
    print(f"    1. Easy (random play, no challenge)")
    print(f"    2. Medium (basic strategy)")
    print(f"    3. Hard (optimal play, aggressive)")
    diff_choice = input(f"\n  {clr('Choice:', C.BOLD)} ").strip()
    difficulties = {'1': 'easy', '2': 'medium', '3': 'hard'}
    ai_difficulty = difficulties.get(diff_choice, 'medium')
    print(f"\n  {clr('Building decks...', C.DIM)}")
    human_deck = DeckBuilder.auto_build_deck(card_pool, target_size=45)
    ai_deck = DeckBuilder.auto_build_deck(card_pool, target_size=45)
    valid, errors = DeckBuilder.validate_deck(human_deck)
    if not valid:
        for e in errors:
            print(f"  {clr(e, C.RED)}")
        while len(human_deck) < 40:
            human_deck.append(copy.deepcopy(random.choice(
                [c for c in card_pool if c.rarity == 'C'])))
    human = Player("You", Deck(human_deck), is_ai=False)
    ai = Player("AI Banker", Deck(ai_deck), is_ai=True)
    game = ExchangeGame([human, ai], target_value=target, max_rounds=max_rounds)
    game.ai_difficulty = ai_difficulty
    game.setup()
    print(f"\n  {clr('Game started!', C.GREEN)} Target: ${target:.2f} | AI: {ai_difficulty.capitalize()}")
    print(f"  {clr('Your starter purse:', C.CYAN)}")
    for card in human.purse.cards:
        print(f"    {card.short_str()}")
    input(f"\n  {clr('Press Enter to begin...', C.DIM)}")
    while not game.game_over:
        current = game.players[game.current_player_idx]
        if current.is_ai:
            print(f"\n  {clr(f'--- {current.name} Turn (Round {game.current_round}) ---', C.RED)}")
            actions = game.ai_take_turn(current)
            for a in actions:
                print(a)
        else:
            game.human_take_turn(current)
        if game.check_win_conditions():
            break
        game.next_turn()
    # ── End-of-game summary ──
    print(f"\n  {clr('='*60, C.BOLD)}")
    print(f"  {clr('GAME OVER', C.BOLD + C.CYAN)}")
    print(f"  {clr('='*60, C.BOLD)}")
    if game.winner:
        if game.winner.is_ai:
            print(f"  {clr(f'{game.winner.name} wins!', C.RED + C.BOLD)}")
        else:
            print(f"  {clr('YOU WIN!', C.GREEN + C.BOLD)}")
        print(f"\n  {clr('Final Values:', C.YELLOW)}")
        for p in game.players:
            val = game.compute_purse_value(p)
            bar_len = 20
            ratio = val / max(self_target, 1) if (self_target := game.target_value) else 0
            filled = min(int(ratio * bar_len), bar_len)
            bar = '#' * filled + '-' * (bar_len - filled)
            print(f"    {p.name}: ${val:.2f} ({len(p.purse.cards)} cards) [{bar}]")
        # Detailed stats
        print(f"\n  {clr('Game Statistics:', C.YELLOW)}")
        print(f"    Rounds played: {game.current_round}")
        win_val = game.compute_purse_value(game.winner)
        lose_val = max(game.compute_purse_value(p) for p in game.players if p != game.winner)
        margin = win_val - lose_val
        print(f"    Win margin: ${margin:.2f}")
        print(f"    Target: ${game.target_value:.2f}")
        # Top cards in winner's purse
        top_cards = sorted(game.winner.purse.cards, key=lambda c: c.value, reverse=True)[:3]
        print(f"\n  {clr('Winner Top Cards:', C.YELLOW)}")
        for card in top_cards:
            color = RARITY_COLOR.get(card.rarity, C.WHITE)
            print(f"    {clr(card.short_str(), color)} - {card.ability_desc}")
        # Rarity breakdown
        print(f"\n  {clr('Winner Purse Rarity:', C.YELLOW)}")
        for r in ['SR', 'L', 'UR', 'R', 'U', 'C']:
            count = sum(1 for c in game.winner.purse.cards if c.rarity == r)
            if count:
                print(f"    {RARITY_EMOJI[r]} {RARITY_NAMES[r]:12s}: {count}")
    print(f"  {clr('='*60, C.BOLD)}")
    save_choice = input(f"\n  {clr('Save game? (y/n):', C.BOLD)} ").strip().lower()
    if save_choice == 'y':
        name = input(f"  {clr('Save name:', C.BOLD)} ").strip()
        path = save_game(game, name if name else None)
        print(f"  {clr(f'Saved to {path}', C.GREEN)}")

def load_game_menu():
    saves = list_saves()
    if not saves:
        print(f"\n  {clr('No save files found.', C.RED)}")
        return
    print(f"\n  {clr('Save Files:', C.BOLD + C.CYAN)}")
    for i, s in enumerate(saves):
        print(f"    {i+1}. {s}")
    choice = input(f"\n  {clr('Load which save? (number, 0=cancel):', C.BOLD)} ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(saves):
            game = load_game(saves[idx])
            if game:
                print(f"\n  {clr('Game loaded!', C.GREEN)}")
                while not game.game_over:
                    current = game.players[game.current_player_idx]
                    if current.is_ai:
                        print(f"\n  {clr(f'--- {current.name} Turn ---', C.RED)}")
                        actions = game.ai_take_turn(current)
                        for a in actions:
                            print(a)
                    else:
                        game.human_take_turn(current)
                    if game.check_win_conditions():
                        break
                    game.next_turn()
                print(f"\n  {clr('='*60, C.BOLD)}")
                if game.winner:
                    if game.winner.is_ai:
                        print(f"  {clr(f'{game.winner.name} wins!', C.RED + C.BOLD)}")
                    else:
                        print(f"  {clr('YOU WIN!', C.GREEN + C.BOLD)}")
                    for p in game.players:
                        val = game.compute_purse_value(p)
                        print(f"    {p.name}: ${val:.2f}")
                print(f"  {clr('='*60, C.BOLD)}")
    except (ValueError, IndexError):
        print(f"  {clr('Invalid selection.', C.RED)}")

def simulation_menu():
    print(f"\n  {clr('='*60, C.BOLD)}")
    print(f"  {clr('AI SIMULATION', C.BOLD + C.CYAN)}")
    print(f"  {clr('='*60, C.BOLD)}")
    num = input(f"  {clr('Number of games (default 10):', C.BOLD)} ").strip()
    try:
        num_games = int(num) if num else 10
    except ValueError:
        num_games = 10
    target = input(f"  {clr('Target value (default 500):', C.BOLD)} ").strip()
    try:
        target_val = float(target) if target else 500.0
    except ValueError:
        target_val = 500.0
    verbose = input(f"  {clr('Verbose output? (y/n, default n):', C.BOLD)} ").strip().lower() == 'y'
    print(f"\n  {clr(f'Running {num_games} simulations...', C.DIM)}")
    results = run_simulation(num_games=num_games, target=target_val, verbose=verbose)
    print(f"\n  {clr('='*60, C.BOLD)}")
    print(f"  {clr('SIMULATION RESULTS', C.BOLD + C.GREEN)}")
    print(f"  {clr('='*60, C.BOLD)}")
    print(f"  Games played:    {num_games}")
    print(f"  Bank Alpha wins: {results['p1_wins']} ({results['p1_wins']/num_games*100:.0f}%)")
    print(f"  Bank Beta wins:  {results['p2_wins']} ({results['p2_wins']/num_games*100:.0f}%)")
    avg_rounds = sum(results['rounds']) / len(results['rounds']) if results['rounds'] else 0
    print(f"  Avg rounds:      {avg_rounds:.1f}")
    avg_purse = sum(results['avg_purse']) / len(results['avg_purse']) if results['avg_purse'] else 0
    print(f"  Avg winner purse: ${avg_purse:.2f}")

def deck_builder_menu(card_pool: List[Card]):
    print(f"\n  {clr('='*60, C.BOLD)}")
    print(f"  {clr('DECK BUILDER', C.BOLD + C.CYAN)}")
    print(f"  {clr('='*60, C.BOLD)}")
    print(f"  Min deck size: {DeckBuilder.MIN_DECK_SIZE}")
    print(f"  Max deck size: {DeckBuilder.MAX_DECK_SIZE}")
    print(f"  Min Commons:   {DeckBuilder.MIN_COMMONS}")
    print(f"  Max Events:    5")
    print(f"\n  {clr('Options:', C.YELLOW)}")
    print(f"    1. Auto-generate a deck")
    print(f"    2. Generate a starter deck")
    print(f"    3. Validate a random deck")
    print(f"    0. Back")
    choice = input(f"\n  {clr('Choice:', C.BOLD)} ").strip()
    if choice == '1':
        size = input(f"  {clr('Deck size (40-60, default 45):', C.BOLD)} ").strip()
        try:
            target_size = int(size) if size else 45
            target_size = max(40, min(60, target_size))
        except ValueError:
            target_size = 45
        deck = DeckBuilder.auto_build_deck(card_pool, target_size)
        valid, errors = DeckBuilder.validate_deck(deck)
        print(f"\n  {clr('Generated Deck:', C.BOLD)}")
        print(f"  Size: {len(deck)} cards")
        for r in ['C', 'U', 'R', 'UR', 'L', 'SR']:
            count = sum(1 for c in deck if c.rarity == r)
            if count:
                print(f"    {RARITY_EMOJI[r]} {RARITY_NAMES[r]:12s}: {count}")
        events = sum(1 for c in deck if c.card_type == 'Event')
        print(f"    Events:         {events}")
        total = sum(c.value for c in deck)
        print(f"    Total value:    ${total:.2f}")
        if valid:
            print(f"  {clr('Deck is VALID!', C.GREEN)}")
        else:
            for e in errors:
                print(f"  {clr(e, C.RED)}")
    elif choice == '2':
        deck = DeckBuilder.build_starter_deck(card_pool)
        valid, errors = DeckBuilder.validate_deck(deck)
        print(f"\n  {clr('Starter Deck:', C.BOLD)}")
        print(f"  Size: {len(deck)} cards")
        for r in ['C', 'U', 'R', 'UR', 'L', 'SR']:
            count = sum(1 for c in deck if c.rarity == r)
            if count:
                print(f"    {RARITY_EMOJI[r]} {RARITY_NAMES[r]:12s}: {count}")
        total = sum(c.value for c in deck)
        print(f"    Total value:    ${total:.2f}")
        if valid:
            print(f"  {clr('Deck is VALID!', C.GREEN)}")
        else:
            for e in errors:
                print(f"  {clr(e, C.RED)}")
    elif choice == '3':
        deck = DeckBuilder.auto_build_deck(card_pool)
        valid, errors = DeckBuilder.validate_deck(deck)
        print(f"\n  Deck size: {len(deck)}")
        if valid:
            print(f"  {clr('Deck is VALID!', C.GREEN)}")
        else:
            print(f"  {clr('Deck is INVALID:', C.RED)}")
            for e in errors:
                print(f"    {clr(e, C.RED)}")


# =============================================================================
# SECTION 15 - ENTRY POINT
# =============================================================================

def main():
    try:
        launch_gui()
    except KeyboardInterrupt:
        print(f"\n\n  {clr('Game exited.', C.YELLOW)}")
        sys.exit(0)

if __name__ == "__main__":
    main()