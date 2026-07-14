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

import pygame
import pygame.gfxdraw

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


# ==============================================================================
# SECTION: EXCHANGE DUEL ENGINE (merged from ExchangeDuel.py)
# ==============================================================================

# ── Card for Duel Mode ───────────────────────────────────────────────────────

DUEL_ABILITIES = {
    'none': {'desc': 'No special ability', 'type': 'passive'},
    'insider_info': {'desc': 'Peek at 2 of opponent\'s face-down cards', 'type': 'active'},
    'hostile_takeover': {'desc': 'Force opponent to accept your next offer', 'type': 'active'},
    'market_lock': {'desc': 'Protect one of your cards from trades this round', 'type': 'active'},
    'margin_call': {'desc': 'Opponent must offer their highest value card next turn', 'type': 'active'},
    'pump_dump': {'desc': 'Temporarily inflate a card\'s displayed value by 50%', 'type': 'active'},
    'short_sell': {'desc': 'Bet against opponent\'s card - if they trade it, you profit extra', 'type': 'active'},
    'insider_trade': {'desc': 'Swap a card from your hand with one from your deck', 'type': 'active'},
    'market_crash': {'desc': 'Reduce all opponent card values by 20% for 1 round', 'type': 'active'},
    'golden_parachute': {'desc': 'If you lose a trade this round, gain $5 compensation', 'type': 'passive'},
    'poison_pill': {'desc': 'If opponent trades for this card, they lose $3', 'type': 'passive'},
    'blue_chip': {'desc': 'This card\'s value is locked - cannot be reduced by events', 'type': 'passive'},
    'junk_bond': {'desc': 'Value fluctuates ±30% each round', 'type': 'passive'},
    'leveraged_buyout': {'desc': 'Trade 2 of your cards for 1 of opponent\'s', 'type': 'active'},
    'dutch_auction': {'desc': 'Reveal all opponent face-down cards for 1 round', 'type': 'active'},
}

@dataclass
class DuelCard:
    """A card in the exchange duel."""
    name: str
    value: float
    rarity: str  # C, U, R, UR, L, SR
    ability: str  # key into DUEL_ABILITIES
    card_id: str
    year: str = ''
    composition: str = ''
    face_down: bool = False
    value_modifier: float = 1.0  # temporary modifier from abilities
    protected: bool = False  # market_lock
    shorted_by: Optional[int] = None  # player index who short-sold this
    ability_used: bool = False

    @property
    def display_value(self) -> float:
        return self.value * self.value_modifier

    @property
    def ability_desc(self) -> str:
        return DUEL_ABILITIES.get(self.ability, {}).get('desc', '')

    @property
    def ability_type(self) -> str:
        return DUEL_ABILITIES.get(self.ability, {}).get('type', 'passive')

    def can_use_ability(self) -> bool:
        return self.ability != 'none' and self.ability_type == 'active' and not self.ability_used

    def short_str(self) -> str:
        return f"[{self.rarity}] {self.name} ${self.display_value:.2f}"


def generate_duel_deck(seed_pool: list, deck_size: int = 20) -> List[DuelCard]:
    """Generate a duel deck from the existing card pool, converting to DuelCards.
    Values are scaled up for duel mode to make trades meaningful."""
    pool = seed_pool[:]
    # Filter for variety - prefer a mix of rarities
    by_rarity = {}
    for c in pool:
        by_rarity.setdefault(c.rarity, []).append(c)
    # Build a balanced deck: 8 commons, 5 uncommons, 3 rares, 2 UR, 1 L, 1 SR
    target_counts = {'C': 8, 'U': 5, 'R': 3, 'UR': 2, 'L': 1, 'SR': 1}
    selected = []
    for r, count in target_counts.items():
        avail = by_rarity.get(r, [])
        random.shuffle(avail)
        selected.extend(avail[:count])
    random.shuffle(selected)
    deck = []
    for i, card in enumerate(selected[:deck_size]):
        # Map original abilities to duel abilities
        duel_ab = 'none'
        orig_ab = card.ability
        # Assign utility abilities based on rarity
        if card.rarity in ('L', 'SR'):
            duel_ab = random.choice(['hostile_takeover', 'margin_call', 'leveraged_buyout', 'dutch_auction'])
        elif card.rarity == 'UR':
            duel_ab = random.choice(['insider_info', 'pump_dump', 'short_sell', 'market_crash'])
        elif card.rarity == 'R':
            duel_ab = random.choice(['market_lock', 'insider_trade', 'poison_pill', 'blue_chip'])
        elif card.rarity == 'U':
            duel_ab = random.choice(['golden_parachute', 'junk_bond', 'market_lock', 'none'])
        else:
            duel_ab = random.choice(['none', 'none', 'junk_bond'])

        # Scale value for duel mode: base value * 100 + rarity bonus
        rarity_mult = {'C': 1, 'U': 2, 'R': 5, 'UR': 10, 'L': 25, 'SR': 50}
        duel_value = max(card.value * 100, 1.0) * rarity_mult.get(card.rarity, 1)
        duel_value = round(duel_value, 2)
        dc = DuelCard(
            name=card.name,
            value=duel_value,
            rarity=card.rarity,
            ability=duel_ab,
            card_id=f"duel_{i}_{card.card_id}",
            year=card.year_range,
            composition=card.composition,
        )
        deck.append(dc)
    random.shuffle(deck)
    return deck


# ── Duel Player ──────────────────────────────────────────────────────────────

class DuelPlayer:
    """A player in the exchange duel."""
    def __init__(self, name: str, deck: List[DuelCard], is_ai: bool = False):
        self.name = name
        self.deck: List[DuelCard] = deck[:]
        self.hand: List[DuelCard] = []
        self.portfolio: List[DuelCard] = []  # cards on the board (face up)
        self.face_down: List[DuelCard] = []  # hidden cards on the board
        self.profit: float = 0.0
        self.is_ai = is_ai
        self.force_accept: bool = False  # hostile_takeover active
        self.margin_call: bool = False  # must offer highest card
        self.ability_used_this_round: bool = False
        self.leveraged_buyout_active: bool = False  # next trade +$5 bonus

    def draw(self, n: int = 1):
        for _ in range(n):
            if self.deck:
                self.hand.append(self.deck.pop(0))
            elif self.face_down:
                # Reshuffle face_down back into deck
                self.deck.extend(self.face_down[:])
                self.face_down.clear()
                random.shuffle(self.deck)
                if self.deck:
                    self.hand.append(self.deck.pop(0))

    def play_to_portfolio(self, card: DuelCard) -> bool:
        if card in self.hand:
            self.hand.remove(card)
            self.portfolio.append(card)
            return True
        return False

    def play_face_down(self, card: DuelCard) -> bool:
        if card in self.hand:
            self.hand.remove(card)
            card.face_down = True
            self.face_down.append(card)
            return True
        return False

    def total_value(self) -> float:
        return sum(c.display_value for c in self.portfolio + self.face_down + self.hand)


# ── Trade Offer ──────────────────────────────────────────────────────────────

@dataclass
class TradeOffer:
    """A trade offer from one player to another."""
    offerer_idx: int
    offered_cards: List[DuelCard]
    requested_cards: List[DuelCard]
    # Calculated values
    offered_value: float = 0.0
    requested_value: float = 0.0
    margin: float = 0.0  # profit for offerer if accepted

    def calc_values(self):
        self.offered_value = sum(c.display_value for c in self.offered_cards)
        self.requested_value = sum(c.display_value for c in self.requested_cards)
        self.margin = self.requested_value - self.offered_value


# ── Exchange Duel Game ───────────────────────────────────────────────────────

class ExchangeDuel:
    """The main duel game engine."""

    def __init__(self, p1: DuelPlayer, p2: DuelPlayer, target_profit: float = 50.0,
                 max_rounds: int = 15):
        self.players = [p1, p2]
        self.target_profit = target_profit
        self.max_rounds = max_rounds
        self.current_round = 1
        self.current_player_idx = 0
        self.game_over = False
        self.winner: Optional[DuelPlayer] = None
        self.current_offer: Optional[TradeOffer] = None
        self.log: List[str] = []
        self.ai_difficulty = 'medium'
        self.phase = 'setup'  # setup, draw, play, offer, respond, end_turn, game_over
        self.peeked_cards: Dict[int, List[int]] = {}  # player_idx -> list of face_down indices revealed
        self.dutch_auction_active: bool = False
        self.market_crash_target: Optional[int] = None  # player whose values are reduced
        self.market_crash_timer: int = 0

    @property
    def active_player(self) -> DuelPlayer:
        return self.players[self.current_player_idx]

    @property
    def responding_player(self) -> DuelPlayer:
        return self.players[1 - self.current_player_idx]

    def setup(self):
        """Initialize the duel: deal cards to both players."""
        for p in self.players:
            random.shuffle(p.deck)
            p.draw(5)
            # Play 3 cards face-down and 2 face-up as starting portfolio
            for _ in range(3):
                if p.hand:
                    p.play_face_down(p.hand[0])
            for _ in range(2):
                if p.hand:
                    p.play_to_portfolio(p.hand[0])
        self.phase = 'play'
        self.log.append(f"Round 1 begins! Target profit: ${self.target_profit:.0f}")

    def make_offer(self, offered: List[DuelCard], requested: List[DuelCard]) -> str:
        """Active player makes a trade offer."""
        player = self.active_player
        opponent = self.responding_player

        # Validate offered cards belong to player
        for c in offered:
            if c not in player.portfolio and c not in player.hand:
                return "Invalid: you don't own the offered cards."
        # Validate requested cards belong to opponent
        for c in requested:
            if c not in opponent.portfolio and c not in opponent.face_down:
                return "Invalid: opponent doesn't own the requested cards."
        # Check market_lock
        for c in requested:
            if c.protected:
                return f"Invalid: {c.name} is market-locked!"

        offer = TradeOffer(
            offerer_idx=self.current_player_idx,
            offered_cards=offered[:],
            requested_cards=requested[:],
        )
        offer.calc_values()
        self.current_offer = offer
        self.phase = 'respond'

        margin_str = f"+${offer.margin:.2f}" if offer.margin >= 0 else f"-${abs(offer.margin):.2f}"
        self.log.append(f"{player.name} offers {len(offered)} card(s) for {len(requested)} card(s) | Margin: {margin_str}")
        return f"Offer made: {', '.join(c.name for c in offered)} for {', '.join(c.name for c in requested)}"

    def accept_offer(self) -> str:
        """Responding player accepts the trade."""
        if not self.current_offer:
            return "No offer to accept."
        offer = self.current_offer
        player = self.players[offer.offerer_idx]
        opponent = self.players[1 - offer.offerer_idx]

        # Execute the trade
        profit = offer.margin  # profit for offerer

        # Check short_sell
        for c in offer.requested_cards:
            if c.shorted_by is not None:
                short_profit = c.display_value * 0.3
                self.players[c.shorted_by].profit += short_profit
                self.log.append(f"Short sell triggered! Player {c.shorted_by+1} gains ${short_profit:.2f}")
                c.shorted_by = None

        # Check poison_pill
        for c in offer.offered_cards:
            if c.ability == 'poison_pill':
                opponent.profit -= 3.0
                self.log.append(f"Poison Pill! {opponent.name} loses $3.00")

        # Check golden_parachute
        for c in offer.offered_cards:
            if c.ability == 'golden_parachute' and profit < 0:
                player.profit += 5.0
                self.log.append(f"Golden Parachute! {player.name} gains $5.00 compensation")

        # Move cards
        for c in offer.offered_cards:
            if c in player.portfolio:
                player.portfolio.remove(c)
            elif c in player.hand:
                player.hand.remove(c)
            c.face_down = False
            opponent.portfolio.append(c)

        for c in offer.requested_cards:
            if c in opponent.portfolio:
                opponent.portfolio.remove(c)
            elif c in opponent.face_down:
                opponent.face_down.remove(c)
            c.face_down = False
            player.portfolio.append(c)

        # Apply profit
        bonus = 0.0
        if player.leveraged_buyout_active:
            bonus = 5.0
            player.leveraged_buyout_active = False
            self.log.append(f"Leveraged Buyout bonus! +${bonus:.2f}")
        player.profit += profit + bonus
        self.log.append(f"Trade accepted! {player.name} profit: ${profit:.2f}" +
                        (f" +${bonus:.2f} bonus" if bonus > 0 else "") +
                        f" (Total: ${player.profit:.2f})")

        self.current_offer = None
        self.phase = 'play'
        self._check_win()
        return f"Trade accepted! Margin: ${profit:.2f}"

    def decline_offer(self) -> str:
        """Responding player declines the trade."""
        if not self.current_offer:
            return "No offer to decline."
        self.log.append(f"{self.responding_player.name} declined the trade.")
        self.current_offer = None
        self.phase = 'play'
        return "Trade declined."

    def use_ability(self, card: DuelCard, target: Optional[DuelCard] = None) -> str:
        """Use a card's active ability."""
        player = self.active_player
        opponent = self.responding_player

        if not card.can_use_ability():
            return "Ability already used or not activatable."
        if card not in player.portfolio and card not in player.hand:
            return "You don't own this card."

        ab = card.ability
        card.ability_used = True
        result = ""

        # Auto-select targets if not provided
        if ab == 'market_lock' and target is None:
            target = max(player.portfolio, key=lambda c: c.display_value) if player.portfolio else None
        elif ab == 'pump_dump' and target is None:
            target = max(player.portfolio, key=lambda c: c.display_value) if player.portfolio else None
        elif ab == 'short_sell' and target is None:
            target = max(opponent.portfolio, key=lambda c: c.display_value) if opponent.portfolio else None

        if ab == 'insider_info':
            # Peek at 2 of opponent's face-down cards
            face_down = opponent.face_down
            peek_count = min(2, len(face_down))
            peeked = random.sample(range(len(face_down)), peek_count) if face_down else []
            self.peeked_cards[self.current_player_idx] = peeked
            names = [face_down[i].name for i in peeked]
            result = f"Insider Info! Peeked at: {', '.join(names)}"

        elif ab == 'hostile_takeover':
            player.force_accept = True
            result = "Hostile Takeover! Your next offer will be auto-accepted."

        elif ab == 'market_lock':
            if target and target in player.portfolio:
                target.protected = True
                result = f"Market Lock! {target.name} is protected from trades."
            else:
                result = "Market Lock failed: no valid target."

        elif ab == 'margin_call':
            opponent.margin_call = True
            result = f"Margin Call! {opponent.name} must offer their highest value card next turn."

        elif ab == 'pump_dump':
            if target and target in player.portfolio:
                target.value_modifier = 1.5
                result = f"Pump & Dump! {target.name} display value inflated to ${target.display_value:.2f}"
            else:
                result = "Pump & Dump failed: no valid target."

        elif ab == 'short_sell':
            if target and target in opponent.portfolio:
                target.shorted_by = self.current_player_idx
                result = f"Short Sell! Betting against {target.name}. If traded, you profit 30% extra."
            else:
                result = "Short Sell failed: no valid target."

        elif ab == 'insider_trade':
            if player.deck:
                # Swap this card with top of deck
                if card in player.hand:
                    idx = player.hand.index(card)
                    old = player.hand.pop(idx)
                    player.deck.append(old)
                    new = player.deck.pop(0)
                    player.hand.append(new)
                    result = f"Insider Trade! Swapped {old.name} for {new.name} from deck."
                elif card in player.portfolio:
                    idx = player.portfolio.index(card)
                    old = player.portfolio.pop(idx)
                    player.deck.append(old)
                    new = player.deck.pop(0)
                    player.portfolio.append(new)
                    result = f"Insider Trade! Swapped {old.name} for {new.name} from deck."
                else:
                    result = "Insider Trade failed: card not found."
            else:
                result = "Insider Trade failed: deck is empty."

        elif ab == 'market_crash':
            self.market_crash_target = 1 - self.current_player_idx
            self.market_crash_timer = 1
            for c in opponent.portfolio + opponent.face_down:
                if c.ability != 'blue_chip':
                    c.value_modifier = max(c.value_modifier * 0.8, 0.1)
            result = f"Market Crash! {opponent.name}'s card values reduced 20%!"

        elif ab == 'leveraged_buyout':
            player.leveraged_buyout_active = True
            result = "Leveraged Buyout ready! Your next accepted trade gains +$5 bonus profit."

        elif ab == 'dutch_auction':
            self.dutch_auction_active = True
            result = f"Dutch Auction! All of {opponent.name}'s face-down cards revealed!"

        self.log.append(f"{player.name} used {ab}: {result}")
        return result

    def end_turn(self):
        """End the active player's turn."""
        # Reset temporary effects
        player = self.active_player
        player.force_accept = False
        player.ability_used_this_round = False
        player.leveraged_buyout_active = False

        # Reset pump_dump modifiers
        for c in player.portfolio:
            if c.value_modifier != 1.0 and c.ability != 'junk_bond':
                c.value_modifier = 1.0

        # Reset market_lock and short_sell
        for p in self.players:
            for c in p.portfolio + p.face_down:
                c.protected = False
                c.shorted_by = None

        # Reset dutch auction
        if self.dutch_auction_active:
            self.dutch_auction_active = False

        # Junk bond fluctuation
        for p in self.players:
            for c in p.portfolio + p.face_down:
                if c.ability == 'junk_bond':
                    c.value_modifier = random.uniform(0.7, 1.3)

        # Market crash timer
        if self.market_crash_timer > 0:
            self.market_crash_timer -= 1
            if self.market_crash_timer <= 0:
                opponent = self.players[self.market_crash_target]
                for c in opponent.portfolio + opponent.face_down:
                    if c.ability != 'blue_chip':
                        c.value_modifier = 1.0
                self.market_crash_target = None

        self.peeked_cards.clear()

        # Switch turns
        self.current_player_idx = 1 - self.current_player_idx
        if self.current_player_idx == 0:
            self.current_round += 1
            self.log.append(f"--- Round {self.current_round} ---")
            for p in self.players:
                p.ability_used_this_round = False

        self.phase = 'play'

        if self.current_round > self.max_rounds:
            self.game_over = True
            self.winner = max(self.players, key=lambda p: p.profit)
            self.phase = 'game_over'
            self.log.append(f"Game Over! {self.winner.name} wins with ${self.winner.profit:.2f} profit!")

        self._check_win()

    def _check_win(self):
        """Check if any player has reached the target profit."""
        for p in self.players:
            if p.profit >= self.target_profit:
                self.game_over = True
                self.winner = p
                self.phase = 'game_over'
                self.log.append(f"{p.name} reached ${self.target_profit:.0f} profit and wins!")
                return

    def play_card_to_board(self, card: DuelCard, face_down: bool = False) -> str:
        """Play a card from hand to the board."""
        player = self.active_player
        if card not in player.hand:
            return "Card not in hand."
        if face_down:
            player.play_face_down(card)
            self.log.append(f"{player.name} placed a card face-down.")
            return f"Placed {card.name} face-down."
        else:
            player.play_to_portfolio(card)
            self.log.append(f"{player.name} played {card.name} (${card.display_value:.2f})")
            return f"Played {card.name} (${card.display_value:.2f})"

    # ── AI Logic ──────────────────────────────────────────────────────────────

    def ai_take_turn(self, player: DuelPlayer) -> List[str]:
        """AI takes its turn."""
        actions = []
        opponent = self.responding_player
        diff = self.ai_difficulty

        # Draw a card
        player.draw(1)
        actions.append(f"{player.name} drew a card.")

        # Play 1-2 cards to portfolio - mix of values for trading variety
        playable = [c for c in player.hand if c not in player.face_down]
        if diff == 'easy':
            random.shuffle(playable)
            to_play = playable[:random.randint(0, 2)]
        elif diff == 'medium':
            # Play a mix: one high, one low for trading flexibility
            random.shuffle(playable)
            to_play = playable[:random.randint(1, 2)]
        else:  # hard
            # Play lowest card (keep high cards for trading up)
            playable.sort(key=lambda c: c.display_value)
            to_play = playable[:2]

        for card in to_play:
            result = self.play_card_to_board(card, face_down=False)
            actions.append(result)

        # Use ability if beneficial
        for card in player.portfolio:
            if card.can_use_ability() and random.random() < (0.7 if diff == 'hard' else 0.4):
                target = None
                if card.ability in ('market_lock', 'pump_dump'):
                    target = max(player.portfolio, key=lambda c: c.display_value) if player.portfolio else None
                elif card.ability in ('short_sell',):
                    target = max(opponent.portfolio, key=lambda c: c.display_value) if opponent.portfolio else None
                result = self.use_ability(card, target)
                actions.append(result)
                break

        # Make a trade offer - find the best fair swap
        if player.portfolio and (opponent.portfolio or opponent.face_down):
            op_cards = opponent.portfolio[:]
            if self.dutch_auction_active or diff == 'hard':
                op_cards.extend(opponent.face_down[:])
            if not op_cards:
                actions.append(f"{player.name} has no valid trade targets.")
                self.end_turn()
                return actions

            # Strategy: find a fair swap where we profit slightly and opponent accepts
            # We want margin > 0 (we profit) but small enough that opponent accepts
            best_offer = None
            best_margin = -999
            # Determine the max margin the opponent will tolerate
            if diff == 'easy':
                max_opp_loss = 999  # easy AI accepts almost anything
            elif diff == 'medium':
                max_opp_loss = 10.0
            else:
                max_opp_loss = 5.0

            for my_card in player.portfolio:
                if my_card.protected:
                    continue
                for op_card in op_cards:
                    if op_card.protected:
                        continue
                    margin = op_card.display_value - my_card.display_value
                    # We want small positive margin within opponent's tolerance
                    if 0 < margin <= max_opp_loss:
                        # Pick the trade with the best margin within tolerance
                        if margin > best_margin:
                            best_offer = (my_card, op_card)
                            best_margin = margin

            # If no profitable trade found, try equal-value swap to cycle cards
            if not best_offer and diff != 'hard':
                for my_card in player.portfolio:
                    for op_card in op_cards:
                        if not op_card.protected and abs(op_card.display_value - my_card.display_value) < 0.01:
                            best_offer = (my_card, op_card)
                            best_margin = 0
                            break
                    if best_offer:
                        break

            # Margin call override: must offer highest card
            if player.margin_call:
                offer_card = max(player.portfolio, key=lambda c: c.display_value)
                request_card = max(op_cards, key=lambda c: c.display_value)
                player.margin_call = False
                best_offer = (offer_card, request_card)

            if best_offer:
                offer_card, request_card = best_offer
                result = self.make_offer([offer_card], [request_card])
                actions.append(result)

                # AI opponent auto-decides (in AI vs AI sim)
                if self.current_offer and opponent.is_ai:
                    offer = self.current_offer
                    opp_margin = -offer.margin  # profit for opponent (negative = loss)
                    if diff == 'easy':
                        accept = random.random() < 0.7
                    elif diff == 'medium':
                        accept = opp_margin >= -10.0
                    else:
                        accept = opp_margin >= -5.0

                    # Hostile takeover forces accept
                    if player.force_accept:
                        accept = True
                        player.force_accept = False

                    if accept:
                        result = self.accept_offer()
                        actions.append(f"{opponent.name}: {result}")
                    else:
                        result = self.decline_offer()
                        actions.append(f"{opponent.name}: {result}")

        # If AI made an offer to a human opponent, don't end turn yet — wait for response
        if self.current_offer and not opponent.is_ai:
            # Leave phase as 'respond', don't end turn
            actions.append(f"{player.name} is waiting for response to their offer...")
            return actions

        self.end_turn()
        actions.append(f"{player.name} ended turn. Profit: ${player.profit:.2f}")
        return actions

    def get_state_summary(self) -> dict:
        """Get a summary of the game state for UI."""
        return {
            'round': self.current_round,
            'max_rounds': self.max_rounds,
            'phase': self.phase,
            'active_player': self.current_player_idx,
            'target_profit': self.target_profit,
            'p1_profit': self.players[0].profit,
            'p2_profit': self.players[1].profit,
            'p1_hand': len(self.players[0].hand),
            'p2_hand': len(self.players[1].hand),
            'p1_portfolio': len(self.players[0].portfolio),
            'p2_portfolio': len(self.players[1].portfolio),
            'p1_facedown': len(self.players[0].face_down),
            'p2_facedown': len(self.players[1].face_down),
            'has_offer': self.current_offer is not None,
        }


# ==============================================================================
# SECTION: HISTORY CARDS SYSTEM (merged from HistoryCards.py)
# ==============================================================================

CARD_TYPES = ['Figure', 'Event', 'Conspiracy', 'Scandal', 'Organization', 'Policy']

ORGANIZATIONS = [
    'CIA', 'FBI', 'NSA', 'Federal Reserve', 'White House', 'Congress',
    'Pentagon', 'KGB', 'Mossad', 'MI6', 'UN', 'NATO', 'WHO',
    'Wall Street', 'Media', 'Big Pharma', 'Big Oil', 'Military-Industrial',
    'Mafia', 'Cartel', 'Freemasons', 'Skull & Bones', 'Bilderberg',
    'Trilateral Commission', 'CFR', 'DEA', 'ATF', 'DHS', 'None',
    # Global
    'Kremlin', 'British Crown', ' CCP', 'Israeli Govt', 'Mossad', 'IRA',
    'African Union', 'OPEC', 'SWIFT', 'BIS', 'IMF', 'World Bank',
    'EU', 'WTO', 'Interpol', 'Blackwater', 'Pinkerton', 'United Fruit',
    'East India Co', 'Vatican', 'Opus Dei', 'Triads', 'Yakuza', 'FARC',
    'Black Hand', 'Young Turks', 'Bolsheviks', 'SAVAK', 'Stasi', 'Gestapo',
]

@dataclass
class HistoryCard:
    card_id: str
    name: str
    card_type: str
    category: str
    year: str
    rarity: str
    organization: str
    power: int
    influence: int
    effect: str
    effect_desc: str
    flavor: str
    tags: List[str] = field(default_factory=list)
    region: str = 'US'

    def short_str(self):
        return f"[{self.rarity}] {self.name} ({self.year})"

def _hc(cid, name, ctype, cat, year, rarity, org, power, influence, effect, desc, flavor, tags=None, region='US'):
    return HistoryCard(cid, name, ctype, cat, year, rarity, org, power, influence, effect, desc, flavor, tags or [], region)

def get_cards_by_type(cards, t): return [c for c in cards if c.card_type == t]
def get_cards_by_org(cards, o): return [c for c in cards if c.organization == o]
def get_cards_by_category(cards, cat): return [c for c in cards if c.category == cat]
def get_cards_by_rarity(cards, r): return [c for c in cards if c.rarity == r]
def search_cards(cards, q):
    q = q.lower()
    return [c for c in cards if q in c.name.lower() or q in c.effect_desc.lower() or q in c.flavor.lower() or any(q in t for t in c.tags)]
def get_all_tags(cards):
    s = set()
    for c in cards: s.update(c.tags)
    return sorted(s)

# Card data loaded from separate function to keep file manageable
def create_history_set():
    return FIGURES + EVENTS + CONSPIRACIES + SCANDALS + ORGS + POLICIES


# ==============================================================================
# SECTION: HISTORY CARDS DATA (merged from HistoryCardsData.py)
# ==============================================================================

FIGURES = [
    _hc('FIG001','George Washington','Figure','domestic','1789-1797','C','White House',7,8,
       'Founding Father: +2 influence for all Policy cards on field.',
       'First President. Sets precedent for executive power.','First US President, warned against political parties and foreign entanglements.',['founding_father','president']),
    _hc('FIG002','Thomas Jefferson','Figure','domestic','1801-1809','C','White House',6,7,
       'Author of Independence: Once per game, nullify one Policy card.',
       'Third President, Louisiana Purchase author.','Wrote the Declaration of Independence. Doubled US territory.',['president','author']),
    _hc('FIG003','Abraham Lincoln','Figure','domestic','1861-1865','R','White House',8,9,
       'Emancipator: Destroy all cards tagged "confederacy". +3 power.',
       '16th President, Civil War leader.','Assassinated at Fords Theatre. Preserved the Union, ended slavery.',['president','civil_war']),
    _hc('FIG004','Theodore Roosevelt','Figure','domestic','1901-1909','R','White House',7,8,
       'Trust Buster: Remove one Organization cards influence for 2 turns.',
       '26th President, progressive reformer.','Nobel Peace Prize winner. Broke up monopolies, built Panama Canal.',['president','progressive']),
    _hc('FIG005','Woodrow Wilson','Figure','foreign','1913-1921','R','White House',6,7,
       'League Architect: +2 influence to all foreign affairs cards.',
       '28th President, led US into WWI.','Tried to create League of Nations, Congress blocked it.',['president','wwi']),
    _hc('FIG006','Franklin D. Roosevelt','Figure','domestic','1933-1945','UR','White House',9,9,
       'New Deal: Restore 3 cards from discard. Once per game.',
       '32nd President, 4 terms, WWII leader.','Led US through Great Depression and WWII. Died in office 1945.',['president','wwii','new_deal']),
    _hc('FIG007','JFK','Figure','domestic','1961-1963','L','White House',8,10,
       'Camelot: Reveal one face-down Conspiracy card. +5 influence.',
       '35th President, assassinated Dallas 1963.','Cuban Missile Crisis, Bay of Pigs, Moon program. Assassination debated.',['president','assassination','cold_war']),
    _hc('FIG008','Lyndon B. Johnson','Figure','domestic','1963-1969','R','White House',7,7,
       'Great Society: +2 power to all social Policy cards.',
       '36th President, escalated Vietnam.','Civil Rights Act, Medicare, Medicaid. Gulf of Tonkin.',['president','vietnam','civil_rights']),
    _hc('FIG009','Richard Nixon','Figure','domestic','1969-1974','UR','White House',7,6,
       'Tricky Dick: Steal one opponent card face-down. Scandal cards double vs you.',
       '37th President, resigned over Watergate.','Only president to resign. Opened China. Watergate.',['president','watergate','scandal']),
    _hc('FIG010','Henry Kissinger','Figure','foreign','1969-1977','UR','White House',6,9,
       'Realpolitik: Swap one foreign card with opponent. +3 influence.',
       'National Security Advisor, Secretary of State.','Nobel Peace Prize (controversial). Linked to Chile, Bangladesh coups.',['diplomat','cold_war','controversial']),
    _hc('FIG011','Ronald Reagan','Figure','foreign','1981-1989','UR','White House',8,8,
       'Star Wars: Negate one nuclear card. +2 power to military cards.',
       '40th President, Cold War endgame.','Iran-Contra scandal. SDI missile defense. Berlin Wall speech.',['president','cold_war','iran_contra']),
    _hc('FIG012','George H.W. Bush','Figure','foreign','1989-1993','R','CIA',7,8,
       'CIA Veteran: Peek at opponents hand. Once per game.',
       '41st President, former CIA Director.','Gulf War, Panama invasion. Deep intelligence ties.',['president','cia','gulf_war']),
    _hc('FIG013','Bill Clinton','Figure','domestic','1993-2001','R','White House',6,6,
       'Slick Willie: Negate one Scandal card per turn.',
       '42nd President, impeached not convicted.','Balanced budget, NAFTA. Lewinsky scandal, impeachment.',['president','scandal','impeachment']),
    _hc('FIG014','George W. Bush','Figure','foreign','2001-2009','UR','White House',6,7,
       'War on Terror: All military cards +3 power for 3 turns.',
       '43rd President, 9/11, Iraq War.','Patriot Act, Afghanistan, Iraq WMD claims. Election 2000.',['president','911','iraq_war']),
    _hc('FIG015','Barack Obama','Figure','domestic','2009-2017','R','White House',6,7,
       'Hope & Change: Nullify one racial/social Scandal card.',
       '44th President, first African American.','ACA, Osama bin Laden raid. Drone warfare expanded.',['president','aca','drones']),
    _hc('FIG016','Donald Trump','Figure','domestic','2017-2021','UR','White House',7,6,
       'MAGA: Double power of domestic cards. Risk: Media cards triple vs you.',
       '45th President, businessman, impeached twice.','Trade wars, border wall, COVID. Two impeachments, acquitted.',['president','impeachment','populist']),
    _hc('FIG017','J. Edgar Hoover','Figure','intelligence','1924-1972','UR','FBI',8,10,
       'The Files: Blackmail any Figure card. Control it for 2 turns.',
       'FBI Director for 48 years.','Kept secret files on politicians, MLK, presidents. Never resigned.',['fbi','blackmail','surveillance']),
    _hc('FIG018','Allen Dulles','Figure','intelligence','1953-1961','UR','CIA',7,9,
       'Regime Change: Remove one foreign Figure card. Once per game.',
       'First civilian CIA Director.','Bay of Pigs, coups in Iran and Guatemala. JFK fired him.',['cia','coups','cold_war']),
    _hc('FIG019','Robert McNamara','Figure','military','1961-1968','R','Pentagon',6,7,
       'Body Count: +2 power to military cards. Risk: -1 influence per turn.',
       'Secretary of Defense, Vietnam architect.','Later admitted Vietnam mistakes. Fog of War documentary.',['vietnam','pentagon']),
    _hc('FIG020','Oliver North','Figure','intelligence','1981-1987','R','NSA',5,6,
       'Iran-Contra: Trade cards secretly. Risk: Scandal.',
       'NSC staff, Iran-Contra figure.','Sold arms to Iran, funded Contras. Convicted, overturned.',['iran_contra','scandal','nsa']),
    _hc('FIG021','Winston Churchill','Figure','foreign','1940-1945','UR','None',8,9,
       'Iron Curtain: +3 influence to all allied foreign cards.',
       'UK Prime Minister, WWII leader.','Gallipoli, WWII savior, Cold War phrase-maker.',['wwii','uk','cold_war'],'UK'),
    _hc('FIG022','Fidel Castro','Figure','foreign','1959-2008','UR','None',7,8,
       'Revolution: Convert one domestic card to your side. Once per game.',
       'Cuban leader, 49 years in power.','Bay of Pigs survivor, Missile Crisis. CIA assassination attempts.',['cuba','cold_war','revolution'],'Cuba'),
    _hc('FIG023','Saddam Hussein','Figure','foreign','1979-2003','UR','None',7,6,
       'Iron Fist: +4 power but -2 influence. Opponent gains Scandal card.',
       'Iraq dictator, executed 2006.','US ally vs Iran, then enemy. WMD claims, 2003 invasion.',['iraq','dictator'],'Iraq'),
    _hc('FIG024','Osama bin Laden','Figure','foreign','1988-2011','L','None',9,8,
       'Terror Mastermind: Destroy 2 cards on entry. Both lose 3 influence.',
       'Al-Qaeda founder, 9/11 architect.','CIA-funded mujahideen origins. Killed Abbottabad 2011.',['al_qaeda','911','cia'],'Global'),
    _hc('FIG025','Nikita Khrushchev','Figure','foreign','1953-1964','UR','KGB',7,8,
       'Shoe Banger: Opponent discards 1 card or loses 2 influence.',
       'Soviet leader, Cuban Missile Crisis.','De-Stalinization, Berlin crisis, shoe-banging UN.',['soviet','cold_war','missile_crisis'],'USSR'),
    _hc('FIG026','Vladimir Putin','Figure','foreign','2000-present','UR','KGB',8,9,
       'KGB Playbook: Steal one face-down card. +2 to Conspiracy cards.',
       'Russian President, former KGB.','Poisonings, election interference, Crimea.',['russia','kgb','interference'],'Russia'),
    _hc('FIG027','Mao Zedong','Figure','foreign','1949-1976','L','None',9,8,
       'Cultural Revolution: Destroy all domestic Policy cards. Both lose 3 power.',
       'Chairman of China, 27 years.','Great Leap Forward famine, Cultural Revolution. 40M+ deaths.',['china','communist','revolution'],'China'),
    _hc('FIG028','Ho Chi Minh','Figure','foreign','1945-1969','R','None',7,7,
       'National Liberation: +3 power vs all foreign military cards.',
       'Vietnamese revolutionary leader.','Defeated France and US. Unified Vietnam.',['vietnam','revolutionary'],'Vietnam'),
    _hc('FIG029','Nelson Mandela','Figure','social','1994-1999','UR','None',7,9,
       'Reconciliation: Nullify all racial Scandal cards. +4 influence.',
       'First black South African President.','27 years imprisoned. Nobel Peace Prize. Apartheid end.',['apartheid','nobel'],'South Africa'),
    _hc('FIG030','Margaret Thatcher','Figure','foreign','1979-1990','R','None',7,7,
       'Iron Lady: +2 power to economic cards. Negate one socialist Policy.',
       'UK Prime Minister, Falklands, privatization.','Close Reagan ally. Miners strike. Austerity.',['uk','conservative','cold_war'],'UK'),
    _hc('FIG031','Alexander Hamilton','Figure','domestic','1789-1804','U','Federal Reserve',6,7,
       'Central Banker: +2 influence to all economic cards. First Treasury Secretary.','Built US financial system.','Killed by Burr in duel. $10 bill face. Federalist Papers.',['founding_father','treasury','duel']),
    _hc('FIG032','Benjamin Franklin','Figure','domestic','1776-1790','U','None',6,8,
       'Diplomat: +3 influence to all foreign Policy cards. Negate one Scandal.','Founding father, inventor, diplomat.','Negotiated French alliance. Electricity, bifocals, almanac.',['founding_father','diplomat','inventor']),
    _hc('FIG033','John Adams','Figure','domestic','1797-1801','C','White House',5,6,
       'Founding Lawyer: +1 influence to all Policy cards.','Second President, Alien & Sedition Acts.','Defended British soldiers after Boston Massacre.',['founding_father','president','lawyer']),
    _hc('FIG034','Andrew Jackson','Figure','domestic','1829-1837','R','White House',7,5,
       'Indian Killer: Remove all cards tagged "native". +3 power.','7th President, Trail of Tears.','Killed Bank of US. Duel survivor. Populist.',['president','trail_of_tears','populist']),
    _hc('FIG035','Ulysses S. Grant','Figure','domestic','1869-1877','R','Pentagon',7,5,
       'Union General: +3 power to all military cards. Destroy confederacy cards.','Civil War victor, 18th President.','Alcoholism, corruption in cabinet. Brilliant military mind.',['civil_war','general','president']),
    _hc('FIG036','J.P. Morgan','Figure','economic','1890-1913','UR','Wall Street',7,9,
       'Banker: +3 influence to economic cards. Bail out: restore 2 cards from discard.','Financier, industrial consolidation.','Bailed out US government twice. Created US Steel, GE.',['wall_street','banker','monopoly']),
    _hc('FIG037','John D. Rockefeller','Figure','economic','1870-1911','UR','Big Oil',7,8,
       'Oil Monopoly: +2 power to Big Oil cards. +1 card per turn.','Standard Oil, first billionaire.','Controlled 90% of US oil. Sherman Anti-Trust broke it up.',['oil','monopoly','billionaire']),
    _hc('FIG038','Andrew Carnegie','Figure','economic','1880-1919','R','Wall Street',6,7,
       'Steel Magnate: +2 influence to economic cards. Give 1 card to opponent for +2 power.','Steel empire, philanthropist.','Sold to JP Morgan. Gave away 90% of wealth. Libraries.',['steel','philanthropy','gilded_age']),
    _hc('FIG039','Teddy Roosevelt Jr.','Figure','military','1917-1918','U','Pentagon',5,4,
       'Rough Rider: +2 power to military cards. Once per game: lead the charge.','TR\'s son, Medal of Honor WWII.','Oldest man on D-Day at 56. Died in France.',['wwii','medal_of_honor','roosevelt']),
    _hc('FIG040','Douglas MacArthur','Figure','military','1930-1951','UR','Pentagon',8,7,
       'Emperor: +3 power to all Pacific theater cards. Risk: insubordination.','WWII Pacific, Korea, Japan rebuild.','Fired by Truman for defying orders. "Old soldiers never die."',['wwii','korea','japan'],'Japan'),
    _hc('FIG041','George Patton','Figure','military','1942-1945','R','Pentagon',8,5,
       'Old Blood and Guts: +4 power to military cards. Risk: -2 influence.','WWII tank commander.','Slapping incident. Died in car crash 1945. Possible assassination?',['wwii','tanks','controversial']),
    _hc('FIG042','Dwight Eisenhower','Figure','domestic','1953-1961','R','White House',7,8,
       'Supreme Commander: +2 power to all military. Warning: MIC gains +2 influence.','34th President, WWII European commander.','Warned of military-industrial complex in farewell.',['president','wwii','military_industrial']),
    _hc('FIG043','MLK Jr.','Figure','social','1955-1968','UR','None',6,10,
       'Dream: +4 influence to all social cards. Nullify all racial Scandal cards.','Civil rights leader, "I Have a Dream."','FBI surveilled, harassed. Assassinated Memphis 1968.',['civil_rights','assassination','mlk']),
    _hc('FIG044','Malcolm X','Figure','social','1952-1965','R','None',7,7,
       'By Any Means: +3 power to social cards. Risk: Media cards double vs you.','Civil rights, Black empowerment.','Nation of Islam split. Assassinated 1965. FBI COINTELPRO target.',['civil_rights','assassination','black_power']),
    _hc('FIG045','Robert F. Kennedy','Figure','domestic','1961-1968','R','White House',7,8,
       'Bobby: +2 influence to social cards. Reveal 1 Conspiracy card.','JFK\'s brother, AG, Senator.','Assassinated 1968 LA, after winning primary. Sirhan Sirhan.',['assassination','rfk','civil_rights']),
    _hc('FIG046','Cesar Chavez','Figure','social','1962-1993','U','None',5,6,
       'Labor Leader: +2 influence to social Policy. Boycott: opponent loses 1 card/turn.','Farm worker labor rights, UFW.','Grape boycott, Delano strike. Fastings.',['labor','civil_rights','boycott']),
    _hc('FIG047','Daniel Ellsberg','Figure','intelligence','1971','R','None',5,7,
       'Whistleblower: Reveal all government face-down cards. Risk: Espionage charges.','Leaked Pentagon Papers.','Trial dismissed due to government misconduct. Nixon plumbers.',['whistleblower','pentagon_papers','vietnam']),
    _hc('FIG048','Mark Felt (Deep Throat)','Figure','intelligence','1972-1974','R','FBI',6,7,
       'Insider: Reveal 1 face-down card per turn. +2 to Scandal cards.','FBI #2, Watergate source.','Denied until 2005. Woodward and Bernstein contact.',['fbi','watergate','whistleblower']),
    _hc('FIG049','Edward Snowden','Figure','intelligence','2013','UR','NSA',6,9,
       'The Leak: All face-down cards revealed permanently. NSA loses 5 influence.','NSA contractor, mass surveillance whistleblower.','Exiled in Russia. Charged under Espionage Act.',['nsa','whistleblower','surveillance'],'Russia'),
    _hc('FIG050','Julian Assange','Figure','intelligence','2006-present','UR','None',6,8,
       'Publisher: Reveal 3 face-down cards. Risk: Legal persecution.','WikiLeaks founder.','Ecuadorian embassy asylum 7 years. Extradition battles.',['wikileaks','whistleblower','press'],'UK'),
    _hc('FIG051','Che Guevara','Figure','foreign','1955-1967','R','None',7,7,
       'Revolutionary: +3 power to all revolutionary cards. Convert one card.','Argentine revolutionary, Cuban Revolution.','CIA-backed Bolivian execution. T-shirt icon.',['revolution','cuba','cia'],'Cuba'),
    _hc('FIG052','Augusto Pinochet','Figure','foreign','1973-1990','UR','CIA',7,5,
       'Dictator: +4 power. -3 influence. Risk: Human rights Scandals triple.','Chilean dictator, CIA-backed coup.','Operation Condor. 40K+ killed/tortured. Never tried.',['dictator','cia','condor'],'Chile'),
    _hc('FIG053','Shah of Iran','Figure','foreign','1953-1979','R','CIA',6,6,
       'Puppet King: +2 influence to foreign cards. Risk: Revolution cards triple vs you.','US-installed Iranian monarch.','SAVAK secret police. Overthrown 1979. CIA blowback.',['iran','cia','puppet'],'Iran'),
    _hc('FIG054','Manuel Noriega','Figure','foreign','1983-1989','R','CIA',6,5,
       'CIA Asset: +2 to intelligence cards. Risk: Drug Scandal cards double.','Panamanian dictator, former CIA informant.','US invaded 1989. Drug trafficking. Jailed in US, France, Panama.',['cia','drugs','dictator'],'Panama'),
    _hc('FIG055','Slobodan Milosevic','Figure','foreign','1989-2000','R','None',6,4,
       'Butcher of Balkans: +3 power. Risk: War crime cards triple.','Serbian leader, Yugoslav wars.','Genocide, ethnic cleansing. Died at Hague before verdict.',['war_crime','yugoslavia','genocide'],'Serbia'),
    _hc('FIG056','Saddam Hussein (Ally Era)','Figure','foreign','1980-1988','R','CIA',6,6,
       'US Ally: +2 power when paired with CIA cards. Risk: Later betrayal.','US supported Iraq vs Iran.','Rumsfeld handshake 1983. Chemical weapons use ignored.',['iraq','cia','iran_iraq_war'],'Iraq'),
    _hc('FIG057','Muammar Gaddafi (Ally Era)','Figure','foreign','2003-2011','U','None',5,5,
       'Rehabilitated: +2 influence to economic cards. Risk: NATO betrayal.','Gaddafi after giving up WMD.','Blair deal, oil contracts. Then NATO ousted him 2011.',['libya','nato','betrayal'],'Libya'),
    _hc('FIG058','Kim Jong-il','Figure','foreign','1994-2011','R','None',6,5,
       'Dear Leader: +3 power. -2 influence. Nuclear cards +2.','North Korean dictator.','Famine, prison camps, nuclear program. Succession drama.',['north_korea','dictator','nuclear'],'North Korea'),
    _hc('FIG059','Bashar al-Assad','Figure','foreign','2000-present','R','None',6,5,
       'Chemical Bashar: +3 power. Risk: War crime cards triple. Russian protection.','Syrian dictator.','Chemical weapons, barrel bombs. Russian/ Iranian backing.',['syria','chemical','war_crime'],'Syria'),
    _hc('FIG060','Vladimir Lenin','Figure','foreign','1917-1924','UR','KGB',8,8,
       'Revolution: Destroy all domestic Policy cards. +3 power to communist cards.','Soviet founder, Bolshevik Revolution.','German train, sealed. Red Terror. Created USSR.',['soviet','revolution','communist'],'USSR'),
    _hc('FIG061','Joseph Stalin','Figure','foreign','1924-1953','L','KGB',10,7,
       'Great Purge: Destroy 4 cards. Both lose 5 influence. Terror cards +5 power.','Soviet dictator, 20M+ dead.','Gulags, Holodomor famine, purges. WWII ally then Cold War.',['soviet','dictator','purge'],'USSR'),
    _hc('FIG062','Leon Trotsky','Figure','foreign','1917-1940','R','None',7,6,
       'Permanent Revolution: +3 power to revolutionary cards. Assassinated.','Bolshevik, exiled by Stalin.','Ice axe assassination in Mexico by Soviet agent.',['soviet','revolution','assassination'],'Mexico'),
    _hc('FIG063','Mikhail Gorbachev','Figure','foreign','1985-1991','UR','None',6,8,
       'Glasnost: Reveal all face-down cards. +3 influence. Risk: USSR collapses.','Soviet reformer, perestroika.','Nobel Peace Prize. USSR dissolved 1991.',['soviet','reform','cold_war'],'USSR'),
    _hc('FIG064','Boris Yeltsin','Figure','foreign','1991-1999','R','None',5,5,
       'The Drunkard: -2 influence. +1 power. Risk: Economic cards lose 2 power.','First Russian President.','Oligarch privatization, constitutional crisis, Chechen war.',['russia','oligarch','chaos'],'Russia'),
    _hc('FIG065','Angela Merkel','Figure','foreign','2005-2021','R','None',6,8,
       'Iron Chancellor: +2 influence to all European cards. Negate one economic Event.','German Chancellor, 16 years.','Refugee crisis, Eurozone, Nord Stream. Scientist turned politician.',['germany','eu','refugees'],'Germany'),
    _hc('FIG066','Emmanuel Macron','Figure','foreign','2017-present','U','None',5,6,
       'Centrist: +2 influence to economic cards. Risk: Protest cards double.','French President, banker.','Yellow vest protests, pension reform, EU integration.',['france','eu','centrist'],'France'),
    _hc('FIG067','Narendra Modi','Figure','foreign','2014-present','R','None',6,6,
       'Hindu Nationalist: +3 power. Risk: Religious conflict cards double.','Indian Prime Minister.','Gujarat riots controversy. Kashmir revocation.',['india','nationalist','hindu'],'India'),
    _hc('FIG068','Benjamin Netanyahu','Figure','foreign','1996-present','UR','Mossad',7,8,
       'Bibi: +3 power to all Mossad cards. +2 influence to intelligence.','Israeli PM, longest serving.','Corruption charges, Gaza wars, US Congress speech.',['israel','mossad','corruption'],'Israel'),
    _hc('FIG069','Yasser Arafat','Figure','foreign','1969-2004','R','None',6,7,
       'Palestinian Leader: +2 power vs all Israeli cards. Nobel Peace Prize.','PLO chairman, Palestinian cause.','Oslo Accords. Intifadas. Died 2004, poisoning suspected.',['palestine','plo','nobel'],'Palestine'),
    _hc('FIG070','Nelson Rockefeller','Figure','domestic','1974-1977','U','Wall Street',5,6,
       'Vice President: +2 influence to economic cards. Trilateral Commission member.','41st VP, Rockefeller family.','Bilderberg attendee. Three Mile Island during tenure.',['rockefeller','vp','trilateral']),
    _hc('FIG071','Henry Wallace','Figure','domestic','1941-1945','U','None',5,5,
       'Progressive VP: +2 influence to social Policy. Risk: Communist sympathy allegations.','FDR\'s VP, progressive.','Replaced by Truman. Ran Progressive Party 1948.',['progressive','new_deal','socialist']),
    _hc('FIG072','Barry Goldwater','Figure','domestic','1964','U','None',5,5,
       'Mr. Conservative: +2 power to military cards. Extremism defense.','1964 GOP nominee, libertarian conservative.','Lost to LBJ in landslide. Father of modern conservatism.',['conservative','libertarian','gop']),
    _hc('FIG073','George Soros','Figure','economic','1970-present','UR','Wall Street',6,9,
       'The Speculator: +3 influence to economic cards. Risk: Conspiracy cards double.','Billionaire investor, philanthropist.','Broke the Bank of England. Open Society. Right-wing target.',['soros','speculator','philanthropy']),
    _hc('FIG074','Koch Brothers','Figure','economic','1980-present','UR','Wall Street',6,8,
       'Dark Money: +2 influence to Organization cards. Negate one environmental Policy.','Billionaire political donors.','Climate denial funding, libertarian think tanks, Super PACs.',['koch','oil','dark_money']),
    _hc('FIG075','Rupert Murdoch','Figure','social','1980-present','UR','Media',6,9,
       'Media Mogul: +3 influence to all Media cards. Control narrative.','Fox News, Wall Street Journal owner.','Phone hacking scandal. Political kingmaker.',['media','fox','mogul']),
    _hc('FIG076','Jeffrey Epstein','Figure','social','2008-2019','L','None',7,10,
       'Blackmailer: Control any Figure card. Reveal all face-down. Risk: Death.','Financier, sex trafficker.','Connected to presidents, royals, CEOs. Died in jail, cameras off.',['epstein','blackmail','trafficking']),
    _hc('FIG077','James Madison','Figure','domestic','1809-1817','C','White House',5,6,
       'Constitution: +2 influence to all Policy cards. Father of Bill of Rights.','4th President, War of 1812.','Federalist Papers author. Dolly Madison saved art.',['founding_father','president','constitution']),
    _hc('FIG078','John Quincy Adams','Figure','domestic','1825-1829','C','None',5,6,
       'Diplomat President: +1 influence to foreign Policy. Anti-slavery congressman.','6th President, son of John Adams.','Amistad case Supreme Court argument. Died in Congress.',['founding_father','president','diplomat']),
    _hc('FIG079','William McKinley','Figure','domestic','1897-1901','U','White House',6,5,
       'Imperialist: +2 power to all foreign territorial cards. Assassinated.','25th President, Spanish-American War.','Annexed Hawaii, Philippines, Puerto Rico. Shot by anarchist.',['president','imperialism','assassination']),
    _hc('FIG080','Warren Harding','Figure','domestic','1921-1923','U','White House',4,4,
       'Corrupt: +1 card from discard. Risk: Scandal cards +2 power vs you.','29th President, Teapot Dome.','Poker cabinet. Mistress in White House. Died in office.',['president','corruption','teapot_dome']),
    _hc('FIG081','Calvin Coolidge','Figure','domestic','1923-1929','U','White House',4,5,
       'Silent Cal: +2 influence to economic cards. Small government.','30th President, laissez-faire.','"The business of America is business." Roaring Twenties.',['president','conservative','economic']),
    _hc('FIG082','Herbert Hoover','Figure','domestic','1929-1933','U','White House',4,4,
       'Depression: Economic cards -2 power. Risk: Social cards +2 vs you.','31st President, Great Depression start.','Bonus Army crushed. Smoot-Hawley tariff. One-term.',['president','depression','failure']),
    _hc('FIG083','Harry Truman','Figure','domestic','1945-1953','R','White House',7,6,
       'The Buck Stops: +2 power to military. Once per game: drop the bomb.','33rd President, WWII end, Korea.','Hiroshima/Nagasaki decision. Marshall Plan. Fired MacArthur.',['president','wwii','nuclear']),
    _hc('FIG084','Jimmy Carter','Figure','domestic','1977-1981','U','White House',5,6,
       'Human Rights: +2 influence to social cards. Risk: Iran Hostage Crisis.','39th President, peanut farmer.','Camp David Accords. Energy crisis. Habitat for Humanity.',['president','human_rights','peace']),
    _hc('FIG085','Gerald Ford','Figure','domestic','1974-1977','U','White House',4,5,
       'Pardon: Negate one Scandal card. Nixon pardoned. Risk: -2 influence.','38th President, only unelected.','Pardoned Nixon. Mayaguez incident. Two assassination attempts.',['president','pardon','nixon']),
    _hc('FIG086','Colin Powell','Figure','military','1989-2004','R','Pentagon',7,7,
       'The Case: +3 power to military cards. Risk: WMD claims proven false.','Sec of State, UN WMD presentation.','Iraq WMD presentation was false. Regrets it. My Lai cover-up role.',['military','iraq','wmd']),
    _hc('FIG087','Condoleezza Rice','Figure','foreign','2001-2009','R','White House',6,7,
       'WMD Pusher: +2 influence to foreign Policy. Risk: Iraq War cards double.','NSA then Sec of State under GWB.','"Mushroom cloud" warning. Russia expert. Chevron board.',['bush','iraq','russia']),
    _hc('FIG088','Robert Mueller','Figure','intelligence','2001-2013','R','FBI',6,7,
       'The Investigator: +2 to Scandal cards. Reveal 1 face-down per turn.','FBI Director 12 years, Special Counsel.','9/11, anthrax, Mueller Report on Russian interference.',['fbi','mueller','russia']),
    _hc('FIG089','James Comey','Figure','intelligence','2013-2017','R','FBI',5,7,
       'The Letter: Reveal 1 face-down card. Risk: Backlash from both sides.','FBI Director, fired by Trump.','Clinton email letter Oct 2016. Memos. Trump investigation.',['fbi','comey','trump']),
    _hc('FIG090','Hillary Clinton','Figure','domestic','1993-2016','UR','White House',7,8,
       'Establishment: +2 influence to Organization cards. Risk: Scandal cards double.','First Lady, Senator, Sec of State, 2016 nominee.','Benghazi, emails, Clinton Foundation. Lost to Trump.',['clinton','establishment','scandal']),
    _hc('FIG091','Bernie Sanders','Figure','social','1981-present','R','None',6,8,
       'The Revolution: +3 influence to social Policy. +2 power vs Wall Street.','Senator, progressive icon.','2016/2020 primary challenges. Democratic socialist. Grassroots.',['progressive','socialist','grassroots']),
    _hc('FIG092','Ron Paul','Figure','domestic','1976-2013','U','None',5,6,
       'Liberty: +2 influence to economic cards. Negate one surveillance Policy.','Congressman, libertarian, gold standard.','Audit the Fed. 2008/2012 presidential runs. Internet grassroots.',['libertarian','audit_fed','constitution']),
    _hc('FIG093','John McCain','Figure','domestic','1983-2018','R','Pentagon',6,7,
       'Maverick: +2 power to military. Risk: Keating Five Scandal.','Senator, POW, 2008 GOP nominee.','Vietnam POW 5 years. Tortured. Thumb down on ACA repeal.',['vietnam','pow','maverick']),
    _hc('FIG094','Mitch McConnell','Figure','domestic','1985-present','R','Congress',5,8,
       'The Turtle: +3 influence to Congress. Negate one Policy from opponent.','Senate Majority Leader, GOP strategist.','SCOTUS blockade, tax cuts, impeachment acquittal. Power politics.',['congress','gop','strategist']),
    _hc('FIG095','Nancy Pelosi','Figure','domestic','1987-present','R','Congress',6,8,
       'The Gavel: +2 influence to Congress. Force one vote per turn.','Speaker of the House, first woman.','Impeached Trump twice. ACA passage. Torn speech.',['congress','speaker','democrat']),
    _hc('FIG096','Ruth Bader Ginsburg','Figure','domestic','1993-2020','UR','None',5,8,
       'Notorious RBG: +3 influence to social Policy. Negate one discriminatory Policy.','Supreme Court Justice, gender equality.','Liberal icon. Died before 2020 election. Barrett replaced her.',['scotus','gender','liberal']),
    _hc('FIG097','Antonin Scalia','Figure','domestic','1986-2016','UR','None',6,6,
       'Originalist: +2 influence to conservative Policy. Negate one social Policy.','Supreme Court Justice, conservative.','Heller gun rights. Bush v Gore. Died at ranch, pillow rumors.',['scotus','conservative','originalist']),
    _hc('FIG098','Alan Greenspan','Figure','economic','1987-2006','UR','Federal Reserve',6,8,
       'The Maestro: +2 influence to economic cards. Risk: Bubble cards double.','Fed Chairman 19 years.','Dot-com, housing bubbles. "Irrational exuberance." Ayn Rand friend.',['fed','economy','bubble']),
    _hc('FIG099','Ben Bernanke','Figure','economic','2006-2014','UR','Federal Reserve',6,7,
       'Helicopter Ben: +1 card per turn. Negate one economic crash Event.','Fed Chairman during 2008 crisis.','Quantitative easing, ZIRP. Bailouts. Studied Great Depression.',['fed','bailout','qe']),
    _hc('FIG100','Janet Yellen','Figure','economic','2014-present','UR','Federal Reserve',5,7,
       'The Data: +2 influence to economic cards. Negate one inflation Event.','Fed Chair, Treasury Sec, first woman.','Rate hikes, labor market focus. Inflation debates.',['fed','treasury','economy']),
    _hc('FIG101','Elon Musk','Figure','economic','2002-present','UR','None',7,8,
       'Disruptor: +3 power to economic cards. Risk: Media cards double vs you.','Tesla, SpaceX, X owner.','Government subsidies, Twitter purchase, free speech debates.',['tech','disruptor','twitter']),
    _hc('FIG102','Bill Gates','Figure','economic','1975-present','UR','None',6,8,
       'Philanthrocapitalist: +2 influence to Organization cards. WHO +2 power.','Microsoft founder, Gates Foundation.','Vaccine funding, climate, agriculture. Conspiracy target.',['tech','philanthropy','vaccines']),
    _hc('FIG103','Henry Ford','Figure','economic','1903-1947','R','None',7,6,
       'Assembly Line: +2 power to economic cards. Risk: Anti-semitism Scandal.','Ford Motor Company, Model T.','Anti-semitic publications. Hitler admired him. $5 day wage.',['ford','industrialist','antisemitism']),
    _hc('FIG104','Charles Lindbergh','Figure','social','1927-1974','R','None',6,6,
       'America First: +2 power to domestic cards. Risk: Nazi sympathy allegations.','Aviator, isolationist, America First Committee.','Baby kidnapping/murder. Nazi medals. Pre-war isolationism.',['isolationist','america_first','wwii']),
    # ── Global Political Figures ──
    _hc('FIG105','Ferdinand Marcos','Figure','foreign','1965-1986','UR','None',7,5,
       'Martial Law: +3 power. Risk: -3 influence. People Power cards triple.','Philippine dictator, 21 years in power.','Imelda shoes. US bases. Overthrown 1986. Hawaii exile.',['philippines','dictator','martial_law'],'Philippines'),
    _hc('FIG106','Deng Xiaoping','Figure','foreign','1978-1997','UR',' CCP',7,8,
       'Capitalist Road: +3 influence to economic cards. Risk: Tiananmen.','Reformer who opened China to markets.','Tiananmen Square 1989. "To get rich is glorious."',['china','reform','tiananmen'],'China'),
    _hc('FIG107','Xi Jinping','Figure','foreign','2012-present','UR',' CCP',8,8,
       'Emperor for Life: +3 power to all communist cards. Negate one reform Policy.','General Secretary, abolished term limits.','Belt and Road, Uyghur camps, Hong Kong crackdown.',['china','dictator','surveillance'],'China'),
    _hc('FIG108','Mahatma Gandhi','Figure','foreign','1915-1948','UR','None',5,10,
       'Nonviolence: Negate all military cards for 2 turns. +5 influence to social.','Indian independence leader, nonviolent resistance.','Assassinated 1948. Salt March. Inspired MLK, Mandela.',['india','nonviolence','assassination'],'India'),
    _hc('FIG109','Indira Gandhi','Figure','foreign','1966-1984','R','None',7,6,
       'Emergency: +3 power. Risk: -3 influence. Destroy 2 social cards.','PM of India, declared Emergency 1975.','Assassinated by Sikh bodyguards after Golden Temple raid.',['india','emergency','assassination'],'India'),
    _hc('FIG110','F.W. de Klerk','Figure','foreign','1989-1994','R','None',5,8,
       'Apartheid Ender: +3 influence to social. Negate racial Scandal cards. Risk: Right-wing backlash.','Last apartheid South African President. Nobel Peace Prize.','Freed Mandela. 1994 elections. NP disbanded.',['south_africa','nobel','apartheid'],'South Africa'),
    _hc('FIG111','Kim Il-sung','Figure','foreign','1948-1994','UR','None',7,5,
       'Eternal President: +3 power. Nuclear cards +2. Risk: Economic -3.','Founder of North Korea, Juche ideology.','Korean War started 1950. Cult of personality. Dynasty.',['north_korea','dictator','juche'],'North Korea'),
    _hc('FIG112','Pol Pot','Figure','foreign','1975-1979','L','None',9,3,
       'Year Zero: Destroy ALL cards. Both lose 10 influence. Reset board.','Khmer Rouge leader, 1.5M+ Cambodians killed.','Evacuated cities. Killing fields. UN tribunal.',['cambodia','genocide','communist'],'Cambodia'),
    _hc('FIG113','Augusto Sandino','Figure','foreign','1927-1934','R','None',6,7,
       'Sandinista: +3 power to revolutionary cards. Assassinated.','Nicaraguan guerrilla leader vs US occupation.','Killed by Somoza National Guard. Inspired FSLN.',['nicaragua','revolution','assassination'],'Nicaragua'),
    _hc('FIG114','Fulgencio Batista','Figure','foreign','1933-1959','R','None',6,4,
       'Dictator: +2 power to military. Risk: Revolution cards triple vs you.','Cuban dictator, US-backed, overthrown by Castro.','Mafia casinos. Corruption. Castro\'s revolution.',['cuba','dictator','us_backed'],'Cuba'),
    _hc('FIG115','Mohammad Reza Pahlavi','Figure','foreign','1953-1979','R','CIA',6,6,
       'Shah: +2 influence to economic. Risk: Revolution cards double.','US-installed Shah of Iran, SAVAK secret police.','White Revolution. Oil wealth. Overthrown 1979.',['iran','cia','puppet'],'Iran'),
    _hc('FIG116','Ruhollah Khomeini','Figure','foreign','1979-1989','UR','None',7,8,
       'Islamic Revolution: Destroy all US-backed cards. +3 to religious cards.','Supreme Leader of Iran, 1979 revolution.','Hostage crisis. Iran-Iraq War. Fatwa on Rushdie.',['iran','revolution','islamic'],'Iran'),
    _hc('FIG117','Rodrigo Duterte','Figure','foreign','2016-2022','UR','None',7,4,
       'Death Squads: +4 power. -3 influence. Destroy 2 social cards. Risk: ICC.','Philippian President, drug war killings.','Thousands killed. ICC investigation. China pivot.',['philippines','drug_war','dictator'],'Philippines'),
    _hc('FIG118','Muammar Gaddafi','Figure','foreign','1969-2011','UR','None',7,6,
       'Pan-African: +2 influence to African cards. Risk: NATO intervention.','Libyan dictator 42 years.','Pan Am 103 bombing. Killed by rebels 2011. Gold dinar plan?',['libya','dictator','oil'],'Libya'),
    _hc('FIG119','Hosni Mubarak','Figure','foreign','1981-2011','R','None',6,5,
       'Pharaoh: +2 power to military. Risk: Arab Spring cards triple.','Egyptian president 30 years.','Overthrown 2011. Emergency law. US ally.',['egypt','dictator','arab_spring'],'Egypt'),
    _hc('FIG120','Gamal Abdel Nasser','Figure','foreign','1956-1970','R','None',7,6,
       'Pan-Arabism: +3 power to revolutionary. +2 to Middle East cards.','Egyptian President, Suez Crisis, UAR.','Nationalized Suez Canal. Six-Day War disaster. Arab nationalism icon.',['egypt','revolution','arab_nationalism'],'Egypt'),
    _hc('FIG121','Anwar Sadat','Figure','foreign','1970-1981','R','None',5,7,
       'Peace with Israel: +3 influence to social. Negate one Middle East Event. Risk: Assassination.','Egyptian President, Nobel Peace Prize.','Camp David Accords. Assassinated by Islamic extremists 1981.',['egypt','nobel','assassination'],'Egypt'),
    _hc('FIG122','Charles de Gaulle','Figure','foreign','1958-1969','UR','None',7,8,
       'Free France: +3 influence to all European cards. Negate one occupation.','Leader of Free French, WWII, Fifth Republic.','Algeria war. NATO withdrawal. "Vive le Quebec libre."',['france','wwii','gaullist'],'France'),
    _hc('FIG123','Konrad Adenauer','Figure','foreign','1949-1963','R','None',6,7,
       'Father of Europe: +2 influence to EU cards. Economic +2 power.','First West German Chancellor, rebuilt Germany.','NATO, EEC founder. Reconciliation with France.',['germany','eu','cold_war'],'Germany'),
    _hc('FIG124','Francois Mitterrand','Figure','foreign','1981-1995','R','None',5,7,
       'Socialist: +2 influence to social Policy. Negate one conservative Policy.','French President, Socialist Party.','Maastricht Treaty. Vichy past controversy.',['france','socialist','eu'],'France'),
    _hc('FIG125','Silvio Berlusconi','Figure','foreign','1994-2011','R','None',6,5,
       'Media Mogul: +3 influence to Media cards. Risk: Scandal cards double.','Italian PM, media tycoon.','Bunga bunga parties. Tax fraud. Putin friend.',['italy','media','scandal'],'Italy'),
    _hc('FIG126','Viktor Orban','Figure','foreign','2010-present','R','None',6,6,
       'Illiberal Democracy: +3 power to domestic. EU -2 influence.','Hungarian PM, nationalist.','Anti-immigration, EU clashes. Media control.',['hungary','nationalist','eu'],'Hungary'),
    _hc('FIG127','Recep Erdogan','Figure','foreign','2003-present','UR','None',7,6,
       'Sultan: +3 power to military. Risk: -2 influence. Coup cards double.','Turkish President, former PM.','Kurdish conflict, coup attempt 2016, press crackdown.',['turkey','dictator','coup'],'Turkey'),
    _hc('FIG128','Mohammed bin Salman','Figure','foreign','2017-present','UR','None',7,7,
       'MBS: +3 power to economic. Risk: Scandal cards triple vs you.','Saudi Crown Prince, de facto ruler.','Khashoggi murder. Vision 2030. Oil price wars.',['saudi','oil','khashoggi'],'Saudi Arabia'),
    _hc('FIG129','Nicolae Ceausescu','Figure','foreign','1965-1989','R','None',6,4,
       'Conducator: +2 power. Risk: Revolution cards triple. Executed.','Romanian dictator, overthrown 1989.','Securitate. Orphanages. Shot on Christmas.',['romania','dictator','revolution'],'Romania'),
    _hc('FIG130','Lech Walesa','Figure','foreign','1980-1990','R','None',5,8,
       'Solidarity: +3 influence to social cards. Destroy one communist card.','Polish labor leader, Solidarity movement, President.','Nobel Peace Prize. Gdansk shipyard. Communist collapse.',['poland','solidarity','nobel'],'Poland'),
    _hc('FIG131','Mikhail Khodorkovsky','Figure','foreign','1995-2013','R','Kremlin',6,7,
       'Oligarch: +3 influence to economic. Risk: Putin destroys you.','Russian oil tycoon, jailed by Putin.','Yukos oil. 10 years prison. Exiled. Warned of kleptocracy.',['russia','oligarch','oil'],'Russia'),
    _hc('FIG132','Roman Abramovich','Figure','foreign','2000-present','U','Kremlin',5,6,
       'Oligarch Shield: +2 influence to economic. Risk: Sanctions.','Russian oligarch, Chelsea FC owner.','Putin ally. Sanctioned 2022. Yacht seized.',['russia','oligarch','sanctions'],'Russia'),
    _hc('FIG133','Aung San Suu Kyi','Figure','foreign','1988-present','UR','None',5,8,
       'Lady: +3 influence to social. Risk: Military cards double vs you.','Myanmar democracy icon, Nobel laureate.','House arrest 15 years. Rohingya defense controversy.',['myanmar','nobel','democracy'],'Myanmar'),
    _hc('FIG134','Robert Mugabe','Figure','foreign','1980-2017','UR','None',7,4,
       'Comrade Bob: +3 power. Risk: Economic -3. Destroy 2 economic cards.','Zimbabwe dictator 37 years.','Land seizures, hyperinflation. Grace Mugabe. Coup 2017.',['zimbabwe','dictator','hyperinflation'],'Zimbabwe'),
    _hc('FIG135','Idi Amin','Figure','foreign','1971-1979','R','None',7,2,
       'Butcher: +5 power. -5 influence. Destroy 3 social cards.','Ugandan dictator, 300K+ killed.','Expelled Asians. Ate opponents (rumored). Exiled Saudi.',['uganda','dictator','genocide'],'Uganda'),
    _hc('FIG136','Thomas Sankara','Figure','foreign','1983-1987','R','None',6,8,
       'African Che: +3 power to revolutionary. +2 to social. Risk: Assassination.','Burkina Faso revolutionary leader.','Renamed country. Vaccinated 2M. Killed by Blaise Compaore.',['burkina_faso','revolution','africa'],'Burkina Faso'),
    _hc('FIG137','Muhammad Ali','Figure','social','1960-1981','R','None',6,8,
       'The Greatest: +3 power vs military. Negate one draft Policy.','Boxer, conscientious objector, civil rights icon.','"No Viet Cong ever called me n-word." Stripped of title.',['ali','civil_rights','vietnam']),
    _hc('FIG138','Coco Chanel','Figure','economic','1910-1971','R','None',5,7,
       'Fashion Empire: +2 influence to economic. Risk: Nazi agent allegations.','French fashion designer, Nazi spy (declassified).','Abwehr Agent 7124. Lived at Ritz. Anti-semitism.',['france','nazi','fashion'],'France'),
    _hc('FIG139','Aristide Briand','Figure','foreign','1909-1932','U','None',4,7,
       'Peacemaker: +2 influence to foreign Policy. Negate one military Event.','French PM, Nobel Peace Prize, Locarno Treaties.','European unity advocate. Kellogg-Briand Pact.',['france','nobel','peace'],'France'),
    _hc('FIG140','Rasputin','Figure','foreign','1905-1916','UR','None',6,8,
       'Dark Influence: Control any Figure card. Risk: Assassination cards triple.','Russian mystic, influenced Tsar family.','Healed hemophilia. Drunk, debauched. Murdered by nobles.',['russia','mystic','romanov'],'Russia'),
    _hc('FIG141','Enver Hoxha','Figure','foreign','1944-1985','R','None',6,3,
       'Bunkers: +3 power to defense. -2 influence. Destroy 1 social card.','Albanian dictator, 750K bunkers built.','Isolated from USSR and China. No religion. Forced labor.',['albania','dictator','isolationist'],'Albania'),
    _hc('FIG142','Cecil Rhodes','Figure','foreign','1870-1902','UR','None',7,6,
       'Imperialist: +3 power to African cards. +2 to economic. Risk: -3 influence.','British imperialist, De Beers diamonds, Rhodesia.','Scholarship namesake. White supremacy. "From Cape to Cairo."',['rhodesia','diamonds','imperialism'],'UK'),
    _hc('FIG143','King Leopold II','Figure','foreign','1885-1908','UR','None',8,4,
       'Congo Butcher: +5 power. Destroy 3 African cards. -5 influence.','Belgian king, Congo Free State, 10M+ dead.','Hands cut off. Rubber quotas. International scandal.',['congo','genocide','colonialism'],'Belgium'),
    _hc('FIG144','Otto von Bismarck','Figure','foreign','1871-1890','UR','None',8,7,
       'Iron Chancellor: +3 power to military. +2 influence to European cards.','Unified Germany, "blood and iron."','Social insurance pioneer. Realpolitik. Dismissed by Wilhelm II.',['germany','unification','realpolitik'],'Germany'),
    _hc('FIG145','Garibaldi','Figure','foreign','1848-1882','R','None',6,7,
       'Unifier: +2 power to revolutionary. +2 influence to European cards.','Italian unification hero.','Red Shirts. "Roma o morte." Cavour alliance.',['italy','unification','revolution'],'Italy'),
    _hc('FIG146','Simon Bolivar','Figure','foreign','1810-1830','R','None',7,7,
       'El Libertador: +3 power to revolutionary cards. Liberate 3 territories.','South American independence leader.','Freed Venezuela, Colombia, Ecuador, Peru, Bolivia.',['bolivar','revolution','liberation'],'Venezuela'),
    _hc('FIG147','Toussaint Louverture','Figure','foreign','1791-1803','R','None',6,7,
       'Haitian Revolution: +3 power to revolutionary. Destroy all slavery cards.','Leader of Haitian slave revolt.','First Black republic. Died in French prison.',['haiti','revolution','slavery'],'Haiti'),
    _hc('FIG148','Maximilien Robespierre','Figure','foreign','1789-1794','R','None',7,5,
       'The Terror: Destroy 3 domestic cards. +3 power. Risk: Guillotine.','French revolutionary, Reign of Terror.','Executed his own allies. "Virtue without terror is impotent."',['france','revolution','terror'],'France'),
    _hc('FIG149','Napoleon Bonaparte','Figure','foreign','1799-1815','L','None',9,7,
       'Emperor: +4 power to military. +2 influence to European. Risk: Exile.','French emperor, conquered Europe.','Code Napoleon. Waterloo. Died St Helena 1821.',['france','emperor','waterloo'],'France'),
    _hc('FIG150','Duke of Wellington','Figure','foreign','1800-1852','UR','British Crown',7,7,
       'Iron Duke: +3 power to military. Negate one Napoleon card.','British general, defeated Napoleon at Waterloo.','PM twice. "Publish and be damned."',['uk','waterloo','general'],'UK'),
    _hc('FIG151','Lord Palmerston','Figure','foreign','1855-1865','R','British Crown',6,6,
       'Gunboat Diplomacy: +2 power to military. +2 influence to foreign.','British PM, imperialist.','Opium Wars. "Civis Romanus sum."',['uk','imperialism','opium'],'UK'),
    _hc('FIG152','Cornelius Vanderbilt','Figure','economic','1820-1877','UR','None',7,7,
       'Railroad Tycoon: +3 influence to economic. +2 to military transport.','Shipping and railroad magnate, $100M fortune.','Gibbons v Ogden. Grand Central Terminal. Started Vanderbilt University.',['railroad','shipping','gilded_age']),
    _hc('FIG153','JP Morgan Sr.','Figure','economic','1890-1913','UR','Wall Street',7,9,
       'Banker King: +3 influence to economic. Bailout: restore 3 cards.','Financier who bailed out US govt twice.','US Steel, GE. Panic of 1907. Died wealthy.',['wall_street','banker','monopoly']),
    _hc('FIG154','Nathan Rothschild','Figure','economic','1800-1836','UR','None',7,9,
       'Financier: +3 influence to economic. Peek at opponent hand.','Rothschild banking dynasty founder in London.','Waterloo fortune. "Buy when blood runs in streets."',['rothschild','banker','napoleon'],'UK'),
    _hc('FIG155','Jacob Rothschild','Figure','economic','1960-present','UR','None',6,8,
       'Modern Baron: +2 influence to economic. +2 to Organization cards.','Rothschild investment trust, Bilderberg attendee.','Conspiracy target. Philanthropy. Israel ties.',['rothschild','bilderberg','banker'],'UK'),
    _hc('FIG156','David Rockefeller','Figure','economic','1960-2017','UR','CFR',6,9,
       'Trilateral: +3 influence to Organization. Peek 2 opponent cards/turn.','Chase Manhattan CEO, CFR chairman, Bilderberg.','"Internationalist conspiracy" letter quote. Trilateral founder.',['rockefeller','cfr','trilateral']),
    _hc('FIG157','Zbigniew Brzezinski','Figure','foreign','1977-1981','UR','White House',6,8,
       'Grand Chessboard: +2 power to intelligence. +2 influence to foreign Policy.','Carter NSA, geopolitical strategist.','Afghan trap for Soviets. China normalization.',['cold_war','strategist','carter']),
    _hc('FIG158','Paul Volcker','Figure','economic','1979-1987','UR','Federal Reserve',6,7,
       'The Sledgehammer: +2 influence to economic. Negate one inflation Event.','Fed Chair, broke inflation with 20% rates.','Recession, recovery. "Keep at it." Plaza Accord.',['fed','inflation','economy']),
    _hc('FIG159','Christine Lagarde','Figure','economic','2011-present','UR','IMF',5,8,
       'IMF Chief: +2 influence to economic. Negate one debt crisis Event.','IMF Managing Director, ECB President.','First woman at IMF and ECB. France finance minister.',['imf','ecb','economy'],'France'),
    _hc('FIG160','Klaus Schwab','Figure','economic','1971-present','UR','None',5,8,
       'Great Reset: +2 influence to Organization. Reveal 2 face-down cards.','World Economic Forum founder, Davos.','"You will own nothing and be happy." Stakeholder capitalism.',['wef','davos','globalist'],'Switzerland'),
    _hc('FIG161','George H.W. Bush Sr.','Figure','intelligence','1976-present','L','CIA',8,9,
       'Deep State: +3 to CIA. Peek 3 cards. Negate one reform Policy.','41st President, CIA Director, VP, UN rep.','Skull & Bones. Carlyle Group. NWO speech.',['cia','bush','deep_state']),
    _hc('FIG162',' Prescott Bush','Figure','economic','1930-1950','UR','None',5,7,
       'Industrialist: +2 to economic. Risk: Nazi connection allegations.','Bush family patriarch, Brown Brothers Harriman.','Union Banking Corp seized under Trading with Enemy Act.',['bush','nazi','banking']),
    _hc('FIG163','Lyndon LaRouche','Figure','intelligence','1970-2019','R','None',4,6,
       'Conspiracy Theorist: Reveal 3 face-down. Risk: Discredited.','Political activist, conspiracy theorist.','Fusion energy, British monarchy plots. Jailed for fraud.',['larouche','conspiracy','activist']),
    _hc('FIG164','Lee Kuan Yew','Figure','foreign','1959-1990','UR','None',7,8,
       'Founding Father: +3 influence to economic. +2 to domestic.','Singapore founding PM, transformed nation.','From swamp to metropolis. Authoritarian but prosperous.',['singapore','development','authoritarian'],'Singapore'),
    _hc('FIG165','Park Chung-hee','Figure','foreign','1961-1979','UR','None',7,5,
       'Miracle on Han River: +3 to economic. +2 to military. Risk: Assassination.','South Korean dictator, industrialized nation.','Assassinated by own intelligence chief. Daughter became president, impeached.',['south_korea','dictator','development'],'South Korea'),
    _hc('FIG166','Suharto','Figure','foreign','1967-1998','UR','None',7,5,
       'New Order: +3 power to military. Risk: -3 influence. Destroy 2 social.','Indonesian dictator 31 years.','1965 mass killings 500K+. East Timor. Corruption.',['indonesia','dictator','genocide'],'Indonesia'),
    _hc('FIG167','Salvador Allende','Figure','foreign','1970-1973','R','None',5,7,
       'Democratically Elected Socialist: +2 to social. Risk: CIA coup.','Chilean President, overthrown by CIA-backed Pinochet.','Died in La Moneda. Last democratic Marxist leader.',['chile','socialist','cia'],'Chile'),
    _hc('FIG168','Jacobo Arbenz','Figure','foreign','1951-1954','R','None',5,6,
       'Land Reformer: +2 to social. Risk: United Fruit destroys you.','Guatemalan President, overthrown by CIA.','Land reform threatened United Fruit. Castillo Armas installed.',['guatemala','reform','cia'],'Guatemala'),
    _hc('FIG169','Patrice Lumumba','Figure','foreign','1960','R','None',5,7,
       'Independence Leader: +2 to revolutionary. Risk: CIA assassination.','First PM of Congo, assassinated.','Killed by Belgian/Congolese operatives with CIA involvement.',['congo','independence','assassination'],'Congo'),
    _hc('FIG170','Mobutu Sese Seko','Figure','foreign','1965-1997','UR','CIA',7,4,
       'Kleptocrat: +3 to economic. Risk: -4 influence. Destroy 2 social.','Zaire dictator 32 years, looted $5B.','Leopard-skin hat. "Mobutism." US anti-communist ally.',['congo','dictator','kleptocrat'],'Congo'),
    _hc('FIG171','Jacob Zuma','Figure','foreign','2009-2018','R','None',5,4,
       'Corruption: +2 to economic. Risk: Scandal cards double.','South African President, corruption charges.','Arms deal, Nkandla upgrade. Gupta family influence.',['south_africa','corruption','guptas'],'South Africa'),
    _hc('FIG172','Bashir Gemayel','Figure','foreign','1982','R','None',5,5,
       'Phalange: +2 to military. Risk: Assassination.','Lebanese President-elect, assassinated.','Israeli ally. Kataeb Party. Killed by bomb 9 days before inauguration.',['lebanon','assassination','israel'],'Lebanon'),
    _hc('FIG173','Yitzhak Rabin','Figure','foreign','1974-1995','UR','Mossad',7,8,
       'Peacemaker: +3 influence to social. Negate one military Event. Risk: Assassination.','Israeli PM, Oslo Accords, Nobel Peace Prize.','Assassinated by right-wing extremist 1995.',['israel','nobel','assassination'],'Israel'),
    _hc('FIG174','Ariel Sharon','Figure','foreign','2001-2006','UR','Mossad',8,5,
       'Bulldozer: +4 power to military. Risk: Sabra and Shatila Scandal.','Israeli PM, general, Lebanon invasion 1982.','Sabra/Shatila massacre. Gaza withdrawal. Coma 2006-2014.',['israel','military','lebanon'],'Israel'),
    _hc('FIG175','Evo Morales','Figure','foreign','2006-2019','R','None',5,6,
       'Indigenous President: +2 to social. Risk: Military coup.','Bolivia\'s first indigenous president.','MAS party. Lithium coup allegations 2019. Returned 2020.',['bolivia','indigenous','coup'],'Bolivia'),
    _hc('FIG176','Hugo Chavez','Figure','foreign','1999-2013','UR','None',7,7,
       'Bolivarian Revolution: +3 to revolutionary. Oil +2 power. Risk: Economic -2.','Venezuelan President, socialist.','Oil wealth, anti-US. Failed 2002 coup vs him. Succession crisis.',['venezuela','socialist','oil'],'Venezuela'),
    _hc('FIG177','Nicolas Maduro','Figure','foreign','2013-present','R','None',5,4,
       'Chavista Successor: +2 to military. Risk: Economic -3. Humanitarian crisis.','Venezuelan President, Chavez successor.','Hyperinflation, migration crisis. Disputed election 2019.',['venezuela','dictator','crisis'],'Venezuela'),
    _hc('FIG178','Juan Guaido','Figure','foreign','2019-2022','U','None',3,5,
       'Interim: +1 influence. Risk: No real power.','Venezuelan opposition leader, recognized by 60 countries.','Failed to oust Maduro. Lost recognition. Exiled.',['venezuela','opposition','us_backed'],'Venezuela'),
    _hc('FIG179','Volodymyr Zelensky','Figure','foreign','2019-present','UR','None',6,8,
       'Wartime Leader: +3 power to military. +3 influence to social.','Ukrainian President, wartime leadership.','Comedian turned president. Russian invasion 2022.',['ukraine','war','leadership'],'Ukraine'),
    _hc('FIG180','Viktor Yanukovych','Figure','foreign','2010-2014','R','Kremlin',5,4,
       'Pro-Russian: +2 to Kremlin cards. Risk: Revolution cards triple.','Ukrainian President, ousted by Euromaidan.','Fled to Russia. Corruption. Putin\'s man.',['ukraine','russia','corruption'],'Ukraine'),
    _hc('FIG181','Boris Johnson','Figure','foreign','2019-2022','R','None',5,5,
       'BoJo: +2 to economic. Risk: Scandal cards double. Partygate.','UK PM, Brexit architect.','Blonde chaos. COVID parties. Pincher affair. Resigned.',['uk','brexit','scandal'],'UK'),
    _hc('FIG182','Tony Blair','Figure','foreign','1997-2007','UR','None',6,7,
       'Third Way: +2 to economic. +2 to military. Risk: Iraq War Scandal.','UK PM, Labour, Iraq War.','WMD dossier. Chilcot Inquiry. Middle East envoy.',['uk','iraq_war','labour'],'UK'),
    _hc('FIG183','Gordon Brown','Figure','foreign','2007-2010','U','None',4,6,
       'Bigotgate: +2 to economic. Negate one financial crisis.','UK PM during 2008 crash.','Sold gold cheap. "Saved the world." G20 response.',['uk','economy','labour'],'UK'),
    _hc('FIG184','Helmut Kohl','Figure','foreign','1982-1998','UR','None',6,8,
       'Reunification: +3 influence to European. Negate one communist card.','German Chancellor, reunified Germany.','Maastricht Treaty. Euro architect. 16 years in power.',['germany','eu','reunification'],'Germany'),
    _hc('FIG185','Olaf Scholz','Figure','foreign','2021-present','U','None',4,6,
       'Olaf the Boring: +2 to economic. Risk: Nord Stream Scandal.','German Chancellor, SPD.','Nord Stream 2, Ukraine tanks, fiscal discipline.',['germany','eu','spd'],'Germany'),
    _hc('FIG186','Shinzo Abe','Figure','foreign','2012-2020','UR','None',7,6,
       'Abenomics: +3 to economic. Risk: -1 influence. Assassinated.','Japanese PM longest serving.','QE, weak yen. Unification Church ties. Shot 2022.',['japan','abenomics','assassination'],'Japan'),
    _hc('FIG187','Jean-Claude Duvalier','Figure','foreign','1971-1986','R','None',5,3,
       'Baby Doc: +2 power. -4 influence. Risk: Revolution cards triple.','Haitian dictator, succeeded father Papa Doc.','Tonton Macoute terror. Fled to France 1986. Returned 2011.',['haiti','dictator','tonton_macoute'],'Haiti'),
    _hc('FIG188','Imran Khan','Figure','foreign','2018-2022','R','None',5,6,
       'Cricket Star: +2 to social. Risk: Military removes you.','Pakistani PM, cricketer turned politician.','Ousted by no-confidence. Shot at rally. Jailed.',['pakistan','opposition','military'],'Pakistan'),
    _hc('FIG189','Jair Bolsonaro','Figure','foreign','2019-2022','R','None',6,5,
       'Tropical Trump: +2 to military. Risk: Amazon + pandemic Scandals.','Brazilian President, right-wing.','COVID denial. Amazon fires. Jan 8 Brazil riot.',['brazil','right_wing','covid'],'Brazil'),
    _hc('FIG190','Lula da Silva','Figure','foreign','2003-2022','R','None',6,7,
       'Worker\'s President: +3 to social. Risk: Corruption allegations.','Brazilian President, Workers Party.','Jailed then freed. Returned to power 2023.',['brazil','socialist','corruption'],'Brazil'),
    # ── New Figures ──
    _hc('FIG191','James K. Polk','Figure','domestic','1845-1849','R','White House',6,6,
       'Manifest Destiny: +3 to territorial cards. Mexican War +2. One term only.','11th President, expansionist.','Oregon, Texas annexation, Mexican War. Died 3 months post-presidency.',['president','expansion','mexican_war']),
    _hc('FIG192','James Buchanan','Figure','domestic','1857-1861','C','White House',3,3,
       'Doomed Presidency: -2 to all domestic. Civil War Event cards triple.','15th President, failed to prevent Civil War.','Dred Scott. Kansas chaos. Only bachelor president.',['president','failure','civil_war']),
    _hc('FIG193','Andrew Johnson','Figure','domestic','1865-1869','U','White House',4,4,
       'Impeached: +1 to military. Risk: Social -3, Reconstruction cards fail.','17th President, first impeached.','Vetoed civil rights bills. Survived Senate trial by 1 vote.',['president','impeachment','reconstruction']),
    _hc('FIG194','Grover Cleveland','Figure','domestic','1885-1897','U','White House',5,5,
       'Non-Consecutive: Play twice. Economic +2. Risk: Panic of 1893.','22nd and 24th President, only non-consecutive.','Bourbon Democrat. Gold standard. Pullman Strike.',['president','democrat','gold_standard']),
    _hc('FIG195','Rutherford B. Hayes','Figure','domestic','1877-1881','U','White House',4,5,
       'Compromise: +2 to domestic. End Reconstruction. Risk: Black -3 influence.','19th President, disputed election.','Compromise of 1877. Troops withdrawn from South.',['president','compromise','reconstruction']),
    _hc('FIG196','Chester A. Arthur','Figure','domestic','1881-1885','U','White House',4,5,
       'Civil Service Reform: +2 to economic. Negate one Spoils card.','21st President, succeeded Garfield.','Pendleton Act. Chinese Exclusion Act. Surprise reformer.',['president','reform','civil_service']),
    _hc('FIG197','Huey Long','Figure','domestic','1928-1935','UR','None',7,6,
       'The Kingfish: +4 to social. Share Our Wealth. Risk: Assassination.','Louisiana governor/senator, populist demagogue.','Every man a king. Built roads, schools. Shot 1935.',['populist','louisiana','socialist']),
    _hc('FIG198','Eugene V. Debs','Figure','domestic','1894-1920','R','None',5,7,
       'Labor Leader: +3 to social. +2 to labor cards. Risk: Imprisonment.','Socialist leader, 5-time presidential candidate.','Pullman Strike jailed. WWI sedition jailed. 1M votes from prison.',['socialist','labor','imprisonment']),
    _hc('FIG199','William Jennings Bryan','Figure','domestic','1896-1925','R','None',5,7,
       'Cross of Gold: +3 to economic. Populist +2. Risk: Scopes Trial.','Three-time Democratic nominee, populist orator.','Free silver. Anti-imperialism. Scopes Monkey Trial prosecutor.',['populist','bryan','orator']),
    _hc('FIG200','Boss Tweed','Figure','domestic','1858-1871','R','Tammany Hall',6,4,
       'Tammany Hall: +3 to economic. Steal $50M. Risk: Scandal cards triple.','New York political boss, corruption kingpin.','Tweed Courthouse. Thomas Nast cartoons brought him down.',['tammany','corruption','new_york']),
    _hc('FIG201','Joseph McCarthy','Figure','domestic','1947-1957','UR','Congress',6,5,
       'Red Scare: +3 to intelligence. Destroy 2 communist cards. Risk: Backlash.','Wisconsin Senator, anti-communist crusader.','Army-McCarthy hearings. "Have you no decency." Censured.',['mccarthy','red_scare','anticommunist']),
    _hc('FIG202','John Tyler','Figure','domestic','1841-1845','C','None',4,4,
       'Accidental President: +1 to domestic. Risk: No party support, impeached.','First VP to succeed on death. Whig expelled him.','Annexed Texas. Later joined Confederacy.',['president','texas','whig']),
    _hc('FIG203','Zachary Taylor','Figure','domestic','1849-1850','U','White House',5,4,
       'Old Rough and Ready: +2 to military. Died in office. Risk: Short reign.','12th President, Mexican War hero.','Slavery extension debate. Died after 16 months. Cherries?',['president','mexican_war','military']),
    _hc('FIG204','Frederick Douglass','Figure','social','1845-1895','UR','None',5,9,
       'Abolitionist: +4 to social. Destroy all slavery-tagged cards. +2 influence.','Escaped slave, orator, author, statesman.','Narrative of his life. Lincoln advisor. Diplomat to Haiti.',['abolition','frederick_douglass','orator']),
    _hc('FIG205','Ida B. Wells','Figure','social','1889-1931','R','None',4,8,
       'Anti-Lynching: +3 to social. Reveal 3 face-down. Risk: Backlash.','Investigative journalist, civil rights pioneer.','Lynch law statistics. Memphis Free Speech. Suffragist.',['journalist','civil_rights','anti_lynching']),
    # ── Batch 2 Figures ──
    _hc('FIG206','Harriet Tubman','Figure','social','1849-1913','UR','None',5,8,
       'Conductor: +3 to social. Move 2 cards from opponent to your side. Destroy slavery cards.','Escaped slave, Underground Railroad conductor, 70+ rescued.','Combahee River Raid. Spy for Union. First woman to lead US armed expedition.',['underground_railroad','abolition','civil_war']),
    _hc('FIG207','John Brown','Figure','domestic','1855-1859','UR','None',6,5,
       'Martyr: +4 to social. Destroy 3 slavery cards. Risk: Execution, backlash.','Abolitionist who raided Harpers Ferry to arm slaves.','"His soul goes marching on." Hanged. Civil war catalyst.',['abolition','harpers_ferry','martyr']),
    _hc('FIG208','Nat Turner','Figure','domestic','1831','R','None',5,3,
       'Rebellion: +3 to military. Destroy 2 slavery cards. Risk: Retaliation triples.','Enslaved preacher who led Virginia slave rebellion.','60 whites killed. 200+ Blacks killed in retaliation. Hanged, skinned.',['rebellion','slavery','virginia']),
    _hc('FIG209','Booker T. Washington','Figure','social','1881-1915','R','None',5,7,
       'Tuskegee: +3 to economic. Social +2. Risk: Accommodationist backlash.','Former slave, educator, founded Tuskegee Institute.','Atlanta Compromise speech. Up from Slavery. Dined with TR.',['educator','tuskegee','accommodationist']),
    _hc('FIG210','W.E.B. Du Bois','Figure','social','1895-1963','UR','None',5,9,
       'Niagara Movement: +4 to social. +2 to civil rights. Reveal 2 face-down.','NAACP co-founder, scholar, first Black Harvard PhD.','Souls of Black Folk. Talented Tenth. Pan-Africanism. Exiled to Ghana.',['naacp','scholar','pan_african']),
    _hc('FIG211','Rosa Parks','Figure','social','1955-2005','R','None',4,8,
       'Mother of the Movement: +3 to social. Boycott: opponent loses 1 card/turn for 3 turns.','Refused to give up bus seat, sparked Montgomery Bus Boycott.','NAACP secretary. 381-day boycott. "Tired of giving in."',['civil_rights','montgomery','boycott']),
    _hc('FIG212','Medgar Evers','Figure','social','1954-1963','R','None',5,6,
       'Field Secretary: +2 to social. Reveal 2 face-down. Risk: Assassination.','NAACP field secretary in Mississippi, assassinated.','Byron De La Beckwith killed him. Convicted 31 years later.',['naacp','mississippi','assassination']),
    _hc('FIG213','James Garfield','Figure','domestic','1881','U','White House',5,5,
       'Scholar President: +2 to economic. +1 influence. Risk: Assassinated after 200 days.','20th President, Civil War general, scholar.','Shot by Charles Guiteau. Infection killed him. Doctors killed him more.',['president','assassination','civil_war']),
    _hc('FIG214','William Henry Harrison','Figure','domestic','1841','C','White House',3,3,
       'Shortest Reign: +1 to military. Died after 31 days. Risk: No effect.','9th President, died after one month in office.','Longest inauguration speech, caught pneumonia. First to die in office.',['president','short_term','whig']),
    _hc('FIG215','Benjamin Harrison','Figure','domestic','1889-1893','U','White House',4,5,
       'Sherman Antitrust: +2 to economic. Negate one monopoly Org.','23rd President, signed Sherman Antitrust Act.','Electric lights in White House. Billion-dollar Congress.',['president','antitrust','republican']),
    _hc('FIG216','William Howard Taft','Figure','domestic','1909-1913','U','White House',5,6,
       'Trust Buster: +2 to economic. Destroy 1 monopoly Org. Later Chief Justice.','27th President, later Supreme Court Chief Justice.','Broke 90 trusts. Dollar Diplomacy. Heaviest president.',['president','trust_buster','supreme_court']),
    _hc('FIG217','Aaron Burr','Figure','domestic','1801-1805','R','None',5,4,
       'Duelist: Remove one Figure. Risk: Treason trial, exile.','3rd VP, killed Hamilton in duel, later tried for treason.','Western conspiracy alleged. Acquitted. Exiled Europe.',['duel','treason','hamilton']),
    _hc('FIG218','John C. Calhoun','Figure','domestic','1825-1850','R','None',5,6,
       'States Rights: +3 to domestic. Slavery cards +2. Risk: Nullification crisis.','VP, Senator, slavery defender, nullification theorist.','"Slavery as a positive good." Nullification Crisis 1832.',['slavery','nullification','states_rights']),
    _hc('FIG219','Henry Clay','Figure','domestic','1811-1852','UR','None',6,8,
       'The Great Compromiser: +3 to domestic. Negate one Crisis Event. Economic +2.','Speaker of House, Senator, 5-time presidential candidate.','American System. Missouri Compromise. Compromise of 1850.',['compromise','american_system','whig']),
    _hc('FIG220','Stephen A. Douglas','Figure','domestic','1843-1861','R','None',5,6,
       'Little Giant: +2 to domestic. Risk: Lincoln-Douglas debates, Civil War.','Senator, Kansas-Nebraska Act author, Lincoln rival.','Popular sovereignty. Lost 1860 election. Died early in Civil War.',['kansas_nebraska','lincoln','democrat']),
    # ── Batch 3 Figures ──
    _hc('FIG221','Julius Caesar','Figure','foreign','49-44 BC','L','None',9,8,
       'Veni Vidi Vici: +4 to military. +2 to domestic. Risk: Ides of March.','Roman general, dictator, conquered Gaul.','Crossed Rubicon. "Et tu, Brute?" Assassinated Senate. Julian calendar.',['rome','caesar','dictator'],'Rome'),
    _hc('FIG222','Genghis Khan','Figure','foreign','1206-1227','L','None',10,6,
       'Mongol Horde: +5 to military. Destroy 3 foreign cards. Risk: Succession crisis.','Founder of Mongol Empire, largest contiguous land empire.','40M+ killed. Silk Road unified. Religious tolerance. Successor split.',['mongol','conquest','khan'],'Mongolia'),
    _hc('FIG223','Augustus','Figure','foreign','27 BC-14 AD','UR','None',8,9,
       'First Emperor: +3 to domestic. +2 to military. +2 influence to all Policy.','First Roman Emperor, Pax Romana.','Julian dynasty. Census. "I found Rome brick, left it marble."',['rome','emperor','pax_romana'],'Rome'),
    _hc('FIG224','Cleopatra','Figure','foreign','51-30 BC','UR','None',6,9,
       'Seductress: Control 2 foreign Figures. +3 influence. Risk: Roman conquest.','Last pharaoh of Ptolemaic Egypt.','Caesar and Antony alliances. Asp suicide. Lost Actium.',['egypt','pharaoh','ptolemy'],'Egypt'),
    _hc('FIG225','Queen Elizabeth I','Figure','foreign','1558-1603','UR','None',7,9,
       'Virgin Queen: +3 to economic. +2 to military. Negate one Spanish card.','English queen, defeated Spanish Armada.','Golden Age. Shakespeare. Colonization began. Never married.',['uk','armada','elizabeth'],'UK'),
    _hc('FIG226','Catherine the Great','Figure','foreign','1762-1796','UR','None',8,8,
       'Enlightened Despot: +3 to domestic. +2 to military. +2 to economic.','Russian empress, expanded empire.','Partitioned Poland. Founded Hermitage. Pugachev rebellion.',['russia','romanov','enlightenment'],'Russia'),
    _hc('FIG227','Queen Victoria','Figure','foreign','1837-1901','UR','None',7,9,
       'Empress of India: +3 to economic. +2 influence to all British cards. Pax Britannica.','Longest-reigning British monarch (until Elizabeth II).','Industrial Revolution. Opium Wars. 63 years. 9 children married across Europe.',['uk','empire','victorian'],'UK'),
    _hc('FIG228','Oliver Cromwell','Figure','foreign','1653-1658','UR','None',7,6,
       'Lord Protector: +3 to military. Destroy 1 monarchy card. Risk: Puritan backlash.','English Civil War leader, executed Charles I.','New Model Army. Ireland massacre. Protectorate. Body exhumed.',['uk','civil_war','puritan'],'UK'),
    _hc('FIG229','Eleanor Roosevelt','Figure','social','1933-1962','UR','None',5,9,
       'First Lady of the World: +4 to social. +2 to human rights. Negate 1 domestic Scandal.','FDR wife, diplomat, UN delegate.','Universal Declaration of Human Rights. My Day column. Most admired woman.',['first_lady','human_rights','un']),
    _hc('FIG230','Sojourner Truth','Figure','social','1843-1883','R','None',4,7,
       'Aint I a Woman: +3 to social. +2 to abolition. Reveal 2 face-down.','Born enslaved, abolitionist and womens rights orator.','"Aint I a Woman?" speech 1851. Met Lincoln. Freed son legally.',['abolition','womens_rights','orator']),
    _hc('FIG231','Marcus Garvey','Figure','social','1914-1940','R','None',5,7,
       'Black Nationalism: +3 to social. +2 to African cards. Risk: Deportation.','Jamaican activist, UNIA, Pan-Africanism.','Black Star Line. Mail fraud conviction. Deported. Rasta prophet.',['pan_african','unia','black_nationalism']),
    _hc('FIG232',' Sitting Bull','Figure','foreign','1876-1890','UR','None',6,5,
       'Lakota Resistance: +3 to military. Destroy 2 US military cards. Risk: Arrest, death.','Hunkpapa Lakota leader, defeated Custer at Little Bighorn.','Vision before battle. Buffalo Bill tour. Killed during arrest.',['lakota','little_bighorn','native'],'USA'),
    _hc('FIG233','Tecumseh','Figure','foreign','1805-1813','UR','None',6,6,
       'Confederacy: +3 to military. +2 to native cards. Negate 1 US territorial card.','Shawnee leader, built Native confederacy against US expansion.','Prophet brother. War of 1812 ally. Killed at Thames.',['shawnee','confederacy','native'],'USA'),
    _hc('FIG234','Geronimo','Figure','foreign','1858-1886','R','None',5,4,
       'Apache Warrior: +3 to military. Evade 1 attack/turn. Risk: Surrender, exile.','Apache leader, resisted US and Mexican forces for 30 years.','5K troops chased 36 warriors. Surrendered 1886. POW 23 years.',['apache','resistance','native'],'USA'),
    _hc('FIG235','Charlemagne','Figure','foreign','768-814','UR','None',7,7,
       'Father of Europe: +3 to domestic. +2 to military. +2 to religious cards.','King of Franks, first Holy Roman Emperor.','Conquered Saxons. Forced conversion. Carolingian Renaissance.',['franks','holy_roman','christian'],'France'),
    # ── Batch 4 Figures ──
    _hc('FIG236','Alexander the Great','Figure','foreign','336-323 BC','L','None',10,7,
       'Conqueror: +5 to military. +3 to foreign. Destroy 3 enemy cards. Risk: Early death.','Macedonian king, conquered Persia to India by age 30.','Never lost a battle. Aristotle tutor. Alexandria cities. Died 32.',['macedonia','conquest','persia'],'Greece'),
    _hc('FIG237','Hannibal','Figure','foreign','218-183 BC','UR','None',8,6,
       'Elephants: +4 to military. Destroy 2 domestic cards. Risk: Roman counter-invasion.','Carthaginian general, crossed Alps with elephants.','Cannae: 50K Romans killed in one day. Roman terror. Defeated at Zama.',['carthage','alps','cannae'],'Tunisia'),
    _hc('FIG238','Attila the Hun','Figure','foreign','434-453','UR','None',8,5,
       'Scourge of God: +4 to military. Destroy 2 European cards. Risk: Overextension.','Hun leader who ravaged Roman Empire.','Rhone, Po valleys. Pope Leo turned him back. Died nosebleed on wedding night.',['hun','barbarian','rome'],'Hungary'),
    _hc('FIG239','Saladin','Figure','foreign','1174-1193','UR','None',7,8,
       'Chivalrous Sultan: +3 to military. +3 to diplomatic. Negate 1 Crusade card.','Kurdish Muslim leader, recaptured Jerusalem from Crusaders.','Hattin 1187. Chivalrous to enemies. Richard I respected him. United Muslim world.',['saladin','jerusalem','crusades'],'Israel'),
    _hc('FIG240','Suleiman the Magnificent','Figure','foreign','1520-1566','UR','None',8,8,
       'Lawgiver: +3 to military. +3 to domestic. +2 to economic.','Ottoman Sultan at empires peak.','Siege of Vienna 1529. Law reforms. Architect Sinan. Hurrem Sultan.',['ottoman','sultan','lawgiver'],'Turkey'),
    _hc('FIG241','Hammurabi','Figure','foreign','1792-1750 BC','R','None',6,7,
       'Code of Laws: +4 to domestic. Negate 1 Scandal. +2 to Policy.','Babylonian king, first written legal code.','"Eye for eye." 282 laws on stele. Presumption of innocence.',['babylon','law','code'],'Iraq'),
    _hc('FIG242','Justinian I','Figure','foreign','527-565','UR','None',7,8,
       'Corpus Juris: +3 to domestic. +2 to military. +2 to Policy. Risk: Plague.','Byzantine emperor, codified Roman law.','Theodora wife. Hagia Sophia. Nika riots. Belisarius general. Plague of Justinian.',['byzantine','law','justinian'],'Turkey'),
    _hc('FIG243','Constantine the Great','Figure','foreign','306-337','UR','None',7,8,
       'Christian Rome: +3 to military. +3 to religious. +2 to domestic.','First Christian Roman emperor, moved capital to Constantinople.','Milvian Bridge vision. Edict of Milan. Byzantium became Constantinople.',['rome','christian','constantinople'],'Turkey'),
    _hc('FIG244','Cyrus the Great','Figure','foreign','559-530 BC','UR','None',7,8,
       'Persian Empire: +3 to military. +3 to diplomatic. Negate 1 oppression card.','Founder of Achaemenid Empire, first human rights charter.','Freed Jews from Babylon. Cyrus Cylinder. Religious tolerance. Killed in battle.',['persia','cyrus','tolerance'],'Iran'),
    _hc('FIG245','Pericles','Figure','foreign','461-429 BC','R','None',6,9,
       'Golden Age: +3 to domestic. +2 to social. +2 to economic.','Athenian statesman, built Parthenon, direct democracy.','Funeral oration. Peloponnesian War. Died of plague.',['athens','democracy','parthenon'],'Greece'),
    _hc('FIG246','Chief Joseph','Figure','foreign','1877','R','None',5,7,
       'I Will Fight No More: +2 to military. +3 to social. Reveal 2 face-down.','Nez Perce leader, 1200-mile retreat to Canada.','40 miles short. "From where the sun now stands." Exiled to Oklahoma.',['nez_perce','native','retreat'],'USA'),
    _hc('FIG247','Sacagawea','Figure','domestic','1804-1806','R','None',3,7,
       'Guide: +2 to domestic. +2 to diplomatic. Negate 1 hostile native card.','Shoshone woman who guided Lewis and Clark expedition.','Carried infant son. Translator, peace mediator. Dollar coin.',['lewis_clark','shoshone','guide']),
    _hc('FIG248','Red Cloud','Figure','foreign','1866-1868','R','None',5,5,
       'Red Clouds War: +3 to military. Destroy 2 US military cards. Won treaty.','Lakota leader who defeated US in Powder River War.','Fetterman Fight, 80 soldiers killed. Fort Phil Kearny abandoned. Won war, signed treaty.',['lakota','native','powder_river'],'USA'),
    _hc('FIG249','Crazy Horse','Figure','foreign','1876-1877','UR','None',6,4,
       'Visionary Warrior: +4 to military. Destroy 1 US military card. Risk: Betrayal.','Oglala Lakota war leader, key at Little Bighorn.','Never photographed. Bayoneted at Fort Robinson. "It is a good day to die."',['lakota','crazy_horse','native'],'USA'),
    _hc('FIG250','Black Hawk','Figure','foreign','1832','U','None',4,4,
       'Black Hawk War: +2 to military. +1 to social. Risk: Defeat, exile.','Sauk leader who fought to reclaim Illinois lands.','Bad Axe massacre. Abraham Lincoln served briefly. Autobiography published.',['sauk','native','black_hawk'],'USA'),
    # ── Batch 5 Figures: Ancient Empires & Asian History ──
    _hc('FIG251','Ashoka the Great','Figure','foreign','268-232 BC','UR','None',7,9,
       'Dharma: +4 to social. +2 to diplomatic. Negate 1 war card. Risk: Empire fragments.','Mauryan emperor who renounced violence after Kalinga war.','Spread Buddhism. Edicts on pillars. Religious tolerance. India golden age.',['india','buddhism','maurya'],'India'),
    _hc('FIG252','Darius I','Figure','foreign','522-486 BC','UR','None',7,8,
       'Persian Administration: +3 to domestic. +2 to economic. Royal Road.','Achaemenid king who organized Persian Empire into satrapies.','Royal Road, postal system. Canal at Suez. Defeated at Marathon.',['persia','achaemenid','administration'],'Iran'),
    _hc('FIG253','Xerxes I','Figure','foreign','486-465 BC','R','None',6,6,
       'Second Invasion: +3 to military. Destroy 2 Greek cards. Risk: Defeat at Salamis.','Persian king who invaded Greece, burned Athens.','Thermopylae, Salamis. 300 Spartans. Assassinated by courtiers.',['persia','invasion','greece'],'Iran'),
    _hc('FIG254','Marcus Aurelius','Figure','foreign','161-180','UR','None',6,9,
       'Philosopher King: +3 to domestic. +2 to social. +1 to military. Stoic.','Roman emperor, Stoic philosopher, last of Five Good Emperors.','Meditations. Germanic wars. Commodus son ruined empire.',['rome','stoic','philosopher'],'Italy'),
    _hc('FIG255','Cicero','Figure','foreign','63-43 BC','R','None',4,8,
       'Orator: +3 to social. +2 to diplomatic. Reveal 2 face-down. Risk: Proscription.','Roman statesman, greatest orator, defender of Republic.','Catiline conspiracy. Philippics vs Antony. Head and hands displayed.',['rome','republic','orator'],'Italy'),
    _hc('FIG256','Trajan','Figure','foreign','98-117','UR','None',7,7,
       'Optimus Princeps: +3 to military. +2 to domestic. +2 to economic.','Roman emperor at empires greatest extent.','Dacian Wars, gold. Column. Public works. Adopted successor system.',['rome','conquest','dacian'],'Italy'),
    _hc('FIG257','Akbar the Great','Figure','foreign','1556-1605','UR','None',7,9,
       'Divine Faith: +3 to domestic. +3 to diplomatic. Negate 1 religious conflict.','Mughal emperor known for religious tolerance and administrative reform.','Abolished jizya tax. Married Hindu princess. Din-i-Ilahi synthesis.',['india','mughal','tolerance'],'India'),
    _hc('FIG258','Tokugawa Ieyasu','Figure','foreign','1600-1616','UR','None',7,7,
       'Shogun: +4 to domestic. +2 to military. Negate 1 foreign card. Risk: Isolation.','Unified Japan, founded Tokugawa shogunate, 250 years of peace.','Sekigahara battle. Alternate attendance. Closed country sakoku.',['japan','shogun','tokugawa'],'Japan'),
    _hc('FIG259','Oda Nobunaga','Figure','foreign','1560-1582','R','None',6,5,
       'Demon King: +4 to military. Destroy 2 religious cards. Risk: Betrayal at Honno-ji.','Warlord who began unification of Japan, betrayed by vassal.','Firearms adoption. Destroyed Buddhist monasteries. Honno-ji incident.',['japan','sengoku','oda'],'Japan'),
    _hc('FIG260','Queen Nzinga','Figure','foreign','1624-1663','R','None',5,7,
       'Diplomatic Warrior: +3 to military. +2 to diplomatic. Negate 1 colonial card.','Angolan queen who fought Portuguese colonization for 40 years.','Negotiated with Portuguese. Guerrilla warfare. Allied with Dutch.',['angola','resistance','colonial'],'Angola'),
    _hc('FIG261','Shaka Zulu','Figure','foreign','1816-1828','UR','None',7,4,
       'Assegai: +4 to military. Destroy 2 African cards. +2 to military org. Risk: Assassination.','Zulu king who revolutionized African warfare.','Short stabbing spear. Buffalo formation. Mfecane upheaval. Half-brother killed him.',['zulu','africa','warfare'],'South Africa'),
    _hc('FIG262','Mansa Musa','Figure','foreign','1312-1337','UR','None',6,10,
       'Golden Pilgrim: +5 to economic. +2 to diplomatic. Risk: Gold inflation.','Mali emperor, richest person in history, gold devalued on hajj.','Timbuktu. 60K entourage. Spent so much gold he crashed Egypts economy.',['mali','gold','africa'],'Mali'),
    _hc('FIG263','Boudica','Figure','foreign','60-61','R','None',5,5,
       'Warrior Queen: +3 to military. Destroy 2 Roman cards. Risk: Defeat, poison.','Celtic queen who led Icini revolt against Roman occupation.','London burned. 80K dead. Poisoned herself after defeat.',['celt','icini','rome'],'UK'),
    _hc('FIG264','Spartacus','Figure','foreign','73-71 BC','R','None',5,4,
       'Slave Revolt: +3 to military. Destroy 2 slavery cards. +2 to revolutionary.','Thracian gladiator who led slave rebellion against Rome.','Crucified 6000 along Appian Way. "I am Spartacus." Marxist icon.',['rome','slave','rebellion'],'Italy'),
    _hc('FIG265','Joan of Arc','Figure','foreign','1429-1431','UR','None',5,8,
       'Divine Mission: +3 to military. +2 to religious. Negate 1 English card. Risk: Burned.','Peasant girl who led French army to victory during Hundred Years War.','Orleans lifted. Charles VII crowned. Burned at stake 19 years old. Saint 1920.',['france','saint','hundred_years'],'France'),
    # ── Batch 6 Figures: 20th Century World Leaders ──
    _hc('FIG266','Mustafa Kemal Ataturk','Figure','foreign','1923-1938','UR','None',7,8,
       'Modernizer: +3 to domestic. +2 to military. Negate 1 religious card. Risk: Authoritarian.','Founder of modern Turkey, abolished caliphate, secularized state.','Gallipoli hero. Latin alphabet. Womens suffrage. "Peace at home, peace in world."',['turkey','secular','modernizer'],'Turkey'),
    _hc('FIG267','Jawaharlal Nehru','Figure','foreign','1947-1964','R','None',5,8,
       'First PM: +3 to diplomatic. +2 to social. Negate 1 colonial card. Risk: Kashmir dispute.','Indias first Prime Minister, Non-Aligned Movement co-founder.','Secular socialist. Five-year plans. Bandung Conference. Daughter Indira succeeded.',['india','non_aligned','socialist'],'India'),
    _hc('FIG268','Kwame Nkrumah','Figure','foreign','1957-1966','R','None',5,7,
       'Pan-African: +3 to revolutionary. +2 to diplomatic. Negate 1 colonial card. Risk: CIA coup.','Ghanas first President, Pan-Africanism leader.','First sub-Saharan colony freed. OAU founder. Exiled by CIA-backed coup.',['ghana','pan_african','independence'],'Ghana'),
    _hc('FIG269','Jomo Kenyatta','Figure','foreign','1963-1978','R','None',6,6,
       'Father of Nation: +3 to domestic. +2 to economic. Risk: One-party state.','Kenyas first President, independence leader.','Mau Mau rebellion. "Harambee." Land disputes. Son Uhuru became president.',['kenya','independence','africa'],'Kenya'),
    _hc('FIG270','Haile Selassie','Figure','foreign','1930-1974','UR','None',6,8,
       'Lion of Judah: +3 to diplomatic. +2 to military. Negate 1 fascist card. Risk: Famine, coup.','Ethiopian Emperor, last monarch, OAU founder.','Appealed to League of Nations 1936. Rastafari messiah. Overthrown by Marxist junta.',['ethiopia','monarch','oafrican'],'Ethiopia'),
    _hc('FIG271','Josip Broz Tito','Figure','foreign','1945-1980','UR','None',7,7,
       'Non-Aligned: +3 to diplomatic. +2 to military. Negate 1 Soviet AND 1 US card.','Yugoslav leader, independent communist, defied Stalin.','Partisan war hero. Split with Stalin 1948. Built multi-ethnic state. Collapsed after death.',['yugoslavia','non_aligned','communist'],'Yugoslavia'),
    _hc('FIG272','Benito Mussolini','Figure','foreign','1922-1943','UR','None',7,5,
       'Il Duce: +3 to military. +2 to domestic. Risk: Hanging upside down.','Italian fascist dictator, WWII ally of Hitler.','March on Rome. Abyssinia. Corporatism. Executed by partisans, hung in Milan.',['italy','fascist','dictator'],'Italy'),
    _hc('FIG273','Antonio Salazar','Figure','foreign','1932-1968','R','None',6,7,
       'Estado Novo: +3 to domestic. +2 to economic. Negate 1 revolutionary card. Risk: Colonial wars.','Portuguese dictator, economist, kept colonies.','Secret police PIDE. Neutral in WWII. Colonial wars drained treasury. Brain hemorrhage.',['portugal','dictator','colonial'],'Portugal'),
    _hc('FIG274','Francisco Franco','Figure','foreign','1939-1975','UR','None',7,5,
       'Caudillo: +4 to military. +2 to domestic. Negate 1 revolutionary card. Risk: Isolation.','Spanish dictator, won Civil War, neutral in WWII.','Condor Legion. Guernica. 400K political prisoners. Restored monarchy. Juan Carlos.',['spain','fascist','dictator'],'Spain'),
    _hc('FIG275','Golda Meir','Figure','foreign','1969-1974','R','None',5,7,
       'Iron Lady of Israel: +3 to military. +2 to diplomatic. Risk: Yom Kippur surprise.','Israeli PM during Yom Kippur War, fourth woman PM in world.','Milwaukee-raised. Munich Olympics. Wept before cabinet. Resigned 1974.',['israel','yom_kippur','pm'],'Israel'),
    _hc('FIG276','Leonid Brezhnev','Figure','foreign','1964-1982','UR','KGB',6,6,
       'Stagnation: +3 to military. +2 to diplomatic. Risk: Economic -3. Afghanistan quagmire.','Soviet leader, détente era, then stagnation.','SALT treaties. Helsinki Accords. Afghanistan 1979. Gerontocracy. Died in office.',['soviet','cold_war','stagnation'],'USSR'),
    _hc('FIG277','Hastings Banda','Figure','foreign','1964-1994','R','None',6,5,
       'Life President: +3 to domestic. +2 to economic. Risk: One-party state, exile.','Malawian dictator 30 years, pro-Western Cold War ally.','Banda, Kamuzu. Total control. Exiled British. Tobacco economy. Voted out 1994.',['malawi','dictator','cold_war'],'Malawi'),
    _hc('FIG278','Ferdinand Marcos Sr.','Figure','foreign','1965-1986','UR','None',7,5,
       'Martial Law: +3 to military. +2 to economic. Risk: People Power, exile.','Philippine dictator 21 years, looted billions.','Imelda shoes. US bases. Inflation. Overthrown 1986. Hawaii exile. Son became president 2022.',['philippines','dictator','martial_law'],'Philippines'),
    _hc('FIG279','Vaclav Havel','Figure','foreign','1989-2003','R','None',4,8,
       'Velvet Revolutionary: +3 to social. +2 to diplomatic. Negate 2 communist cards.','Czech dissident, playwright, President.','Charter 77. Prague Spring. "Power of the Powerless." NATO membership.',['czech','dissident','velvet'],'Czech Republic'),
    _hc('FIG280','Hafez al-Assad','Figure','foreign','1971-2000','UR','None',7,5,
       'The Lion: +3 to military. +2 to domestic. Negate 1 revolutionary card. Risk: Hama massacre.','Syrian dictator 30 years, air force officer.','Hama 1982, 20K+ killed. Muslim Brotherhood crushed. Golan lost. Son Bashar succeeded.',['syria','dictator','hama'],'Syria'),
    # ── Batch 7 Figures: Conspiracy-Adjacent & Controversial ──
    _hc('FIG281','E. Howard Hunt','Figure','intelligence','1949-1972','R','CIA',5,6,
       'Plumber: Reveal 2 face-down. +2 to Conspiracy. Risk: Watergate exposure.','CIA officer, Watergate burglar, JFK assassination suspect.','Bay of Pigs. Hunt confessed on deathbed to JFK plot involvement. Watergate break-in.',['cia','watergate','jfk']),
    _hc('FIG282','James Jesus Angleton','Figure','intelligence','1954-1975','UR','CIA',7,8,
       'Mole Hunter: Peek 2 face-down. Intelligence +3. Risk: Paranoia destroys CIA.','CIA counter-intelligence chief, paranoid mole hunt.','Soviet defectors Nosenko, Golitsyn. Destroyed CIA operations. Angletonian paranoia.',['cia','counter_intel','mole']),
    _hc('FIG283','Barry Seal','Figure','intelligence','1972-1986','R','CIA',5,5,
       'Smuggler: +3 to economic. Destroy 1 social card. Risk: Assassinated.','CIA informant and drug smuggler, flew Contra supply missions from Mena, Arkansas.','Tom Cruise movie. DEA informant. Medellin cartel. Assassinated in Baton Rouge 1986.',['cia','drugs','contra']),
    _hc('FIG284','Alexander Litvinenko','Figure','intelligence','2000-2006','R','None',4,7,
       'Poisoned Dissident: Reveal 3 face-down. Intelligence +2. Risk: Polonium death.','Ex-FSB officer poisoned with polonium-210 in London.','Blamed Putin. Litvinenko accusations: FSB blew up apartments, staged terror. FSB death squad.',['fsb','poison','russia']),
    _hc('FIG285','Smedley Butler','Figure','military','1898-1940','UR','None',7,8,
       'War is a Racket: +3 to social. Negate 1 corporate Org. Reveal 1 Conspiracy.','Marine general who exposed Business Plot to overthrow FDR in 1933.','Most decorated Marine. "I was a gangster for capitalism." Business Plot testified to Congress.',['business_plot','military','whistleblower']),
    _hc('FIG286','Jack Ruby','Figure','domestic','1963','U','None',3,5,
       'Silencer: Remove 1 Figure. Destroy 1 Conspiracy. Risk: Dies in custody.','Nightclub owner who killed Lee Harvey Oswald on live TV.','Mafia ties. Dallas police let him in. Claimed Jackie Kennedy. Died of cancer 1967.',['jfk','oswald','mafia']),
    _hc('FIG287','Ghislaine Maxwell','Figure','social','1990s-2021','UR','None',5,8,
       'Madam: Control 2 Figure cards. Reveal 2 face-down. Risk: 20-year sentence.','Epsteins associate, convicted of sex trafficking.','Daughter of Robert Maxwell (MI6/Mossad links). Epstein island. Prince Andrew. Jailed 2022.',['epstein','trafficking','maxwell']),
    _hc('FIG288','William Colby','Figure','intelligence','1950-1996','R','CIA',6,7,
       'CIA Director: +2 to intelligence. Reveal 2 face-down. Risk: Canoe accident.','CIA director who cooperated with Church Committee, exposed family jewels.','Vietnam Phoenix Program. Opened CIA books. Found dead in canoe accident 1996.',['cia','church_committee','phoenix']),
    _hc('FIG289','Larry McDonald','Figure','domestic','1975-1983','R','None',4,6,
       'Anti-Communist: +2 to military. Negate 1 communist card. Risk: KAL 007.','Congressman, John Birch Society president, died on Korean Air Lines 007 shot down by USSR.','KAL 007 diverted into Soviet airspace. 269 killed. Cold War incident. Conspiracy: deliberate?',['kal007','cold_war','birch']),
    _hc('FIG290','Danny Casolaro','Figure','intelligence','1991','U','None',2,5,
       'Journalist: Reveal 2 face-down. Peek 1. Risk: Found dead in bathtub.','Journalist investigating PROMIS software, Octopus conspiracy, found dead in hotel bathtub.','Ruled suicide. Slashed wrists. Files missing. Was investigating CIA, Inslaw, Wackenhut.',['casolaro','promis','journalist']),
    # ── Batch 8 Figures: Intelligence Directors & Neocon Architects ──
    _hc('FIG291','Richard Helms','Figure','intelligence','1966-1973','UR','CIA',6,8,
       'The Keeper: +2 to intelligence. Peek 2 face-down. Risk: Church Committee.','CIA director who kept secrets, resisted Nixon, fired for not covering up.','Ordered MKUltra destruction. Convicted of misleading Congress. Ambassador to Iran.',['cia','mkultra','church_committee']),
    _hc('FIG292','William Casey','Figure','intelligence','1981-1987','UR','CIA',7,7,
       'Reagan Spook: +3 to intelligence. +2 to military. Risk: Iran-Contra.','CIA director under Reagan, expanded covert ops worldwide.','Nicaragua, Afghanistan, Angola. Knights of Malta. Died before testimony.',['cia','iran_contra','afghanistan']),
    _hc('FIG293','George Tenet','Figure','intelligence','1997-2004','R','CIA',5,6,
       'Slam Dunk: +2 to intelligence. Risk: WMD intelligence failure.','CIA director during 9/11 and Iraq WMD claims.','"Slam dunk" quote to Bush on WMD. Medal of Freedom. Torture program. Black sites.',['cia','wmd','torture']),
    _hc('FIG294','John Poindexter','Figure','intelligence','1983-1987','R','NSA',5,6,
       'Iran-Contra Architect: Trade 2 cards secretly. Reveal 1. Risk: Conviction.','NSC advisor who devised Iran-Contra arms-for-hostages scheme.','Convicted on 5 felonies, overturned. Total Information Awareness. DARPA.',['iran_contra','nsa','conviction']),
    _hc('FIG295','Elliott Abrams','Figure','foreign','1981-present','R','White House',4,6,
       'Contra Defender: +2 to military. Negate 1 human rights card. Risk: Pardoned.','Reagan/Bush official, Iran-Contra convicted, pardoned, Trump special envoy.','El Salvador death squads. Guatemala. Convicted 1991. Pardoned by Bush. Trump Venezuela envoy.',['iran_contra','contra','pardon']),
    _hc('FIG296','Paul Wolfowitz','Figure','foreign','1989-2005','UR','Pentagon',6,7,
       'Neocon Architect: +3 to military. +2 to foreign Policy. Risk: Iraq quagmire.','Deputy Sec Def, Iraq War architect, World Bank president.','Clean Break memo. PNAC signatory. WMD claims. World Bank scandal. Chalabi ally.',['neocon','iraq','pentagon']),
    _hc('FIG297','Richard Perle','Figure','foreign','1981-2004','UR','Pentagon',5,7,
       'Prince of Darkness: +2 to military. +2 to intelligence. Peek 1 face-down. Risk: Conflict of interest.','Neocon strategist, Defense Policy Board chairman, Iraq War pusher.','Clean Break for Netanyahu 1996. AEI. Hollinger International. Trireme Partners.',['neocon','iraq','israel']),
    _hc('FIG298','Douglas Feith','Figure','foreign','2001-2005','R','Pentagon',4,6,
       'OSP: +2 to intelligence. Create 1 fake intelligence card. Risk: Chalabi connection.','Undersecretary of Defense for Policy, Office of Special Plans stovepiped Iraq intel.','Feith-based intelligence. Cherry-picked WMD. Gen. Tommy Franks: "dumbest guy on the planet."',['neocon','iraq','osp']),
    _hc('FIG299','Ahmed Chalabi','Figure','foreign','1990-2015','R','CIA',4,5,
       'Exile Asset: +2 to intelligence. Create fake intelligence. Risk: Iran double agent.','Iraqi exile who fed false WMD intelligence to US, lobbied for Iraq War.','INC. Curveball source. Defection Act. Iranian intelligence connection. Petraeus ally.',['iraq','wmd','iran']),
    _hc('FIG300','Michael Hayden','Figure','intelligence','2005-2009','R','NSA',5,7,
       'Bulk Collection: +3 to intelligence. Peek 3 face-down. Risk: Snowden exposes.','NSA and CIA director, oversaw warrantless wiretapping, Stellar Wind.','4th Amendment "not absolute." Enhanced interrogation defender. CNN analyst.',['nsa','cia','surveillance']),
    # ── Batch 9 Figures: Spymasters, Oligarchs & Think Tank Architects ──
    _hc('FIG301','Yuri Andropov','Figure','intelligence','1967-1982','UR','KGB',7,8,
       'KGB Chairman: +3 to intelligence. Peek 2 face-down. Negate 1 reform. Risk: Chernenko succession.','KGB chief then Soviet leader, suppressed Prague Spring, crushed dissidents.','Operation RYAN. Crushed Hungarian 1956. Oleg Gordievsky betrayed him. Short reign.',['kgb','soviet','cold_war'],'USSR'),
    _hc('FIG302','Nikolai Patrushev','Figure','intelligence','1999-2008','UR','KGB',6,7,
       'Silovik: +2 to intelligence. +2 to military. Peek 1 face-down. Risk: Putin succession architect.','FSB director, Security Council secretary, Putins inner circle silovik.','Beslan response. Apartment bombing conspiracy. Nord Stream denial. Putin loyalist since KGB.',['fsb','russia','silovik'],'Russia'),
    _hc('FIG303','Alexander Bortnikov','Figure','intelligence','2008-present','R','KGB',5,6,
       'FSB Director: +2 to intelligence. Reveal 1 face-down. Negate 1 domestic Scandal.','Head of FSB, Putins domestic intelligence enforcer.','Nord Stream investigation blocked. Opposition poisoning operations. Navalny persecution.',['fsb','russia','surveillance'],'Russia'),
    _hc('FIG304','Erik Prince','Figure','military','1997-present','UR','None',6,6,
       'PMC Baron: +3 to military. Create 1 mercenary card. Risk: Nisour Square, legal scrutiny.','Blackwater founder, private military entrepreneur, Trump adviser.','UAE mercenary army. Libya operation. China frontier services. DeVos family. Sister Betsy DeVos.',['blackwater','mercenary','cia']),
    _hc('FIG305','Marc Rich','Figure','economic','1970-2001','UR','None',5,6,
       'Commodities King: +3 to economic. Trade 2 cards secretly. Risk: Pardoned, fugitive.','Fugitive commodities trader, pardoned by Clinton on last day.','Iran oil trades during hostage crisis. $48M tax evasion. Denise Rich donations. Clinton pardon scandal.',['rich','oil','pardon'],'Switzerland'),
    _hc('FIG306','Leslie Wexner','Figure','economic','1963-present','R','None',5,7,
       'Retail Empire: +2 to economic. +2 to social. Peek 1 face-down. Risk: Epstein connection.','Victoria Secret/L Brands CEO, Epsteins patron and client.','Gave Epstein power of attorney. $47M transferred. Wexner Foundation. MEGA group. Zionist lobbying.',['wexner','epstein','retail']),
    _hc('FIG307','Oleg Deripaska','Figure','economic','1990s-present','R','Kremlin',5,6,
       'Aluminum Baron: +2 to economic. +2 to intelligence. Risk: Sanctions, Manafort connection.','Russian oligarch, Rusal founder, close to Putin.','Manafort owed him $10M. Clinton campaign dossier. sanctions 2018. FBI raids. yacht seized.',['russia','oligarch','manafort'],'Russia'),
    _hc('FIG308','Norman Dodd','Figure','domestic','1953-1954','U','None',3,5,
       'Reese Committee: Reveal 2 face-down. Peek 1. Risk: Dismissed as paranoid.','Congressional investigator of tax-exempt foundations, alleged subversive agenda.','Ford, Carnegie, Rockefeller foundations. Claimed they promoted globalism. Reese Committee disbanded.',['foundations','conspiracy','globalism']),
    _hc('FIG309','Leo Strauss','Figure','foreign','1920-1973','U','None',3,6,
       'Noble Lie: +2 to intelligence. +2 to foreign Policy. Peek 1 face-down. Risk: Elite manipulation.','Political philosopher whose ideas influenced neoconservatives.','Perle, Wolfowitz, Abrams studied. Noble lie. Regime change. Natural right. UChicago.',['neocon','philosophy','noble_lie']),
    _hc('FIG310','Albert Wohlstetter','Figure','foreign','1950-1990','R','Pentagon',4,6,
       'Nuclear Strategist: +2 to military. +2 to intelligence. Risk: Proliferation advocacy.','RAND analyst, nuclear war theorist, mentor to Wolfowitz and Perle.','Proliferation optimism. B-2 stealth advocate. Persian Gulf strategy. PNAC intellectual godfather.',['neocon','rand','nuclear']),
    # ── Batch 10 Figures: CIA Directors, Hawks & Intellectuals ──
    _hc('FIG311','John Brennan','Figure','intelligence','2013-2017','R','CIA',5,7,
       'Drone Czar: +2 to intelligence. Destroy 1 social card. Peek 2 face-down. Risk: Senate hacking.','CIA director, Obama counterterror advisor, drone strike architect.','Station chief Riyadh. Enhanced interrogation denial. Hacked Senate computers. MSNBC analyst.',['cia','drones','obama']),
    _hc('FIG312','David Petraeus','Figure','military','2003-2012','UR','Pentagon',7,6,
       'Surge: +3 to military. +2 to intelligence. Risk: Affair, classified leaks.','General, Iraq Surge architect, CIA director, forced out over affair with biographer.','Paula Broadwell. Classified notebooks. Jill Kelley. Tampa socialite drama. Rehabilitated on KKR board.',['cia','iraq','surge']),
    _hc('FIG313','James Forrestal','Figure','intelligence','1947-1949','UR','Pentagon',6,7,
       'First SecDef: +3 to military. +2 to intelligence. Risk: Mental breakdown, death.','First Secretary of Defense, architect of post-WWII national security state.','NSA Act 1947. CIA creation. Fell from hospital window 1949. "The Russians are coming." Conspiracy: murdered.',['pentagon','cold_war','forrestal']),
    _hc('FIG314','Curtis LeMay','Figure','military','1948-1965','UR','Pentagon',7,4,
       'Strategic Bombing: +4 to military. Destroy 3 economic. Risk: -4 influence, war crime.','USAF general, architect of firebombing Japan, Cuban Missile Crisis hawk.','Tokyo firebombing 100K dead. SAC. Wallace VP 1968. "Bomb them back to stone age." Nuclear war advocate.',['pentagon','cold_war','bombing']),
    _hc('FIG315','Lyman Lemnitzer','Figure','military','1960-1962','R','Pentagon',5,5,
       'Northwoods Author: +2 to military. Create 1 fake Event. Risk: JFK fires you.','JCS chairman who proposed Operation Northwoods false-flag to justify Cuba invasion.','Signed Northwoods memo. JFK rejected, transferred to NATO. Gladio connection. Kept clearance.',['pentagon','northwoods','false_flag']),
    _hc('FIG316','John Bolton','Figure','foreign','2001-2020','UR','None',5,7,
       'Regime Change Hawk: +3 to military. +2 to foreign Policy. Negate 1 diplomatic. Risk: Alienates allies.','Neocon diplomat, UN ambassador, NSA under Trump, advocate of multiple wars.','Iraq WMD. "Bomb Iran." North Korea regime change. Opposed Iran deal. Taiwan. Resigned Trump.',['neocon','iraq','war_hawk']),
    _hc('FIG317','Robert Kagan','Figure','foreign','1990s-present','R','None',3,8,
       'Interventionist Intellectual: +2 to foreign Policy. +2 to military. Peek 1 face-down. Risk: Endless wars.','Neocon historian, PNAC co-founder, Brookings fellow, advocate of liberal hegemony.','"Of Paradise and Power." Iraq War advocate. Wife Victoria Nuland. Ukraine architect. FP editorialist.',['neocon','pnc','hegemony']),
    _hc('FIG318','Irving Kristol','Figure','domestic','1950-2000','U','None',3,7,
       'Godfather of Neoconservatism: +2 to foreign Policy. +2 to economic. Peek 1 face-down.','Neocon intellectual, godfather of movement, father of Bill Kristol.','Public Interest magazine. Wall Street Journal editorial. AEI. "Neocon" coined. Trotskyist roots.',['neocon','intellectual','kristol']),
    _hc('FIG319','Victoria Nuland','Figure','foreign','1993-2024','UR','State Dept',5,7,
       'Regime Manager: +2 to intelligence. +2 to foreign Policy. Reveal 1 face-down. Risk: "Fuck the EU" leak.','State Dept official, Ukraine regime change architect, assistant secretary for European affairs.','Maidan 2014 cookies. "Fuck the EU" phone call. Pyatt. Biden Ukraine policy. Kagan wife.',['ukraine','state_dept','neocon']),
    _hc('FIG320','Stansfield Turner','Figure','intelligence','1977-1981','R','CIA',4,6,
       'Halloween Massacre: +2 to intelligence. Reveal 2 face-down. Risk: Morale collapse, mass firings.','CIA director under Carter, slashed clandestine service, reformed intelligence.','Fired 820 covert ops officers. Stansfield "Halloween Massacre." Hated by CIA old guard. SALT II.',['cia','carter','reform']),
    # ── Batch 11 Figures: Media, Tech, Finance & Operatives ──
    _hc('FIG321','Roger Ailes','Figure','social','1996-2016','UR','Media',5,9,
       'Fox News Architect: +3 to media. Control 1 social card. Negate 1 Scandal. Risk: Sexual harassment ouster.','Fox News CEO, Republican media strategist, created conservative media empire.','Nixon, Reagan, Bush Sr media consultant. Built Fox from scratch. Ousted 2016 over harassment. Died 2017.',['media','fox','ailes']),
    _hc('FIG322','Peter Thiel','Figure','economic','1998-present','UR','None',5,8,
       'Contrarian Billionaire: +2 to economic. +2 to intelligence. Peek 1 face-down. Risk: Gawker destruction.','PayPal co-founder, Palantir chairman, Trump donor, libertarian activist.','Palantir CIA contracts. Hulk Hogan lawsuit killed Gawker. Seasteading. NRx connections. Facebook board.',['palantir','paypal','libertarian']),
    _hc('FIG323','Mark Zuckerberg','Figure','social','2004-present','UR','None',4,8,
       'Social Graph: +3 to media. +2 to intelligence. Peek 2 face-down. Risk: Privacy scandals, congressional hearings.','Facebook/Meta founder, built largest social media platform with 3B+ users.','Cambridge Analytica. Russia ads. Section 230. Instagram, WhatsApp acquisitions. Metaverse pivot. Libra/Diem.',['facebook','social_media','surveillance']),
    _hc('FIG324','Larry Fink','Figure','economic','1988-present','UR','BlackRock',6,9,
       'Aladdin: +3 to economic. Peek 3 face-down. Negate 1 financial Scandal. Risk: ESG backlash.','BlackRock CEO, worlds largest asset manager with $10T+ AUM.','Aladdin risk platform. ESG investing pioneer. Fed bailout programs. Vanguard, State Street trio. Too big.',['blackrock','asset_management','esg']),
    _hc('FIG325','Jamie Dimon','Figure','economic','2005-present','R','Wall Street',5,7,
       'Survivor: +2 to economic. Negate 1 financial crash. Reveal 1 face-down. Risk: Too big to fail.','JPMorgan Chase CEO, survived 2008 crisis by acquiring Bear Stearns and WaMu.','London Whale. $6B trading loss. Bailout recipient. Treasury Secretary rumors. Davos regular.',['jpmorgan','wall_street','bailout']),
    _hc('FIG326','Robert Mercer','Figure','economic','2010-2018','UR','None',4,7,
       'Dark Money Quant: +2 to economic. +2 to intelligence. Peek 2 face-down. Risk: Cambridge Analytica exposure.','Renaissance Technologies hedge fund co-CEO, Breitbart funder, Cambridge Analytica backer.','$45M political donations. Breitbart, Bannon. Cambridge Analytica. Facebook data. Climate denial. Rarely speaks.',['mercer','cambridge_analytica','dark_money']),
    _hc('FIG327','Sheldon Adelson','Figure','economic','2000-2021','UR','None',5,7,
       'Casino Kingmaker: +2 to economic. +2 to foreign Policy. Control 1 Figure. Risk: Single-issue donor.','Casino magnate, largest Republican donor, pro-Israel hawk.','$218M 2020 donations. Embassy move Jerusalem. MBS relationship. Macau casinos. Anti-Iran, anti-online gambling.',['adelson','casino','israel']),
    _hc('FIG328','Dick Cheney','Figure','military','2001-2009','L','White House',8,7,
       'Dark Heart: +4 to military. +3 to intelligence. Create 1 fake intelligence. Risk: Iraq quagmire, heart failure.','Vice President, most powerful VP in history, Iraq War architect.','Halliburton CEO. PNAC. Unitary executive. Torture. WMD fabrication. Deferments. Shotgun incident.',['neocon','iraq','halliburton']),
    _hc('FIG329','Donald Rumsfeld','Figure','military','2001-2006','UR','Pentagon',6,6,
       'Old Europe: +3 to military. Negate 2 diplomatic. Risk: Iraq occupation disaster, Abu Ghraib.','Sec Def, Iraq War architect, transformed military doctrine.','PNAC chairman. Aspartame CEO Searle. Afghanistan, Iraq invasions. "Known unknowns." Fired 2006.',['neocon','iraq','pentagon']),
    _hc('FIG330','Lloyd Blankfein','Figure','economic','2006-2018','R','Wall Street',4,6,
       'Vampire Squid: +2 to economic. Peek 1 face-down. Risk: 2008 financial crisis, public hatred.','Goldman Sachs CEO during 2008 crash, called "great vampire squid wrapped around the face of humanity."','CDOs. Abacus deal. SEC $550M fine. TARP recipient. "Doing Gods work." Treasury Secretary rumors.',['goldman','wall_street','cdo']),
    # ── Batch 12 Figures: Military, Operatives, Energy & Asia ──
    _hc('FIG331','Paul Manafort','Figure','intelligence','1976-2018','UR','None',5,7,
       'Fixer: +2 to intelligence. Control 1 foreign Figure. Peek 2 face-down. Risk: FARA indictment, prison.','Political consultant, Trump campaign chair, pro-Russian oligarch lobbyist.','Yanukovych Ukraine. Deripaska. Angola, Philippines, Zaire. $60M from pro-Russian party. Tax fraud, witness tampering. Pardoned.',['manafort','lobbyist','ukraine']),
    _hc('FIG332','Michael Flynn','Figure','intelligence','2012-2018','UR','Pentagon',5,6,
       'Russia Connection: +2 to intelligence. +2 to military. Peek 1 face-down. Risk: Logan Act, FARA.','Trump NSA, retired general, Turkey/Russia lobbying, pleaded guilty to lying to FBI.','RT Moscow dinner with Putin. Flynn Intel Group. Gulen kidnapping plot. Logan Act. Pardoned by Trump.',['flynn','russia','pentagon']),
    _hc('FIG333','Rudy Giuliani','Figure','domestic','1994-2023','UR','None',5,7,
       'Americas Mayor: +2 to social. +2 to intelligence. Control 1 Figure. Risk: Ukraine scandal, disbarment.','NYC mayor, Trump lawyer, Ukraine dirt-digging operative.','9/11 hero mythology. Kerik. Lev Parnas. Fruman. Dominion defamation. Borat scene. Law license suspended.',['giuliani','trump','lobbyist']),
    _hc('FIG334','Lewis Libby','Figure','intelligence','2001-2007','R','White House',4,6,
       'Scooter: +2 to intelligence. Peek 2 face-down. Negate 1 Scandal. Risk: Plame affair, perjury.','Cheney chief of staff, convicted of perjury and obstruction in Valerie Plame CIA leak case.','Plame outed. Judith Miller jailed. Commuted by Bush. Pardoned by Trump 2018. PNAC signatory. Wolfowitz protege.',['libby','plame','neocon']),
    _hc('FIG335','Norman Schwarzkopf','Figure','military','1990-1991','UR','Pentagon',7,6,
       'Stormin Norman: +3 to military. +2 to diplomatic. Negate 1 Middle East Scandal. Risk: Stopped at Baghdad.','Gulf War commander, led coalition to liberate Kuwait from Iraq.','Desert Storm 100-hour ground war. Left Saddam in power. Shiite uprising abandoned. CNN war.',['gulf_war','pentagon','iraq']),
    _hc('FIG336','James Mattis','Figure','military','2010-2018','UR','Pentagon',6,6,
       'Mad Dog: +3 to military. Destroy 1 social card. Peek 1 face-down. Risk: Resigns over Syria withdrawal.','Marine general, CENTCOM commander, Trump Sec Def, resigned over policy differences.','Fallujah. "Be polite, be professional, have a plan to kill everyone." Afghanistan, Syria, ISIS. Opposed torture.',['mattis','pentagon','military']),
    _hc('FIG337','Stanley McChrystal','Figure','military','2003-2010','R','Pentagon',5,6,
       'JSOC Commander: +2 to military. +2 to intelligence. Peek 2 face-down. Risk: Rolling Stone profile, fired.','JSOC and Afghanistan commander, fired after Rolling Stone article mocked Biden.','Iraq JSOC kill/capture. Night raids. COIN strategy. Rolling Stone "Runaway General." Retired.',['jsoc','afghanistan','special_ops']),
    _hc('FIG338','Rex Tillerson','Figure','economic','2017-2018','UR','None',5,6,
       'Exxon Diplomat: +2 to economic. +2 to diplomatic. Peek 1 face-down. Risk: Trump fires via tweet.','ExxonMobil CEO turned Trump Secretary of State, Russia sanctions opponent.','Rosneft deals. Igor Sechin friend. Order of Friendship from Putin. Called Trump "moron." Fired by tweet.',['exxon','russia','oil']),
    _hc('FIG339','Lee Raymond','Figure','economic','1993-2005','UR','None',6,7,
       'Oil Baron: +3 to economic. +2 to military. Negate 1 climate Policy. Risk: Climate denial funding.','ExxonMobil CEO, merged Exxon and Mobil, funded climate denial while scientists confirmed warming.','$400M retirement package. Greenwashing. American Petroleum Institute. Lobbying against Kyoto. Scientists suppressed.',['exxon','oil','climate_denial']),
    _hc('FIG340','Zalmay Khalilzad','Figure','foreign','2001-2021','R','None',4,7,
       'Envoy: +2 to diplomatic. +2 to intelligence. Peek 2 face-down. Risk: Taliban negotiations collapse.','Afghan-born US diplomat, ambassador to Afghanistan, Iraq, UN under Bush and Trump.','UNOCAL Taliban negotiations 1996. Wolfowitz protege. Afghanistan withdrawal architect. Taliban talks Doha.',['neocon','afghanistan','taliban']),
]

EVENTS = [
    _hc('EVT001','American Revolution','Event','domestic','1775-1783','R','None',7,8,
       'Birth of Nation: +5 influence to all founding-era cards.','Colonial independence war.','Taxation without representation. French aid decisive.',['revolution','founding']),
    _hc('EVT002','Civil War','Event','domestic','1861-1865','UR','None',9,7,
       'Brothers War: Destroy 3 domestic cards. Both lose 4 power.','Bloodiest US war, 600K+ dead.','States rights vs federal. Slavery central.',['civil_war','slavery']),
    _hc('EVT003','Assassination of Lincoln','Event','domestic','1865','R','None',5,6,
       'Martyr: +3 influence to all Figure cards.','John Wilkes Booth, Fords Theatre.','First US president assassinated.',['assassination','civil_war']),
    _hc('EVT004','Federal Reserve Act','Event','economic','1913','UR','Federal Reserve',6,9,
       'Money Power: +2 influence to economic cards. Controller gains 1 card/turn.','Created central banking system.','Jekyll Island meeting. Controversial.',['fed','banking','conspiracy']),
    _hc('EVT005','World War I','Event','foreign','1914-1918','R','None',8,7,
       'Great War: All military +2 power. Both lose 2 cards.','Lusitania, Zimmerman telegram.','Trench warfare, chemical weapons. US entered 1917.',['wwi','military']),
    _hc('EVT006','Great Depression','Event','economic','1929-1939','UR','Wall Street',8,6,
       'Crash: All economic cards -3 power for 3 turns.','Stock crash, bank failures.','Smoot-Hawley worsened it. New Deal response.',['economic','crash']),
    _hc('EVT007','Pearl Harbor','Event','military','1941','R','None',7,6,
       'Day of Infamy: Military +4 power next turn.','Japanese surprise attack, 2403 killed.','FDR knew? Debate. US entered WWII.',['wwii','surprise_attack']),
    _hc('EVT008','D-Day','Event','military','1944','R','Pentagon',8,7,
       'Liberation: +5 power to allied military cards.','Normandy landings, 156K troops.','Largest amphibious invasion.',['wwii','invasion']),
    _hc('EVT009','Atomic Bombings','Event','military','1945','L','Pentagon',10,8,
       'Nuclear Age: Destroy ALL cards on field. Both lose 5 influence.','Hiroshima Aug 6, Nagasaki Aug 9.','Debated necessity. Started arms race.',['wwii','nuclear','war_crime']),
    _hc('EVT010','Cuban Missile Crisis','Event','foreign','1962','UR','CIA',9,8,
       '13 Days: Both reveal hands. Highest power wins 3 cards.','Soviets put nukes in Cuba.','JFK blockade. Khrushchev backed down.',['cold_war','nuclear','cuba']),
    _hc('EVT011','JFK Assassination','Event','domestic','1963','L','None',8,10,
       'Lost Leader: Remove highest-power Figure. Reveal 1 Conspiracy.','Dallas, Dealey Plaza, Oswald.','Magic bullet. Warren Commission. Theories persist.',['assassination','conspiracy','jfk']),
    _hc('EVT012','Vietnam War','Event','military','1955-1975','UR','Pentagon',8,6,
       'Quagmire: -2 power to military per turn. Both lose 2 influence.','58K US dead, millions Vietnamese.','Gulf of Tonkin possibly staged. My Lai.',['vietnam','war','protest']),
    _hc('EVT013','Moon Landing','Event','domestic','1969','R','None',7,8,
       'Giant Leap: +4 influence. Opponent shows hand 1 turn.','Apollo 11, Armstrong, Aldrin.','Won space race. Studio conspiracy debunked.',['space','cold_war']),
    _hc('EVT014','Watergate Break-in','Event','domestic','1972','UR','FBI',6,8,
       'Cover-Up: Reveal all face-down cards. Scandal cards double power.','Nixon campaign burgled DNC.','Deep Throat (Mark Felt). Tapes. Nixon resigned.',['watergate','scandal','nixon']),
    _hc('EVT015','Iran Hostage Crisis','Event','foreign','1979-1981','R','CIA',6,6,
       '444 Days: -3 influence to foreign cards. Opponent gains 2 cards.','US embassy Tehran, 52 hostages.','CIA overthrew Iran 1953. Blowback.',['iran','cia','blowback'],'Iran'),
    _hc('EVT016','Chernobyl','Event','foreign','1986','R','KGB',7,5,
       'Meltdown: All cards -2 power for 2 turns. Reveal 1 face-down.','Nuclear reactor explosion, Pripyat.','Soviet cover-up delayed evacuation.',['nuclear','coverup'],'USSR'),
    _hc('EVT017','Berlin Wall Falls','Event','foreign','1989','R','None',6,7,
       'Freedom: Remove one authoritarian Figure. +3 influence.','East Germany opens borders.','End of Cold War era.',['cold_war','freedom'],'Germany'),
    _hc('EVT018','Gulf War','Event','military','1990-1991','R','Pentagon',7,6,
       'Desert Storm: +3 power to military for 2 turns.','US-led coalition ousts Iraq from Kuwait.','Highway of Death. Depleted uranium.',['gulf_war','iraq']),
    _hc('EVT019','9/11 Attacks','Event','domestic','2001','L','None',10,10,
       '9/11: Destroy 4 cards. Both lose 5 influence. Reveal all Conspiracies.','Twin towers, Pentagon, Flight 93. 2977 dead.','Building 7 debated. NORAD stand-down questioned.',['911','terrorism','conspiracy']),
    _hc('EVT020','Iraq War','Event','foreign','2003-2011','UR','Pentagon',7,5,
       'WMD Hunt: -3 influence. Reveal 1 face-down/turn for 3 turns.','US invasion based on WMD claims, none found.','Yellowcake, Curveball, Plame leak.',['iraq','wmd','war']),
    _hc('EVT021','2008 Financial Crisis','Event','economic','2008','UR','Wall Street',8,7,
       'Too Big to Fail: Economic -4 power. Both lose 3 cards.','Subprime mortgage, Lehman, TARP.','Bankers bailed out, no execs jailed.',['economic','crash','bailout']),
    _hc('EVT022','Snowden Leaks','Event','intelligence','2013','UR','NSA',7,9,
       'Mass Surveillance Revealed: All face-down cards revealed.','NSA bulk data collection exposed.','PRISM, XKeyscore. Snowden exiled in Russia.',['nsa','surveillance','whistleblower']),
    _hc('EVT023','COVID-19 Pandemic','Event','domestic','2020-2022','UR','WHO',8,7,
       'Lockdown: All cards -2 power for 3 turns. WHO +2 influence.','Global pandemic, lockdowns, vaccines.','Lab leak vs natural origin debated.',['covid','pandemic'],'Global'),
    _hc('EVT024','January 6 Capitol Riot','Event','domestic','2021','UR','None',6,7,
       'Insurrection: Remove one Policy card. Both lose 2 influence.','Capitol breach during certification.','Election denial, Trump impeachment #2.',['jan6','insurrection']),
    _hc('EVT025','Ukraine Invasion','Event','foreign','2022','UR','None',8,7,
       'Special Operation: -3 influence to Russian cards. +2 to NATO.','Russia invades Ukraine.','Bucha allegations. NATO expansion debate.',['ukraine','russia','nato'],'Global'),
    _hc('EVT026','Trail of Tears','Event','domestic','1830-1838','R','White House',6,3,
       'Forced March: Remove all native-tagged cards. -3 influence.','Jackson\'s Indian Removal Act.','4000+ Cherokee died on forced relocation.',['native','trail_of_tears','jackson']),
    _hc('EVT027','Mexican-American War','Event','foreign','1846-1848','U','White House',6,5,
       'Manifest Destiny: +3 influence to all territorial cards.','US seized CA, NV, UT, AZ, NM from Mexico.','Polk provoked war. Thoreau jailed for tax protest.',['mexico','manifest_destiny']),
    _hc('EVT028','Emancipation Proclamation','Event','domestic','1863','R','White House',6,8,
       'Freedom: Destroy all slavery-tagged cards. +3 influence to social.','Lincoln freed Confederate slaves.','Limited scope, symbolic power. 13th Amendment followed.',['civil_war','slavery','lincoln']),
    _hc('EVT029','Spanish Flu','Event','domestic','1918-1920','R','None',7,4,
       'Pandemic: All cards -2 power for 2 turns. 50M dead globally.','H1N1 influenza pandemic.','Killed more than WWI. Wilson got it at Versailles.',['pandemic','flu','wwi'],'Global'),
    _hc('EVT030','Wall Street Crash of 1929','Event','economic','1929','UR','Wall Street',8,5,
       'Black Tuesday: All economic cards lose 5 power. Start of Depression.','Stock market collapse.','Oct 24 and Oct 29. $30B lost. Margin calls.',['crash','depression','wall_street']),
    _hc('EVT031','Dust Bowl','Event','domestic','1930-1936','U','None',5,3,
       'Ecological Disaster: Economic cards -2 power for 3 turns.','Severe drought, soil erosion.','Okie migration to California. Steinbeck\'s Grapes of Wrath.',['dust_bowl','migration','depression']),
    _hc('EVT032','Japanese Internment','Event','domestic','1942-1945','R','White House',6,3,
       'Internment: Remove all Japan-region cards. -3 influence.','FDR EO 9066, 120K Japanese-Americans imprisoned.','Supreme Court upheld in Korematsu. Reagan apologized 1988.',['internment','racism','wwii']),
    _hc('EVT033','Korean War','Event','military','1950-1953','R','Pentagon',7,6,
       'Forgotten War: Military +2 power. Both lose 2 cards. Stalemate.','North invaded South, UN/US intervened.','38th parallel. MacArthur fired. MIA/POW issues.',['korea','cold_war','un']),
    _hc('EVT034','McCarthy Hearings','Event','domestic','1950-1954','R','Congress',5,6,
       'Red Scare: Remove one communist-tagged card. Risk: Backlash.','Sen. McCarthy, communist witch hunt.','Army-McCarthy hearings. "Have you no decency?" Censured.',['mccarthy','red_scare','cold_war']),
    _hc('EVT035','Sputnik Launch','Event','foreign','1957','R','KGB',5,7,
       'Space Race: +3 influence to Soviet cards. US must respond.','First satellite, Soviet space first.','US panic, created NASA, NDEA. ICBM implications.',['space','cold_war','soviet'],'USSR'),
    _hc('EVT036','Bay of Pigs Invasion','Event','foreign','1961','R','CIA',5,4,
       'Failed Invasion: CIA -3 influence. Castro +2 power.','CIA-trained exiles invaded Cuba, failed in 3 days.','JFK inherited plan, denied air support. Led to Missile Crisis.',['cia','cuba','failure'],'Cuba'),
    _hc('EVT037','MLK "I Have a Dream"','Event','social','1963','R','None',6,9,
       'Dream Speech: +4 influence to all social cards. Nullify one racial Scandal.','March on Washington, 250K people.','MLK at Lincoln Memorial. Civil Rights Act 1964 followed.',['civil_rights','mlk','march']),
    _hc('EVT038','MLK Assassination','Event','domestic','1968','UR','None',7,8,
       'Martyr: Remove MLK card. +5 influence to all social cards. Riots.','Memphis, James Earl Ray.','Ray recanted confession. King family doubted lone gunman.',['assassination','mlk','civil_rights']),
    _hc('EVT039','RFK Assassination','Event','domestic','1968','R','None',6,7,
       'Lost Hope: Remove RFK card. Social cards -2 influence.','LA Ambassador Hotel, after primary win.','Sirhan Sirhan. Conspiracy: second gunman theories.',['assassination','rfk','conspiracy']),
    _hc('EVT040','Woodstock','Event','social','1969','U','None',3,6,
       'Counterculture: +2 influence to social cards. Military -1 power.','400K person music festival.','Anti-war era symbol. Hippie movement peak.',['woodstock','counterculture','vietnam']),
    _hc('EVT041','Kent State Massacre','Event','domestic','1970','R','None',5,5,
       'Four Dead in Ohio: -3 influence to government. +2 to protest cards.','National Guard shot students, 4 dead.','Anti-war protest. Crosby Stills Nash Young song.',['kent_state','protest','vietnam']),
    _hc('EVT042','Watergate Hearing','Event','domestic','1973','UR','Congress',7,8,
       'The Tapes: Reveal all face-down government cards. Nixon -5 influence.','Senate Watergate Committee televised.','"What did the president know and when did he know it?"',['watergate','nixon','congress']),
    _hc('EVT043','Three Mile Island','Event','domestic','1979','R','None',5,4,
       'Nuclear Accident: Nuclear cards -3 power for 3 turns.','Partial meltdown, Pennsylvania.','No direct deaths. Killed nuclear power expansion.',['nuclear','accident','energy']),
    _hc('EVT044','Iran-Contra Revelation','Event','foreign','1986','UR','CIA',6,7,
       'Arms Scandal: CIA -3 influence. Reveal 2 face-down cards.','Lebanon newspaper exposed arms-for-hostages.','North shredded documents. Tower Commission.',['iran_contra','cia','scandal']),
    _hc('EVT045','Fall of Saigon','Event','foreign','1975','R','None',6,5,
       'Defeat: US military -4 influence. Helicopter evac from embassy.','North Vietnam took Saigon.','Vietnam unified communist. Boat people exodus.',['vietnam','defeat','cold_war'],'Vietnam'),
    _hc('EVT046','Oklahoma City Bombing','Event','domestic','1995','R','None',7,5,
       'Domestic Terror: Destroy 2 domestic cards. Both lose 2 influence.','Timothy McVeigh, 168 dead.','Retaliation for Waco. Anti-government militia movement.',['terrorism','okc','militia']),
    _hc('EVT047','Dot-Com Crash','Event','economic','2000-2002','R','Wall Street',5,5,
       'Bubble Burst: Tech/economic cards -3 power for 2 turns.','Internet stock bubble popped.','Pets.com, Enron followed. $5T lost.',['economic','crash','tech']),
    _hc('EVT048','Hurricane Katrina','Event','domestic','2005','UR','None',7,4,
       'Disaster: Destroy 2 domestic cards. Government -3 influence.','Levees failed, New Orleans flooded.','1800+ dead. FEMA failure. Racial disparities exposed.',['katrina','disaster','fema']),
    _hc('EVT049','Osama bin Laden Raid','Event','military','2011','UR','CIA',8,7,
       'Geronimo: Remove bin Laden card. CIA +3 influence.','SEAL Team 6, Abbottabad compound.','Buried at sea. Pakistan unaware? Code name Geronimo.',['bin_laden','seal','cia'],'Pakistan'),
    _hc('EVT050','Arab Spring','Event','foreign','2010-2012','R','None',6,6,
       'Uprising: Remove one authoritarian Figure. Both discard 2.','Tunisia, Egypt, Libya, Syria.','Social media fueled. Mixed outcomes. Syria civil war.',['revolution','middle_east'],'Global'),
    _hc('EVT051','Boston Marathon Bombing','Event','domestic','2013','R','None',5,4,
       'Terror Strike: Destroy 1 domestic card. -2 influence.','Chechen brothers, 3 dead, 260 wounded.','Manhunt, lockdown. One killed, one captured.',['terrorism','boston','chechen']),
    _hc('EVT052','Brexit Vote','Event','foreign','2016','R','None',5,6,
       'Brexit: Remove all EU-tagged cards from UK region. Economic -2.','UK voted to leave EU.','Cambridge Analytica involvement. Populist wave.',['brexit','uk','populist'],'UK'),
    _hc('EVT053','2016 Election (Russian Interference)','Event','domestic','2016','UR','KGB',7,8,
       'Meddling: KGB +3 influence. Reveal 3 face-down cards. Both lose 2 influence.','Russian election interference, social media ops.','Mueller Report. IRA troll farm. WikiLeaks DNC emails.',['russia','election','interference']),
    _hc('EVT054','Impeachment of Trump (1st)','Event','domestic','2019','R','Congress',5,6,
       'Impeached: Trump -3 influence. Senate acquits. No removal.','Ukraine quid pro quo.','Only 3rd president impeached. Acquitted along party lines.',['trump','impeachment','ukraine']),
    _hc('EVT055','Impeachment of Trump (2nd)','Event','domestic','2021','R','Congress',5,6,
       'Impeached Again: Trump -3 influence. Jan 6 aftermath.','Incitement of insurrection.','First ever double-impeached president. Acquitted again.',['trump','impeachment','jan6']),
    _hc('EVT056','Afghanistan Withdrawal','Event','military','2021','UR','Pentagon',6,4,
       'Retreat: Military -3 influence. Taliban returns. Both lose 2 cards.','US withdrew, Taliban took Kabul.','20-year war ended. Chaos at airport. ISIS-K bombing.',['afghanistan','taliban','defeat'],'Afghanistan'),
    _hc('EVT057','Israel-Hamas War','Event','foreign','2023-present','UR','Mossad',8,7,
       'Gaza War: Destroy 2 Middle East cards. Both lose 3 influence.','Oct 7 attack, Israeli response.','40K+ Gaza dead. Hostages. ICC arrest warrants. Protests.',['israel','gaza','hamas'],'Israel'),
    _hc('EVT058','Assassination Attempt on Trump','Event','domestic','2024','R','None',6,6,
       'Butler PA: Trump +2 power. Secret Service -3 influence.','Shot at rally, ear wounded, 1 dead.','Thomas Crooks. Security failures. Conspiracy theories.',['trump','assassination','secret_service']),
    _hc('EVT059','Whiskey Rebellion','Event','domestic','1791-1794','C','None',4,4,
       'Tax Revolt: +1 power to domestic cards. Hamilton suppresses.','First tax protest under new Constitution.','Washington led troops. Tax on whiskey. Frontier resistance.',['whiskey','tax','rebellion']),
    _hc('EVT060','Louisiana Purchase','Event','domestic','1803','R','White House',6,6,
       'Expansion: +3 influence to all territorial cards. Double US size.','Jefferson bought from Napoleon for $15M.','Constitutional stretch. Lewis & Clark expedition.',['expansion','jefferson','territory']),
    _hc('EVT061','War of 1812','Event','foreign','1812-1815','U','White House',5,5,
       'Second Revolution: Military +2 power. White House burned.','US vs Britain, DC burned, Star-Spangled Banner.','New Orleans victory after treaty signed. Trade restrictions cause.',['war_1812','britain','burning']),
    _hc('EVT062','Mexican Cession','Event','foreign','1848','U','White House',5,5,
       'Territory Gained: +2 influence to Western cards.','Treaty of Guadalupe Hidalgo, CA/NV/UT/AZ/NM.','$15M for 55% of Mexico. Gadsden Purchase followed.',['mexico','territory','manifest_destiny']),
    _hc('EVT063','Gold Rush','Event','domestic','1848-1855','U','None',5,5,
       'Gold Fever: +2 power to economic cards. +1 card per turn for 2 turns.','California gold discovery, 300K migration.','SF grew from 200 to 36K. Native American genocide.',['gold_rush','california','migration']),
    _hc('EVT064','Pullman Strike','Event','domestic','1894','U','None',4,5,
       'Labor Strike: +2 power to social cards. Military -1 influence.','Railway workers struck, federal troops broke it.','Cleveland sent troops. Debs jailed. Labor Day created.',['labor','strike','pullman']),
    _hc('EVT065','Triangle Shirtwaist Fire','Event','domestic','1911','U','None',4,5,
       'Factory Fire: Social cards +2 influence. Labor laws +3 power.','146 garment workers died, doors locked.','Led to safety regulations. Immigrant women victims.',['labor','fire','safety']),
    _hc('EVT066','Sedition Act of 1918','Event','domestic','1918','U','Congress',4,5,
       'Censorship: Negate one social card. Risk: Backlash.','Criminalized anti-war speech during WWI.','Debs imprisoned. Repealed 1920. Wilson wartime suppression.',['wwi','censorship','sedition']),
    _hc('EVT067','Bonus Army March','Event','domestic','1932','U','None',4,4,
       'Veterans Protest: +2 power to social cards. Military -2 influence.','WWI veterans marched for bonuses, evicted by Army.','MacArthur, Patton, Eisenhower led eviction. Shantytown burned.',['depression','veterans','macarthur']),
    _hc('EVT068','Rosenberg Execution','Event','domestic','1953','R','FBI',6,5,
       'Atomic Spies: Remove 2 communist-tagged cards. FBI +2 power.','Julius and Ethel Rosenberg executed for atomic espionage.','Debate: guilty or scapegoats? Ethel\'s role minimal. Venona confirmed Julius.',['cold_war','espionage','rosenberg']),
    _hc('EVT069','Suez Crisis','Event','foreign','1956','R','None',6,6,
       'Canal Crisis: +2 power to all Middle East cards. NATO -2 influence.','Egypt nationalized Suez, UK/France/Israel invaded, US opposed.','Eisenhower forced withdrawal. Oil crisis. Cold War dynamics.',['suez','egypt','oil'],'Egypt'),
    _hc('EVT070','Cuban Embargo','Event','foreign','1960-present','U','White House',4,5,
       'Blockade: Cuba cards -3 power. Economic -1 influence.','US embargo against Cuba, longest in history.','Castro survived 10 presidents. Obama thaw, Trump reversed.',['cuba','embargo','cold_war'],'Cuba'),
    # ── Global Events ──
    _hc('EVT071','French Revolution','Event','foreign','1789-1799','UR','None',8,7,
       'Liberty Equality Fraternity: Destroy 3 monarchy cards. +3 to revolutionary cards.','Overthrew French monarchy, Reign of Terror followed.','Napoleon rose from chaos. Inspired revolutions worldwide.',['france','revolution','terror'],'France'),
    _hc('EVT072','Haitian Revolution','Event','foreign','1791-1804','R','None',6,7,
       'Slave Revolt: Destroy all slavery cards. +3 to revolutionary.','Only successful slave revolt in history.','Toussaint Louverture led. France demanded reparations until 1947.',['haiti','revolution','slavery'],'Haiti'),
    _hc('EVT073','Opium Wars','Event','foreign','1839-1842','R','British Crown',6,5,
       'Gunboat Diplomacy: +3 power to military. China -3 influence.','UK forced China to buy opium at gunpoint.','Hong Kong ceded. Century of humiliation.',['uk','china','opium'],'China'),
    _hc('EVT074','Russian Revolution','Event','foreign','1917','UR','KGB',8,8,
       'Red October: Destroy all monarchy cards. Communist +5 power.','Bolsheviks overthrew Tsar, created USSR.','Romanov family executed. Cold War origins.',['russia','revolution','communist'],'USSR'),
    _hc('EVT075','Holodomor','Event','foreign','1932-1933','UR','KGB',7,3,
       'Engineered Famine: Destroy 3 agricultural cards. Soviet -3 influence.','Stalin engineered famine in Ukraine, 4M+ dead.','Denied by USSR for decades. Holodomor = genocide debate.',['ukraine','famine','soviet'],'USSR'),
    _hc('EVT076','Partition of India','Event','foreign','1947','R','British Crown',7,5,
       'Divide and Conquer: Destroy 2 religious cards. Both lose 3 influence.','British split India into India and Pakistan, 1M+ died.','Mass migration, communal violence. Kashmir dispute.',['india','pakistan','british_crown'],'India'),
    _hc('EVT077','Hungarian Uprising','Event','foreign','1956','UR','KGB',7,5,
       'Crushed Revolt: Destroy 2 revolutionary cards. Soviet +3 power.','Hungarians rebelled against Soviet occupation, crushed by tanks.','KGB code name Operation Whirlwind. 200K fled west. Kadar installed.',['hungary','cold_war','soviet'],'Hungary'),
    _hc('EVT078','Soviet-Afghan War','Event','foreign','1979-1989','UR','KGB',7,5,
       'Bear Trap: Military -2 power. Revolutionary +3. Both lose 3.','Soviet quagmire in Afghanistan, US armed mujahideen.','Stinger missiles. Bin Laden forged. Soviet collapse accelerated.',['afghanistan','cold_war','mujahideen'],'Afghanistan'),
    _hc('EVT079','Iranian Revolution','Event','foreign','1979','UR','None',7,7,
       'Islamic Uprising: Remove all US-backed cards from Middle East. Religious +3.','Shah overthrown, Khomeini took power.','Hostage crisis 444 days. CIA blowback. Regional shift.',['iran','revolution','islamic'],'Iran'),
    _hc('EVT080','Berlin Wall Fall','Event','foreign','1989','UR','None',6,8,
       'Tear Down This Wall: Destroy all communist barriers. +4 influence to European.','Wall fell, Cold War effectively ended.','Gorbachev glasnost. East Germany collapsed. Reunification.',['germany','cold_war','freedom'],'Germany'),
    _hc('EVT081','Tiananmen Square','Event','foreign','1989','UR',' CCP',7,4,
       'Tank Man: CCP -4 influence. Destroy 2 social cards. Revolution cards banned.','Chinese pro-democracy protests crushed.','Unknown rebel stood before tanks. Internet censorship.',['china','ccp','protest'],'China'),
    _hc('EVT082','Rwandan Genocide','Event','foreign','1994','UR','None',8,3,
       '100 Days: Destroy 5 African cards. UN -5 influence. Both lose 4.','800K+ Tutsis killed in 100 days.','UN withdrew. Belgium colonial roots. "Never again" again.',['rwanda','genocide','un'],'Rwanda'),
    _hc('EVT083','Syrian Civil War','Event','foreign','2011-present','L','None',8,4,
       'Carnage: Destroy 3 Middle East cards. Refugee cards +5. Both lose 4.','Assad vs rebels, ISIS, foreign intervention.','500K+ dead. 6M refugees. Chemical weapons. Proxy war.',['syria','refugee','isis'],'Syria'),
    _hc('EVT084','Hong Kong Protests','Event','foreign','2019-2020','R','None',5,7,
       'Umbrella Revolution: +3 to social. CCP -2 influence. Risk: National Security Law.','Hong Kong pro-democracy protests crushed by Beijing.','Extradition bill sparked it. NSL 2020 ended autonomy. Leaders jailed.',['hong_kong','ccp','protest'],'China'),
    _hc('EVT085','Crimea Annexation','Event','foreign','2014','UR','Kremlin',7,6,
       'Putin\'s Grab: +3 power to Russian cards. Ukraine -3 influence.','Russia annexed Crimea, first land grab in Europe since WWII.','Sanctions. Little Green Men. Referendum disputed.',['russia','ukraine','putin'],'Ukraine'),
    _hc('EVT086','Russia-Ukraine War','Event','foreign','2022-present','L','Kremlin',9,7,
       'Special Military Operation: Both lose 5 influence. Sanctions -3 to Russian economy.','Full-scale invasion of Ukraine, largest European war since WWII.','Zelensky resistance. NATO expansion. Energy crisis.',['russia','ukraine','war','sanctions'],'Ukraine'),
    # ── New Events ──
    _hc('EVT087','Haymarket Affair','Event','domestic','1886','R','None',5,6,
       'Bomb Thrown: +3 to labor cards. Police -2 influence. Risk: Red Scare.','Chicago labor protest bombing, 7 police killed.','4 anarchists hanged on flimsy evidence. May Day origin.',['labor','haymarket','anarchist']),
    _hc('EVT088','Sacco and Vanzetti','Event','domestic','1920-1927','R','None',5,5,
       'Red Scare Trial: -2 to social. Immigrant -3 influence. Risk: Injustice.','Italian anarchists executed on dubious murder charges.','Worldwide protests. 50 years later: "unjust."',['red_scare','anarchist','injustice']),
    _hc('EVT089','Tulsa Race Massacre','Event','domestic','1921','UR','None',7,4,
       'Black Wall Street Burned: Destroy 3 economic cards. Social -4. Reveal 2.','White mob destroyed prosperous Greenwood district, Tulsa.','300+ dead, 10K homeless. Planes dropped bombs. Covered up for decades.',['tulsa','racism','massacre']),
    _hc('EVT090','Wounded Knee Massacre','Event','domestic','1890','R','None',6,3,
       'Last Indian War: Destroy all native-tagged cards. -4 influence.','US Army killed 300+ Lakota at Wounded Knee.','Ghost Dance fear. Medals of Honor given. Apology 2024.',['native','massacre','lakota']),
    _hc('EVT091','Stonewall Riots','Event','social','1969','R','None',5,7,
       'Gay Liberation: +3 to social. +2 influence to civil rights cards.','Police raid on Stonewall Inn sparked LGBTQ rights movement.','Marsha P. Johnson, Sylvia Rivera. Pride month origin.',['stonewall','lgbtq','civil_rights']),
    _hc('EVT092','Kent State Shooting','Event','domestic','1970','R','None',5,5,
       'Four Dead in Ohio: -3 to military. Social +2. Anti-war +3.','National Guard killed 4 students protesting Vietnam War.','"Tin soldiers and Nixon coming." Crosby Stills Nash Young.',['kent_state','vietnam','protest']),
    _hc('EVT093','Bleeding Kansas','Event','domestic','1854-1861','R','None',5,4,
       'Border War: Destroy 2 domestic cards. Both lose 2. Civil War precursor.','Pro/anti-slavery violence in Kansas territory.','John Brown. Pottawatomie massacre. Popular sovereignty failed.',['bleeding_kansas','slavery','civil_war']),
    _hc('EVT094','Dresden Firebombing','Event','foreign','1945','UR','None',7,4,
       'Firestorm: Destroy 3 foreign cards. Both lose 3. Military +2.','Allied firebombing of Dresden, 25K+ civilians killed.','Controversial: military target or terror bombing? Slaughterhouse Five.',['wwii','dresden','firebombing'],'Germany'),
    _hc('EVT095','Roswell Incident','Event','domestic','1947','R','None',4,7,
       'Weather Balloon: +2 to intelligence. Reveal 2 face-down. Risk: Conspiracy.','Alleged UFO crash in New Mexico, military cover-up.','Project Mogul. Weather balloon vs flying saucer. Conspiracy culture born.',['roswell','ufo','coverup']),
    _hc('EVT096','Shays Rebellion','Event','domestic','1786-1787','C','None',3,5,
       'Armed Revolt: +2 to social. Economic -1. Constitution catalyst.','Debt-ridden farmers rebelled in Massachusetts.','Crushed by militia. Led to Constitutional Convention.',['shays','rebellion','constitution']),
    # ── Batch 2 Events ──
    _hc('EVT097','Boston Tea Party','Event','domestic','1773','R','None',4,7,
       'No Taxation: +2 to social. Destroy 1 economic card. +3 to revolutionary.','Colonists dumped British tea in Boston Harbor.','Sons of Liberty. Intolerable Acts followed. Revolution catalyst.',['boston','tea_party','revolution']),
    _hc('EVT098','Boston Massacre','Event','domestic','1770','U','None',3,6,
       'First Blood: +2 to revolutionary. British -2 influence. Risk: Propaganda.','British soldiers killed 5 colonists in Boston.','Crispus Attucks. Paul Revere engraving. Propaganda tool.',['boston','massacre','revolution']),
    _hc('EVT099','Spanish Civil War','Event','foreign','1936-1939','UR','None',7,6,
       'Pre-WWII: Destroy 3 foreign cards. Fascist +2, Communist +2. Risk: Franco wins.','Republicans vs Nationalists, dress rehearsal for WWII.','Guernica bombing. International Brigades. Orwell fought. Franco won.',['spain','civil_war','franco'],'Spain'),
    _hc('EVT100','Great Leap Forward','Event','foreign','1958-1962','L',' CCP',9,3,
       'Famine: Destroy 5 domestic cards. All cards -3. 30-55M dead.','Mao forced industrialization and collectivization, catastrophic famine.','Backyard furnaces. Sparrows killed. Worst man-made famine.',['mao','china','famine'],'China'),
    _hc('EVT101','Cultural Revolution','Event','foreign','1966-1976','UR',' CCP',7,4,
       'Purge: Destroy 4 social cards. Communist +3. Risk: Intellectuals -5.','Mao purge of opponents, Red Guards terror.','Struggle sessions. Destroyed cultural heritage. Deng reversed.',['mao','china','red_guards'],'China'),
    _hc('EVT102','Homestead Strike','Event','domestic','1892','R','None',5,5,
       'Labor War: +3 to labor. Military -2. Destroy 1 economic card.','Steel workers struck at Homestead, PA, battled Pinkertons.','Frick, Carnegie. 9 strikers, 7 Pinkertons killed. State militia crushed it.',['labor','homestead','carnegie']),
    _hc('EVT103','Ludlow Massacre','Event','domestic','1914','R','None',5,4,
       'Tent Colony: Destroy 2 social cards. Military -3. Labor +3.','National Guard attacked striking coal miners, 20+ dead including women/children.','John D. Rockefeller owned mines. "Death Special" armored car.',['labor','ludlow','rockefeller']),
    _hc('EVT104','Emmett Till Murder','Event','domestic','1955','UR','None',6,5,
       'Open Casket: +4 to social. Civil rights +3. Reveal 2 face-down.','14-year-old Black boy lynched in Mississippi for whistling at a woman.','Mother insisted open casket. Jet magazine. Catalyzed civil rights movement.',['emmett_till','lynching','civil_rights']),
    _hc('EVT105','Dred Scott Decision','Event','domestic','1857','UR','Supreme Court',5,3,
       'Not a Citizen: -3 to social. Slavery cards +3. Risk: Civil War accelerated.','Supreme Court ruled Blacks not citizens, slavery cannot be banned in territories.','Taney court. Overturned by 13th/14th Amendments. Lincoln response.',['dred_scott','slavery','supreme_court']),
    _hc('EVT106','Burning of Washington','Event','domestic','1814','R','British Crown',5,4,
       'Capital Burned: Domestic -3. British +2. White House torched.','British burned White House and Capitol during War of 1812.','Dolley Madison saved portraits. Tornado drove British out.',['war_1812','british_crown','burning']),
    # ── Batch 3 Events ──
    _hc('EVT107','Salem Witch Trials','Event','domestic','1692','U','None',4,3,
       'Witch Hunt: Destroy 3 social cards. Reveal 2 face-down. Risk: Mass hysteria.','20 executed in colonial Massachusetts, spectral evidence.','Gallows Hill. Cotton Mather. Pressed to death. Apology 1697.',['salem','witch','hysteria']),
    _hc('EVT108','Bacon Rebellion','Event','domestic','1676','U','None',3,4,
       'Frontier Revolt: +2 to domestic. Destroy 1 government card. Risk: Slavery hardened.','Virginia settlers rebelled against Berkeley, burned Jamestown.','Nathaniel Bacon died, rebellion collapsed. Elite pivoted to racial slavery.',['bacon','jamestown','virginia']),
    _hc('EVT109','Stono Rebellion','Event','domestic','1739','U','None',3,3,
       'Slave Revolt: +2 to military. Destroy 1 slavery card. Risk: Harsher laws.','Largest slave rebellion in British North America, 60+ killed.','Jemmy led. March to Florida. Negro Act restricted freedoms further.',['stono','slavery','rebellion']),
    _hc('EVT110','Fall of Constantinople','Event','foreign','1453','UR','None',8,6,
       'End of Byzantium: Destroy 3 European cards. Ottoman +4 power. Trade routes shift.','Ottoman Turks captured Constantinople, ended Roman Empire.','Mehmed II. Cannon. Scholars fled west, fueled Renaissance.',['ottoman','byzantine','constantinople'],'Turkey'),
    _hc('EVT111','Fall of Rome','Event','foreign','476 AD','UR','None',7,3,
       'Dark Ages: Destroy 4 European cards. All cards -2. Barbarian +3.','Western Roman Empire fell to Germanic tribes.','Odoacer deposed Romulus Augustulus. 1000-year empire ended.',['rome','barbarian','collapse'],'Italy'),
    _hc('EVT112','Magna Carta','Event','foreign','1215','R','None',5,8,
       'Rule of Law: +3 to social. Negate 1 monarchy card. +2 to Policy.','English barons forced King John to sign, limited royal power.','"No free man shall be imprisoned." Foundation of constitutional law.',['uk','magna_carta','law'],'UK'),
    _hc('EVT113','Black Death','Event','foreign','1347-1351','L','None',9,2,
       'Plague: Destroy 5 cards. All cards -3. 75-200M dead in Europe.','Bubonic plague pandemic killed 30-60% of Europe.','Fleas, rats. Flagellants. Anti-Jewish pogroms. Feudalism weakened.',['plague','pandemic','europe'],'Europe'),
    _hc('EVT114','Crusades','Event','foreign','1095-1291','UR','None',7,5,
       'Holy War: +3 to military. +2 to religious. Destroy 2 Middle East cards. Risk: Blowback.','Christian holy wars to recapture Jerusalem from Muslims.','9 crusades. Saladin. Childrens Crusade. Trade routes opened.',['crusades','jerusalem','religious'],'Israel'),
    _hc('EVT115','Little Bighorn','Event','domestic','1876','R','None',5,4,
       'Custers Last Stand: Destroy 2 US military cards. Native +4 power. Risk: Retaliation.','Lakota and Cheyenne wiped out Custers 7th Cavalry.','Greed for gold in Black Hills. Sitting Bull, Crazy Horse. US revenge intensified.',['little_bighorn','custer','native']),
    _hc('EVT116','Reconstruction','Event','domestic','1865-1877','R','Congress',5,6,
       'Rebuild: +3 to social. Military +1. Risk: Compromise of 1877 ends it.','Post-Civil War rebuilding of South, freedmen rights.','Freedmens Bureau. 13th-15th Amendments. Sharecropping. Jim Crow replaced it.',['reconstruction','freedmen','civil_war']),
    # ── Batch 4 Events ──
    _hc('EVT117','Taiping Rebellion','Event','foreign','1850-1864','L','None',9,3,
       'Heavenly Kingdom: Destroy 5 domestic cards. 20-30M dead. Risk: Dynasty weakened.','Hong Xiuquan claimed to be Jesus brother, led massive civil war in China.','Nanjing captured. 20M+ dead, deadliest civil war ever. Qing weakened.',['china','rebellion','taiping'],'China'),
    _hc('EVT118','Boxer Rebellion','Event','foreign','1899-1901','R','None',6,4,
       'Anti-Foreign: Destroy 3 foreign cards. China -3 influence. Risk: Western retaliation.','Chinese secret society attacked foreigners, crushed by 8-nation alliance.','"Support Qing, destroy foreigners." Siege of Legation Quarter. Indemnity imposed.',['china','boxer','anti_foreign'],'China'),
    _hc('EVT119','Meiji Restoration','Event','foreign','1868-1912','UR','None',7,8,
       'Modernize: +4 to economic. +3 to military. +2 to domestic.','Japan transformed from feudal to modern industrial power.','Samurai abolished. Constitution 1889. Defeated Russia 1905. WWI ally.',['japan','modernization','meiji'],'Japan'),
    _hc('EVT120','Camp David Accords','Event','foreign','1978','R','None',5,8,
       'Peace Treaty: +3 to diplomatic. Negate 1 Middle East conflict. Both +2 influence.','Carter brokered peace between Egypt and Israel.','Sadat, Begin. Egypt recognized Israel. Sinai returned. Sadat assassinated.',['camp_david','peace','egypt'],'Egypt'),
    _hc('EVT121','Prague Spring','Event','foreign','1968','UR','None',6,5,
       'Socialism with a Face: +3 to social. Destroy 2 communist cards. Risk: Soviet invasion.','Czechoslovakia reform movement crushed by Warsaw Pact tanks.','Dubcek. 200K troops. Jan Palach self-immolation. Velvet Revolution 1989.',['prague','czech','soviet'],'Czechoslovakia'),
    _hc('EVT122','Thirty Years War','Event','foreign','1618-1648','UR','None',8,4,
       'Religious War: Destroy 4 European cards. All cards -2. 8M dead.','Catholic vs Protestant war devastated Europe.','Peace of Westphalia. Modern state system. Germany lost 1/3 population.',['europe','religion','westphalia'],'Germany'),
    _hc('EVT123','Hundred Years War','Event','foreign','1337-1453','R','None',6,5,
       'Long War: Military +2. Both lose 3 cards. English expelled from France.','England vs France, 116 years of intermittent war.','Joan of Arc. Agincourt. Longbow. English lost all but Calais.',['england','france','joan_of_arc'],'France'),
    _hc('EVT124','Armenian Genocide','Event','foreign','1915-1917','UR','None',7,2,
       'First Genocide: Destroy 4 civilian cards. Ottoman -5 influence. Risk: Denial.','Ottoman Empire killed 1.5M Armenians during WWI.','Death marches. Talat Pasha. Turkey still denies. Raphael Lemkin coined "genocide."',['armenia','genocide','ottoman'],'Turkey'),
    _hc('EVT125','Nakba','Event','foreign','1948','UR','None',7,4,
       'Catastrophe: Destroy 3 civilian cards. +2 to Israeli cards. Risk: Permanent conflict.','700K Palestinians fled/were expelled during Israels creation.','Deir Yassin. Key law. UNRWA. Right of return debate. 75+ year conflict.',['palestine','israel','refugee'],'Israel'),
    _hc('EVT126','Mexican Revolution','Event','foreign','1910-1920','R','None',6,5,
       'Tierra y Libertad: +3 to social. Destroy 2 domestic cards. Military +2.','Overthrew Diaz dictatorship, 1M+ dead.','Zapata, Pancho Villa, Carranza. Constitution 1917. PRI ruled 71 years.',['mexico','revolution','zapata'],'Mexico'),
    # ── Batch 5 Events: Treaties, Trials & Geopolitical Milestones ──
    _hc('EVT127','Treaty of Paris','Event','foreign','1783','R','None',5,8,
       'Independence Recognized: +4 to diplomatic. +3 to founding. Negate 1 British card.','Treaty ended American Revolution, Britain recognized US independence.','Benjamin Franklin, John Adams, John Jay negotiated. Mississippi boundary. Fishing rights.',['revolution','founding','paris'],'France'),
    _hc('EVT128','SALT I Treaty','Event','foreign','1972','R','None',4,7,
       'Arms Control: Nuclear cards -3 power. Both +2 influence. Risk: SALT II fails.','Strategic Arms Limitation Talks between US and USSR.','ABM Treaty. Nixon-Brezhnev. Detente peak. SALT II never ratified.',['cold_war','arms_control','detente'],'USSR'),
    _hc('EVT129','Truth and Reconciliation','Event','foreign','1995-1998','R','None',4,8,
       'Healing: +4 to social. Negate 2 racial cards. Both +1 influence.','South African restorative justice after apartheid.','Tutu chaired. Amnesty for truth. 7000 hearings. Model for post-conflict.',['south_africa','apartheid','reconciliation'],'South Africa'),
    _hc('EVT130','Treaty of Tordesillas','Event','foreign','1494','R','None',4,6,
       'Divide the World: +3 to diplomatic. Control 1 colonial card. Risk: Overlap conflicts.','Papal treaty divided New World between Spain and Portugal.','Pope Alexander VI. Line of demarcation. Portugal got Brazil. Treaty of Zaragoza 1529.',['colonial','spain','portugal'],'Spain'),
    _hc('EVT131','Congress of Vienna','Event','foreign','1814-1815','UR','None',5,8,
       'Concert of Europe: +3 to diplomatic. Negate 1 revolutionary card. 100 years peace.','Post-Napoleonic conference redrew European borders.','Metternich. Balance of power. Restoration of monarchies. Holy Alliance.',['europe','napoleon','metternich'],'Austria'),
    _hc('EVT132','NPT Signing','Event','foreign','1968','R','None',4,7,
       'Non-Proliferation: Nuclear cards -3 power. Both +2 influence. Risk: Rogue states ignore.','Treaty on Non-Proliferation of Nuclear Weapons, 191 states signed.','5 recognized nuclear states. Iran, North Korea controversies. IAEA inspections. Review conferences.',['npt','nuclear','arms_control'],'Global'),
    _hc('EVT133','Treaty of Westphalia','Event','foreign','1648','R','None',4,7,
       'State Sovereignty: +3 to diplomatic. Negate 1 religious war. +2 to Policy.','Ended Thirty Years War, established modern state system and sovereignty.','Religious tolerance. Westphalian sovereignty. Foundation of international law.',['westphalia','sovereignty','europe'],'Germany'),
    _hc('EVT134','Genocide Convention','Event','foreign','1948','R','UN',3,8,
       'Never Again: +3 to social. Negate 2 genocide cards. Risk: Enforcement gap.','UN Convention on the Prevention and Punishment of Genocide.','Lemkin drafted. Ratified by 150+ nations. Rarely enforced. Rwanda, Srebrenica failures.',['genocide','un','human_rights'],'Global'),
    _hc('EVT135','Velvet Revolution','Event','foreign','1989','R','None',4,7,
       'Peaceful Transition: +3 to social. Destroy 2 communist cards. +2 to diplomatic.','Czechoslovakias bloodless overthrow of communist regime.','Havel. Civic Forum. 10 days. Velvet Divorce followed 1993.',['czech','velvet','havel'],'Czechoslovakia'),
    _hc('EVT136','Soweto Uprising','Event','foreign','1976','R','None',5,5,
       'Students Revolt: +3 to social. Destroy 2 apartheid cards. Risk: Police massacre.','Black South African students protested Afrikaans language mandate.','Hector Pieterson photo. 700+ killed. ANC galvanized. International sanctions followed.',['south_africa','apartheid','student'],'South Africa'),
    # ── Batch 6 Events: Modern Geopolitical ──
    _hc('EVT137','Berlin Blockade','Event','foreign','1948-1949','R','None',5,6,
       'Airlift: +2 to military. +2 to diplomatic. Soviet -2. Risk: Escalation.','Soviet blockade of West Berlin, US/UK airlift supplied 2M+ citizens.','327 days. 278K flights. Candy bomber. First Cold War crisis.',['cold_war','berlin','airlift'],'Germany'),
    _hc('EVT138','Six Day War','Event','foreign','1967','UR','None',7,6,
       'Lightning Victory: +4 to military. Destroy 3 Arab military cards. Israeli +3.','Israel defeated Egypt, Jordan, Syria in 6 days, seized Sinai, Golan, West Bank, Jerusalem.','Preemptive strike. 6 days. Tripled territory. Palestinian occupation began.',['israel','arab','six_day'],'Israel'),
    _hc('EVT139','Yom Kippur War','Event','foreign','1973','UR','None',7,5,
       'Surprise Attack: Both lose 3 cards. Military +2. Oil cards +3. Risk: Nuclear alert.','Egypt/Syria surprise attack on Israel, near-defeat, US resupply.','OPEC embargo. US nuclear alert. Israel pushed back. Sinai returned later.',['israel','arab','yom_kippur'],'Israel'),
    _hc('EVT140','Berlin Wall Construction','Event','foreign','1961','R','None',5,5,
       'Barbed Wire: Divide board. Both lose 2 influence. Communist +2. Risk: 28 years.','East Germany built wall to stop mass defection to West.','Barbed wire Aug 13. Concrete. Checkpoint Charlie standoff. 140+ killed trying to escape.',['berlin','cold_war','wall'],'Germany'),
    _hc('EVT141','Falklands War','Event','foreign','1982','R','None',5,5,
       'Iron Lady: +3 to military. Destroy 2 Argentine cards. Thatcher +3.','UK recaptured Falkland Islands from Argentina.','Thatcher popularity surged. 649 Argentine, 255 British dead. Exocet missiles.',['uk','argentina','thatcher'],'UK'),
    _hc('EVT142','Orange Revolution','Event','foreign','2004','R','None',4,7,
       'People Power: +3 to social. +2 to diplomatic. Negate 1 Russian card. Risk: Reversal.','Ukrainian mass protests against rigged election, pro-Western Yushchenko installed.','Poisoning allegations. Yanukovych reversed it 2010. Maidan followed 2014.',['ukraine','revolution','protest'],'Ukraine'),
    _hc('EVT143','Euromaidan Revolution','Event','foreign','2014','UR','None',6,7,
       'Revolution of Dignity: +3 to revolutionary. +2 to diplomatic. Negate 1 Russian card. Risk: War.','Ukrainian protests ousted pro-Russian Yanukovych, Russia annexed Crimea.','Snipers. 108 killed. Yanukovych fled. Crimea annexed. Donbas war began.',['ukraine','revolution','maidan'],'Ukraine'),
    _hc('EVT144','Bretton Woods Collapse','Event','economic','1971','UR','Federal Reserve',5,7,
       'Nixon Shock: Economic -3. Dollar devalued. Gold window closed. Petrodollar begins.','Nixon ended dollar-gold convertibility, ended Bretton Woods system.','August 15, 1971. Floating currencies. Inflation. Petrodollar with Saudi Arabia.',['nixon','gold','economic'],'USA'),
    _hc('EVT145','Salt March','Event','foreign','1930','R','None',4,8,
       'Civil Disobedience: +4 to social. +2 to revolutionary. Negate 1 colonial card. Risk: Arrest.','Gandhi led 240-mile salt march, defied British salt monopoly.','78 followers, 240 miles. 60K arrested. World attention. Nonviolent resistance model.',['india','gandhi','nonviolence'],'India'),
    _hc('EVT146','Berlin Airlift','Event','foreign','1948-1949','R','None',4,7,
       'Candy Bomber: +3 to diplomatic. +2 to social. Soviet -2. Risk: War.','Allied airlift saved West Berlin from Soviet blockade.','278K flights. 2.3M tons. Coal, food. Gail Halvorsen dropped candy. Stalin backed down.',['cold_war','berlin','airlift'],'Germany'),
    # ── Batch 7 Events: Controversial & Conspiracy Events ──
    _hc('EVT147','Business Plot','Event','domestic','1933','R','None',5,7,
       'Coup Attempt: +3 to military. Negate 1 economic Org. Risk: Denied by all.','Wealthy businessmen allegedly plotted to overthrow FDR, exposed by Smedley Butler.','J.P. Morgan, DuPont, Remington. American Liberty League. Congress investigated. Called "a joke."',['business_plot','fdr','coup'],'USA'),
    _hc('EVT148','King David Hotel Bombing','Event','foreign','1946','UR','Mossad',6,5,
       'Terror Bomb: Destroy 2 diplomatic cards. UK -3. Reveal 1 Conspiracy. Risk: Irgun exposure.','Zionist Irgun bombed British HQ in Jerusalem, 91 killed.','Menachem Begin planned. Disguised as Arabs. 91 dead: British, Arabs, Jews. Mandate ended.',['irgun','israel','terrorism'],'Israel'),
    _hc('EVT149','Ruby Ridge Siege','Event','domestic','1992','R','FBI',5,5,
       'Standoff: Destroy 1 domestic card. FBI -3. Reveal 1 Conspiracy. Risk: Militia movement.','FBI siege at Weaver family cabin, Randy Weavers wife and son killed.','Sniper Lon Horiuchi shot Vicki Weaver. Ruby Ridge + Waco = OKC bombing motive. FBI rules changed.',['ruby_ridge','fbi','standoff'],'USA'),
    _hc('EVT150','Epstein Death','Event','domestic','2019','L','None',8,10,
       'Suicide? Remove Epstein. Reveal 3 face-down. Both lose 2. Risk: Cameras off.','Jeffrey Epstein found dead in MCC jail cell, officially suicide by hanging.','Guards asleep. Cameras malfunctioned. Hyoid bone broken. "Epstein didnt kill himself" meme.',['epstein','conspiracy','coverup'],'USA'),
    _hc('EVT151','Operation Condor Assassinations','Event','foreign','1976','UR','CIA',7,4,
       'Condor Killings: Remove 2 foreign Figures. CIA -2. Risk: Letelier bombing exposes.','Coordinated assassinations by South American dictatorships, CIA-aware.','Orlando Letelier killed in DC 1976. Condor One. 60K+ killed/disappeared across continent.',['condor','cia','assassination'],'South America'),
    # ── Batch 8 Events: Geopolitical Crises & Intelligence ──
    _hc('EVT152','U-2 Incident','Event','foreign','1960','UR','CIA',6,5,
       'Spy Plane Down: Reveal 3 face-down. CIA -3. Cold War +2. Risk: Eisenhower lies.','CIA U-2 spy plane shot down over USSR, pilot Gary Powers captured.','Eisenhower denied, then admitted. Khrushchev canceled Paris summit. Powers swapped 1962.',['cold_war','cia','spy_plane'],'USSR'),
    _hc('EVT153','Entebbe Raid','Event','foreign','1976','UR','Mossad',6,7,
       'Hostage Rescue: Destroy 2 terrorist cards. Israel +3 influence. Reveal 1 face-down.','Israeli commandos rescued 102 hostages from hijacked Air France flight in Uganda.','Idi Amin hosted hijackers. Yonatan Netanyahu killed. Operation Thunderbolt. 7 hijackers killed.',['israel','hostage','commando'],'Uganda'),
    _hc('EVT154','Clean Break Memo','Event','foreign','1996','R','None',4,7,
       'Strategic Clean Break: +3 to military. +2 to intelligence. Negate 1 diplomatic card. Risk: Iraq War.','Netanyahu-era Israeli policy paper advocating regime change in Iraq, Syria, Iran.','Perle, Feith, Wurmser wrote. "Securing the Realm." Blueprint for US Middle East policy.',['neocon','israel','iraq'],'Israel'),
    _hc('EVT155','Color Revolution Wave','Event','foreign','2003-2005','R','None',5,7,
       'People Power: +3 to revolutionary. +2 to diplomatic. Negate 1 Russian card. Risk: Putin backlash.','Series of pro-Western revolutions in post-Soviet states: Rose, Orange, Tulip.','Georgia, Ukraine, Kyrgyzstan. US-funded NGOs. Soros. Putin blamed US. Counter-revolutions followed.',['color_revolution','soros','russia'],'Global'),
    _hc('EVT156','Stuxnet Attack','Event','intelligence','2010','UR','Mossad',7,6,
       'Cyber Sabotage: Destroy 1 nuclear card. Intelligence +3. Risk: Cyber warfare escalation.','US-Israel cyberweapon sabotaged Iranian nuclear centrifuges via USB.','Olympic Games program. Zero-day exploits. Natanz. First digital weapon to cause physical damage.',['israel','iran','cyber'],'Iran'),
    # ── Batch 9 Events: Geopolitical Chess Moves ──
    _hc('EVT157','Budapest Memorandum Violation','Event','foreign','2014','UR','None',6,5,
       'Torn Treaty: Destroy 2 diplomatic cards. Reveal 2 face-down. Risk: Nuclear proliferation.','Russia violated 1994 Budapest Memorandum by annexing Crimea, undermining nuclear disarmament assurances.','Ukraine gave up Soviet nukes for security guarantees. US, UK, Russia signed. Crimea 2014. Set precedent for nuclear proliferation.',['russia','ukraine','crimea'],'Ukraine'),
    _hc('EVT158','Russian Apartment Bombings','Event','foreign','1999','UR','KGB',7,4,
       'Reichstag Fire: +4 to military. Destroy 2 domestic. Reveal 1 Conspiracy. Risk: FSB Ryazan exposure.','Series of apartment bombings killed 300, blamed on Chechens, launched Second Chechen War.','Ryazan: FSB caught planting explosives, called "exercise." Putin popularity soared. Litvinenko investigated.',['fsb','russia','false_flag'],'Russia'),
    _hc('EVT159','PNAC Letter to Clinton','Event','foreign','1998','R','None',3,7,
       'Regime Change Lobby: +2 to military. +2 to foreign Policy. Reveal 1 face-down. Risk: Iraq War follows.','Project for New American Century letter urging Clinton to remove Saddam Hussein.','Rumsfeld, Wolfowitz, Perle, Bolton, Kristol signed. Blueprint for 2003 Iraq invasion.',['neocon','iraq','pnc'],'USA'),
    _hc('EVT160','Litvinenko Polonium Hit','Event','foreign','2006','UR','KGB',6,4,
       'Radioactive Assassination: Remove 1 Figure. Intelligence +2. Reveal 2 face-down. Risk: UK diplomatic crisis.','Russian ex-spy Alexander Litvinenko poisoned with polonium-210 in London, died 3 weeks later.','Litvinenko accused Putin of apartment bombings. Lugovoy suspected. Russia refused extradition. Polonium trail across London.',['russia','polonium','assassination'],'UK'),
    _hc('EVT161','Mena Airport Allegations','Event','domestic','1980s','R','CIA',5,5,
       'Drug Airstrip: +2 to intelligence. Destroy 1 social card. Reveal 1 Conspiracy. Risk: Clinton connection.','Alleged CIA drug smuggling operations through Mena, Arkansas airport during Iran-Contra era.','Barry Seal flights. Clinton governor. Train deaths. Kevin Ives and Don Henry. Conspiracy: covered up.',['cia','drugs','arkansas'],'USA'),
    # ── Batch 10 Events: Geopolitical Crises & Strategic Moves ──
    _hc('EVT162','Maidan Coup','Event','foreign','2014','UR','None',7,7,
       'Regime Change: Remove 1 foreign Figure. +3 to revolutionary. Risk: Civil war, Russian invasion.','Ukraines pro-Russian president Yanukovych ousted after Euromaidan protests and sniper killings.','Nuland cookies. Right Sector. Crimea annexed. Donbas war. 13K+ dead. Proxy war began.',['ukraine','maidan','regime_change'],'Ukraine'),
    _hc('EVT163','Suez Crisis Aftermath','Event','foreign','1956-1957','R','None',4,6,
       'Imperial Sunset: +2 to diplomatic. UK -3 influence. Reveal 1 face-down.','Suez Crisis ended British imperial power, elevated US and USSR in Middle East.','Eisenhower forced UK/France/Israel withdrawal. Pound sterling collapsed. UN peacekeepers. Nasser hero.',['suez','uk','imperial'],'Egypt'),
    _hc('EVT164','Able Archer Scare','Event','foreign','1983','UR','None',6,4,
       'Brink of War: +4 to military. Both lose 3 influence. Risk: Nuclear miscalculation.','NATO command exercise nearly triggered Soviet nuclear response.','Operation RYAN. Andropov paranoid. Petrov saved world. KAL 007 context. Reagan spooked.',['cold_war','nuclear','1983'],'USSR'),
    _hc('EVT165','Repeal of Fairness Doctrine','Event','domestic','1987','R','FCC',3,8,
       'Partisan Media: +3 to media. Social -2 influence. Risk: Polarization, echo chambers.','FCC eliminated Fairness Doctrine requiring balanced coverage on public airwaves.','Reagan FCC. Rush Limbaugh launched 1988. Fox News 1996. Media fragmentation. Echo chambers.',['media','fairness_doctrine','polarization']),
    _hc('EVT166','TWEP Operations','Event','intelligence','2002-2011','UR','CIA',6,5,
       'Targeted Killing: Remove 2 Figures. Intelligence +3. Risk: Civilian casualties, blowback.','CIA Targeted Killing program using drone strikes against suspected terrorists worldwide.','Anwar al-Awlaki. Signature strikes. Double taps. Wedding parties. Kill lists. Obama expanded 10x.',['cia','drones','assassination']),
    # ── Batch 11 Events: Political Movements & Financial Crises ──
    _hc('EVT167','Occupy Wall Street','Event','domestic','2011','R','None',4,7,
       'We Are the 99%: +3 to social. Economic -2. Negate 1 Wall Street Org. Risk: Evicted, no structural change.','Protest movement against wealth inequality, encamped in Zuccotti Park.','TARP rage. 1% vs 99%. Elizabeth Warren. AOC. Crushed by coordinated police raids. No policy change.',['occupy','inequality','wall_street']),
    _hc('EVT168','Tea Party Movement','Event','domestic','2009-2012','R','None',4,6,
       'Taxed Enough Already: +2 to economic. +2 to military. Negate 1 social Policy. Risk: Astroturfed, Koch funded.','Conservative populist movement opposing Obama, fueled by Koch network and Fox News.','Rick Santelli rant. Koch Americans for Prosperity. FreedomWorks. 2010 midterms. Birthed MAGA.',['tea_party','koch','populist']),
    _hc('EVT169','January 6 Capitol Attack','Event','domestic','2021','UR','None',7,8,
       'Stop the Steal: Destroy 2 domestic. Both lose 3 influence. Reveal 3 face-down. Risk: Polarization, authoritarian creep.','Mob stormed US Capitol to prevent Electoral College certification of Biden victory.','Proud Boys, Oath Keepers. 140+ officers injured. $2.7M damage. 1,200+ charged. Trump impeached again.',['jan6','trump','insurrection']),
    _hc('EVT170','Me Too Movement','Event','social','2017-present','R','None',3,8,
       'Time Up: +3 to social. Negate 2 Scandals. Control 1 Figure. Risk: Backlash, co-optation.','Viral movement exposing sexual harassment and assault across industries.','Weinstein catalyst. Tarana Burke founded. Hollywood, media, politics. Ailes, ONeal, Lauer fired.',['metoo','social','harassment']),
    _hc('EVT171','GameStop Short Squeeze','Event','economic','2021','R','None',4,5,
       'Apes Together Strong: +2 to economic. Destroy 1 hedge fund Org. Peek 2 face-down. Risk: Trading halted, DTCC exposure.','Reddit retail traders drove GameStop stock 1,500%+, crushing hedge fund short sellers.','WallStreetBets. Melvin Capital. Robinhood halted buying. Citadel payment for order flow. Ken Griffin.',['gamestop','wall_street','reddit']),
    # ── Batch 12 Events: Energy, Finance & Geopolitical Shifts ──
    _hc('EVT172','OPEC Oil Embargo','Event','economic','1973-1974','UR','None',7,8,
       'Oil Shock: Oil cards +4 power. Economic -3. Destroy 1 domestic. Risk: Stagflation, solar investment.','OPEC embargoed US for supporting Israel in Yom Kippur War, quadrupled oil prices.','Gas lines. Odd-even rationing. 55 mph speed limit. Strategic Petroleum Reserve created. Stagflation. Solar research.',['opec','oil','embargo']),
    _hc('EVT173','Lehman Brothers Collapse','Event','economic','2008','UR','Wall Street',8,7,
       'Domino: Destroy 3 economic cards. Wall Street -4. Both lose 3 influence. Risk: Global contagion, TARP.','Lehman Brothers bankruptcy, largest in US history, triggered global financial crisis.','$639B assets. Repo 105. Fuld. Paulson let it fall. AIG bailed out next day. Money market broke the buck.',['lehman','wall_street','crash']),
    _hc('EVT174','Paris Climate Agreement','Event','foreign','2015','R','None',4,7,
       'Climate Accord: +3 to social. Oil cards -2. Negate 1 climate denial. Risk: US withdraws under Trump.','196 nations agreed to limit global warming to 1.5C above pre-industrial levels.','Obama signed. Trump withdrew 2020. Biden rejoined. Non-binding. NDCs. Green climate fund.',['paris','climate','emissions'],'France'),
    _hc('EVT175','Hong Kong Handover','Event','foreign','1997','R','None',4,6,
       'One Country Two Systems: +2 to diplomatic. CCP +3 influence. Risk: National Security Law 2020, erosion.','UK transferred Hong Kong sovereignty to China under Sino-British Joint Declaration.','50-year promise. Basic Law. CCP gradually eroded autonomy. NSL 2020 crushed democracy. Exodus.',['hong_kong','china','uk'],'Hong Kong'),
    _hc('EVT176','Bretton Woods Conference','Event','economic','1944','UR','None',5,9,
       'Global Financial Order: +3 to economic. Negate 1 gold card. Peek 2 face-down. Risk: Nixon shock 1971.','44 nations established post-WWII monetary system, US dollar as reserve currency, IMF and World Bank.','Dollar-gold peg $35/oz. Keynes bancor rejected. Harry Dexter White. Soviet attended. IMF, IBRD created. Ended 1971 Nixon shock.',['bretton_woods','dollar','imf'],'USA'),
]

CONSPIRACIES = [
    _hc('CON001','Operation Ajax','Conspiracy','foreign','1953','UR','CIA',7,8,
       'Regime Change: Remove one foreign Figure. Place a puppet.','CIA/MI6 overthrew Irans Mossadegh.','Installed Shah. Led to 1979 revolution. Declassified 2013.',['cia','iran','coup'],'Iran'),
    _hc('CON002','Operation Gladio','Conspiracy','intelligence','1956-1990','UR','CIA',6,7,
       'Stay-Behind: Place 2 face-down cards. +2 power when revealed.','NATO secret armies in Europe.','False-flag terrorism alleged.',['cia','nato','false_flag'],'Europe'),
    _hc('CON003','MKUltra','Conspiracy','intelligence','1953-1973','UR','CIA',7,8,
       'Mind Control: Control one opponent Figure for 2 turns.','CIA LSD experiments on unwitting citizens.','Church Committee exposed.',['cia','mind_control','experiment']),
    _hc('CON004','Gulf of Tonkin','Conspiracy','military','1964','UR','NSA',7,7,
       'False Flag: Create a fake Event. Opponent must respond.','Alleged NV attack on US ships.','NSA declassified 2005: 2nd attack never happened.',['false_flag','vietnam','nsa']),
    _hc('CON005','Operation Northwoods','Conspiracy','military','1962','R','Pentagon',6,6,
       'False Flag Plan: Create fake Event. Risk: Scandal if revealed.','Pentagon plan to stage terror, blame Cuba.','JFK rejected. Declassified 1997.',['false_flag','cuba','pentagon']),
    _hc('CON006','COINTELPRO','Conspiracy','intelligence','1956-1971','UR','FBI',7,7,
       'Disrupt: Target org cards lose 3 influence for 3 turns.','FBI counter-intel vs dissidents.','Targeted MLK, Black Panthers, anti-war.',['fbi','surveillance','civil_rights']),
    _hc('CON007','Tuskegee Syphilis','Conspiracy','social','1932-1972','UR','Big Pharma',6,5,
       'Medical Experiment: -4 influence to one Figure. +2 to Scandal cards.','US withheld treatment from Black men.','40-year experiment. 128 died.',['racism','medical','experiment']),
    _hc('CON008','JFK Second Shooter','Conspiracy','domestic','1963','L','None',8,10,
       'Grassy Knoll: Remove one Figure. Reveal 3 face-down cards.','Theory: second shooter on grassy knoll.','Acoustic evidence debated. Zapruder film.',['jfk','assassination','conspiracy']),
    _hc('CON009','9/11 Building 7','Conspiracy','domestic','2001','UR','None',7,8,
       'Controlled Demolition: Destroy one Organization. Both lose 3 power.','WTC 7 collapsed without plane impact.','NIST: fires. Theorists: demolition. Silverstein insurance.',['911','conspiracy','insurance']),
    _hc('CON010','Operation Paperclip','Conspiracy','intelligence','1945-1959','R','CIA',6,7,
       'Nazi Scientists: +3 power to military/intelligence cards.','US recruited 1600+ Nazi scientists.','Von Braun. Soviet counterpart: Osoaviakhim.',['nazi','cia','wwii']),
    _hc('CON011','Iran-Contra Affair','Conspiracy','intelligence','1985-1987','UR','CIA',7,7,
       'Arms for Hostages: Trade cards secretly. Risk: Scandal.','Reagan admin sold arms to Iran, funded Contras.','Oliver North, Fawn Hall shredding.',['iran','contra','scandal']),
    _hc('CON012','PRISM Program','Conspiracy','intelligence','2007-2013','UR','NSA',7,8,
       'Mass Data: Reveal opponents hand permanently. -2 influence.','NSA collected data from Google, Apple, MS.','FISA court. Section 702 reauthorized.',['nsa','surveillance','tech']),
    _hc('CON013','Operation Mockingbird','Conspiracy','intelligence','1950s-1970s','R','CIA',6,7,
       'Media Control: +3 influence to Media cards. Negate one Scandal.','CIA influenced media, planted stories.','Bernstein exposed 1977. Journalists on payroll.',['cia','media','propaganda']),
    _hc('CON014','Suez Crisis Conspiracy','Conspiracy','foreign','1956','R','CIA',5,7,
       'Collusion Exposed: Reveal 3 face-down. +2 to intelligence cards.','UK/France/Israel secretly colluded to seize Suez Canal.','Eisenhower forced withdrawal. Nasser strengthened.',['suez','collusion','cold_war'],'Egypt'),
    _hc('CON015','Fast and Furious','Conspiracy','intelligence','2006-2011','R','FBI',5,6,
       'Gun Walking: Give opponent 2 cards. Risk: Scandal +3 vs you.','ATF let guns walk to cartels.','Brian Terry killed. Holder contempt.',['atf','cartel','scandal']),
    _hc('CON016','Unit 731','Conspiracy','military','1932-1945','L','None',9,6,
       'Biological Warfare: Destroy 2 cards. Both lose 4 influence.','Japanese bio/chem experiments on prisoners.','US granted immunity for data. 3000+ killed.',['japan','biological','war_crime'],'Japan'),
    _hc('CON017','Operation Condor','Conspiracy','intelligence','1975-1983','UR','CIA',7,7,
       'Death Squads: Remove 2 foreign Figures. Risk: -3 influence.','Coordinated S. American dictatorships.','Assassinations in US, Europe, S. America.',['cia','south_america','assassination'],'South America'),
    _hc('CON018','HAARP','Conspiracy','military','1993-present','U','Pentagon',4,5,
       'Weather Control: Negate one Event. Risk: Theorists target you.','Ionospheric research, Alaska.','Conspiracy: mind control, weather, earthquakes.',['haarp','conspiracy']),
    _hc('CON019','Bohemian Grove','Conspiracy','economic','1872-present','U','None',4,6,
       'Elite Retreat: +2 influence to Figure cards.','Exclusive all-male club, California.','Nixon, Reagan attended. Cremation of Care ritual.',['elite','secret_society']),
    _hc('CON020','Midnight Climax','Conspiracy','intelligence','1955-1965','R','CIA',5,6,
       'Sex Blackmail: Control one Figure secretly. Risk: Scandal.','CIA used prostitutes to dose targets with LSD.','Safe houses in SF. Part of MKUltra.',['cia','mkultra','blackmail']),
    _hc('CON021','JFK Assassination Plot','Conspiracy','domestic','1963','L','CIA',9,10,
       'The Plot: Remove JFK card. Reveal 5 face-down cards. Destroy 2 CIA cards.','Theory: CIA orchestrated JFK assassination.','Mob, CIA, Cuba, Vietnam withdrawal motives. Warren Commission gaps.',['jfk','assassination','cia']),
    _hc('CON022','RFK Assassination Plot','Conspiracy','domestic','1968','R','None',7,7,
       'Second Hit: Remove RFK card. Reveal 2 face-down. Sirhan was programmed?','Theory: RFK killed by conspiracy, not lone gunman.','Coroner: fatal shot from behind, Sirhan in front. Hypnosis theories.',['rfk','assassination','conspiracy']),
    _hc('CON023','MLK Assassination Plot','Conspiracy','domestic','1968','R','FBI',7,8,
       'The Dream Cut Short: Remove MLK card. FBI -4 influence. Reveal 2 face-down.','Theory: Government involved in MLK assassination.','King family won civil trial implicating Loyd Jowers. FBI COINTELPRO context.',['mlk','assassination','fbi']),
    _hc('CON024','9/11 Inside Job','Conspiracy','domestic','2001','L','None',10,10,
       'Inside Job: Destroy 4 cards. Reveal ALL face-down. Both lose 5 influence.','Theory: 9/11 was orchestrated or allowed by US government.',' NORAD stand-down, WTC 7, put options, thermite claims. Official: Al-Qaeda.',['911','inside_job','conspiracy']),
    _hc('CON025','Saddam WMD Fabrication','Conspiracy','foreign','2002-2003','UR','CIA',7,7,
       'Fabricated Evidence: Create fake Event card. Opponent must respond.','US used fabricated WMD evidence to justify Iraq War.','Curveball source, yellowcake uranium, aluminum tubes. None found.',['iraq','wmd','cia']),
    _hc('CON026','Gulf War False Testimony','Conspiracy','foreign','1990','R','CIA',5,6,
       'Nayirah: +3 influence to military cards. Risk: Reveal = Scandal.','Kuwaiti ambassador daughter posed as nurse, claimed Iraqi atrocities.','Hill & Knowlton PR firm. Incubator baby story fabricated.',['gulf_war','propaganda','kuwait']),
    _hc('CON027','Operation Cyclone','Conspiracy','intelligence','1979-1989','UR','CIA',7,7,
       'Mujahideen: Create 2 Figure cards. Risk: They become enemies later.','CIA funded Afghan mujahideen via Pakistan ISI.','$3B+ funding. Bin Laden origins. Blowback: Al-Qaeda.',['cia','afghanistan','blowback'],'Afghanistan'),
    _hc('CON028','Iran 1953 Coup','Conspiracy','foreign','1953','UR','CIA',7,8,
       'Regime Change: Remove one democratic foreign Figure. Install puppet.','CIA overthrew Iran\'s democratically elected Mossadegh.','Operation Ajax. Oil interests. 26 years later: Islamic Revolution.',['cia','iran','oil'],'Iran'),
    _hc('CON029','Guatemala 1954 Coup','Conspiracy','foreign','1954','R','CIA',6,6,
       'Banana Republic: Remove one foreign Figure. United Fruit +3 power.','CIA overthrew Arbenz for United Fruit Company.','Eisenhower authorized. Castillo Armas installed. 40-year civil war.',['cia','guatemala','united_fruit'],'Guatemala'),
    _hc('CON030','Lusitania Setup','Conspiracy','military','1915','R','None',5,6,
       'Provocation: Create fake Event. Risk: Reveal = Scandal.','Theory: US allowed Lusitania to be sunk to enter WWI.','German embassy warned passengers. Munitions aboard. Wilson knew?',['wwi','false_flag','lusitania']),
    _hc('CON031','Northwoods Documents','Conspiracy','military','1962','R','Pentagon',5,5,
       'Declassified Proof: Reveal 3 face-down cards. +2 to all Conspiracy cards.','Pentagon plan to stage terror attacks on US soil, blame Cuba.','JFK rejected. Declassified 1997. Blueprint for false flags.',['false_flag','cuba','pentagon']),
    _hc('CON032','Franklin Cover-Up','Conspiracy','domestic','1980s-1990s','UR','None',6,7,
       'Pedophile Network: Control 2 Figure cards. Risk: Discredited.','Allegations of elite child trafficking ring in DC.','Lawrence King, Boys Town. Grand jury collapsed. Media dismissed.',['franklin','trafficking','coverup']),
    _hc('CON033','Vince Foster Death','Conspiracy','domestic','1993','R','None',5,6,
       'Arkancide: Remove one Figure card. Risk: Official suicide ruling.','Clinton White House counsel found dead in park.','Official: suicide. Theorists: Clinton body count. Two investigations.',['clinton','coverup','conspiracy']),
    _hc('CON034','Mena Airport Drug Running','Conspiracy','intelligence','1980s','R','CIA',6,6,
       'Drug Pipeline: +2 power to Cartel cards. CIA +2 influence. Risk: Scandal.','Alleged CIA drug trafficking through Mena, Arkansas.','Barry Seal, Iran-Contra connection. Clinton governor at time.',['cia','drugs','arkansas']),
    _hc('CON035','Seth Rich Murder','Conspiracy','domestic','2016','R','None',5,6,
       'DNC Leaker: Reveal 2 face-down cards. Risk: Debunked.','Theory: DNC staffer killed for leaking emails, not robbery.','Fox retracted story. Family sued. WikiLeaks hinted. Unresolved.',['dnc','seth_rich','conspiracy']),
    _hc('CON036','USS Liberty Attack','Conspiracy','military','1967','UR','Mossad',7,7,
       'Friendly Fire?: Destroy 2 military cards. Israel -3 influence.','Israel attacked US spy ship, 34 killed, 171 wounded.','Israel: mistaken identity. Survivors: deliberate. Johnson recalled rescue.',['israel','uss_liberty','coverup'],'Israel'),
    _hc('CON037','Tonkin Gulf Deception','Conspiracy','military','1964','UR','NSA',7,8,
       'Staged Attack: Create fake military Event. NSA -3 influence when revealed.','NSA declassified 2005: second Tonkin attack never happened.','Johnson: "for all I know they were shooting at flying fish." Escalated Vietnam.',['false_flag','vietnam','nsa']),
    _hc('CON038','Operation Ajax Documents','Conspiracy','intelligence','2013','R','CIA',4,6,
       'Declassified: Reveal all CIA face-down cards. CIA -2 influence.','CIA formally admitted 1953 Iran coup in 2013.','60 years later. Mossadegh was democratically elected. Oil was motive.',['cia','iran','declassified']),
    _hc('CON039','Sibel Edmonds Claims','Conspiracy','intelligence','2002','R','FBI',5,7,
       'FBI Whistleblower: Reveal 3 face-down intelligence cards.','Former FBI translator alleged corruption, nuclear espionage.','Gag ordered. State Secrets Privilege. Congress heard closed door.',['fbi','whistleblower','gag_order']),
    _hc('CON040','Cambridge Analytica','Conspiracy','intelligence','2014-2018','UR','None',7,8,
       'Data Harvesting: Reveal opponent\'s hand. KGB +2 influence.','87M Facebook profiles harvested for political targeting.','Brexit, Trump 2016, Cruz. Zuckerberg testified. Company dissolved.',['cambridge_analytica','facebook','election']),
    # ── Global Conspiracies ──
    _hc('CON041','Nord Stream Sabotage','Conspiracy','foreign','2022','UR','None',7,7,
       'Pipeline Blast: Destroy 2 economic cards. Russia -3 influence.','Nord Stream pipelines sabotaged, blame disputed.','US denied. Seymour Hersh: Norway/US. Russia blamed.',['russia','nord_stream','sabotage'],'Germany'),
    _hc('CON042','Stuxnet Cyberattack','Conspiracy','intelligence','2010','UR','Mossad',7,8,
       'Cyber Worm: Destroy 1 nuclear card. Iran -4 influence.','US/Israel cyberattack on Iranian centrifuges.','First digital weapon to cause physical destruction.',['israel','iran','cyber'],'Iran'),
    _hc('CON043','Skripal Poisoning','Conspiracy','intelligence','2018','UR','KGB',6,7,
       'Novichok: Remove one Figure. Russia -3 influence.','Russian ex-spy poisoned in UK, 1 civilian dead.','Russia denied. OPCW confirmed Novichok. Sanctions.',['russia','kgb','poison'],'UK'),
    _hc('CON044','Khashoggi Murder','Conspiracy','foreign','2018','L','None',8,8,
       'Bone Saw: Remove one Figure. Reveal 3 face-down. Saudi -5 influence.','Saudi journalist killed in consulate by Saudi team.','MBS denied ordering. CIA concluded he did. Body never found.',['saudi','khashoggi','assassination'],'Saudi Arabia'),
    _hc('CON045','MH17 Shootdown','Conspiracy','military','2014','UR','Kremlin',6,6,
       'Civilian Airliner: Destroy 2 military cards. Russia -3 influence.','Malaysian airliner shot down over Ukraine, 298 dead.','Russian Buk missile. Dutch investigation. Russia denied.',['russia','ukraine','coverup'],'Ukraine'),
    _hc('CON046','Pegasus Spyware','Conspiracy','intelligence','2019-present','UR','Mossad',6,8,
       'Zero-Click: Peek at opponent hand permanently. Reveal 2 face-down.','NSO Group spyware used against journalists, activists.','Israel exported globally. Khashoggi associates targeted.',['israel','mossad','surveillance']),
    _hc('CON047','Gold Standard Removal','Conspiracy','economic','1933-1971','UR','Federal Reserve',6,7,
       'Fiat Money: +3 to economic cards. Risk: Inflation cards double.','Nixon ended gold convertibility 1971.','FDR confiscated gold 1933. Fiat enabled money printing.',['fed','gold','nixon']),
    _hc('CON048','Inslaw/PROMIS','Conspiracy','intelligence','1980s-1990s','R','None',5,7,
       'Stolen Software: Peek at 3 opponent cards. Intelligence +2 power.','Justice Dept stole Inslaw PROMIS software, sold to intelligence agencies.','Promis tracked criminals and spies. Danny Casolaro died investigating.',['promis','inslaw','casolaro']),
    _hc('CON049','Davos Great Reset','Conspiracy','economic','2020-present','R','None',5,7,
       'Stakeholder Capitalism: +2 to economic. Reveal 2 face-down.','WEF "Great Reset" agenda post-COVID.','"You will own nothing and be happy." ESG, CBDC.',['wef','davos','globalist']),
    _hc('CON050','CIA Drug Running','Conspiracy','intelligence','1980s-present','UR','CIA',7,7,
       'Dark Alliance: +3 to Cartel cards. CIA +2 power. Risk: Scandal.','Gary Webb exposed CIA-Contra-crack connection.','Webb died 2004 "suicide." Mena airport. Barry Seal.',['cia','drugs','cartel']),
    # ── New Conspiracies ──
    _hc('CON051','Phoenix Program','Conspiracy','intelligence','1965-1972','UR','CIA',7,6,
       'Assassination Squads: Destroy 2 social Figures. CIA +2. Risk: Scandal.','CIA covert program to neutralize Viet Cong infrastructure.','Tens of thousands killed/tortured. "Terminal" count. Blowback.',['cia','vietnam','assassination'],'Vietnam'),
    _hc('CON052','Lavon Affair','Conspiracy','foreign','1954','R','Mossad',5,6,
       'False Flag: Create fake Event. Risk: Reveal = Scandal.','Israeli agents planted bombs in Egypt, blamed Muslims. Code: Operation Susannah.','Caught, tried, executed. Led to resignation of Defense Minister.',['mossad','false_flag','egypt'],'Egypt'),
    _hc('CON053','Operation Mongoose','Conspiracy','foreign','1961-1962','R','CIA',5,6,
       'Sabotage Cuba: Destroy 2 economic cards. +2 to military. Risk: Blowback.','CIA covert ops to overthrow Castro, 33 plans including exploding cigars.','Poisoned pens, contaminated suits. Operation Northwoods grew from this.',['cia','cuba','castro'],'Cuba'),
    _hc('CON054','Stuxnet','Conspiracy','intelligence','2010','UR','Mossad',7,7,
       'Cyber Sabotage: Destroy 2 economic cards. Intelligence +3. Risk: Blowback.','US/Israel cyberweapon destroyed Iranian nuclear centrifuges.','First digital weapon to cause physical damage. Flame, Duqu followed.',['mossad','cyber','iran'],'Iran'),
    _hc('CON055','BCCI Scandal','Conspiracy','economic','1972-1991','R','None',6,7,
       'Bank of Crooks: +3 to economic. Peek 3 face-down. Risk: Laundering.','Bank of Credit and Commerce International, global money laundering.','CIA, drug money, arms deals. $20B+ laundered.',['bcci','money_laundering','cia']),
    _hc('CON056','ECHELON','Conspiracy','intelligence','1960s-present','R','NSA',5,8,
       'Global Surveillance: Peek at ALL opponent face-down. Intelligence +2.','Five Eyes global signals intelligence network.','Intercepts all communications. UKUSA Agreement.',['nsa','surveillance','five_eyes']),
    _hc('CON057','Manhattan Project','Conspiracy','military','1942-1946','UR','None',7,6,
       'Atomic Secret: +4 to military. Destroy 1 city card. Risk: Proliferation.','US secret program to build first nuclear weapons.','130K employed. Oppenheimer. Trinity test. Hiroshima/Nagasaki.',['nuclear','manhattan','oppenheimer']),
    _hc('CON058','Sibel Edmonds','Conspiracy','intelligence','2002','R','FBI',4,7,
       'Whistleblower: Reveal 3 face-down. Intelligence -2 influence. Risk: State Secrets.','FBI translator found evidence of foreign penetration, gagged.','State Secrets Privilege invoked. Congress gagged.',['fbi','whistleblower','state_secrets']),
    # ── Batch 2 Conspiracies ──
    _hc('CON059','Project Azorian','Conspiracy','intelligence','1974','UR','CIA',6,7,
       'Glomar: Steal 1 face-down card. +2 to intelligence. Risk: Cover-up blown.','CIA raised Soviet submarine K-129 from 3-mile depth using fake ship.','Howard Hughes cover. Press leaked it. $3B in today dollars.',['cia','glomar','soviet']),
    _hc('CON060','Lockerbie Bombing','Conspiracy','foreign','1988','UR','None',6,6,
       'Pan Am 103: Destroy 1 civilian card. Reveal 3 face-down. Risk: Retaliation.','Bomb exploded on Pan Am 103 over Scotland, 270 killed.','Libya blamed. Megrahi convicted, released on compassion. Conspiracy theories persist.',['lockerbie','libya','terrorism'],'UK'),
    _hc('CON061','KAL 007 Shootdown','Conspiracy','intelligence','1983','R','NSA',5,6,
       'Off Course: Destroy 1 civilian card. Soviet -2. Reveal 2 face-down.','Soviet fighters shot down Korean Air Lines 007, 269 killed.','Congressman McDonald aboard. NSA knew plane was off course.',['soviet','kal007','nsa'],'USSR'),
    _hc('CON062','Able Danger','Conspiracy','intelligence','1999-2001','R','Pentagon',4,6,
       'Pre-9/11: Reveal 3 face-down. Intelligence +2. Risk: Data destroyed.','Military intelligence identified 9/11 hijackers before attacks.','Data destroyed by SOCOM. 9/11 Commission dismissed.',['911','intelligence','able_danger']),
    _hc('CON063','Belgian Congo','Conspiracy','foreign','1885-1908','L','None',9,4,
       'Heart of Darkness: Destroy 5 African cards. Economic +4. Risk: International outrage.','King Leopold II owned Congo as personal property, 10M+ killed.','Rubber quotas. Hands amputated. Conrad novel. First modern genocide.',['leopold','congo','genocide'],'Congo'),
    _hc('CON064','Boer War Concentration Camps','Conspiracy','foreign','1899-1902','R','British Crown',6,4,
       'Concentration Camps: Destroy 3 civilian cards. British -3 influence.','British built camps for Boer civilians, 26K+ women/children died.','Kitchener scorched earth. Emily Hobhouse exposed. First modern concentration camps.',['british_crown','boer','concentration_camp'],'South Africa'),
    _hc('CON065','Project SHAD','Conspiracy','military','1962-1973','R','Pentagon',5,5,
       'Biowar Tests: Destroy 2 medical cards. Reveal 2 face-down. Risk: Veterans ill.','US tested biological/chemical weapons on unknowing troops.','Project 112. Ships sprayed. Veterans denied benefits for decades.',['pentagon','biowar','experiment']),
    _hc('CON066','Tuskgeegee Syphilis','Conspiracy','social','1932-1972','UR','CDC',6,4,
       'Human Experiment: -3 to social. Medical +2. Reveal 2 face-down. Risk: Bioethics scandal.','US government studied untreated syphilis in Black men for 40 years.','399 men. Withheld penicillin. 128 died. Led to Belmont Report.',['cdc','experiment','racism']),
    # ── Batch 3 Conspiracies ──
    _hc('CON067','Rosenberg Spy Ring','Conspiracy','intelligence','1950-1953','UR','KGB',6,6,
       'Atomic Spies: Soviet +3 to military. Destroy 1 nuclear card. Risk: Execution.','Julius and Ethel Rosenberg passed atomic secrets to USSR.','Executed 1953. Only civilians executed for espionage in US. Venona confirmed Julius.',['rosenberg','kgb','atomic_spy']),
    _hc('CON068','Cambridge Five','Conspiracy','intelligence','1934-1951','UR','KGB',7,8,
       'Moles: Steal 2 face-down cards. Soviet +2 influence. Reveal 1.','British establishment spies for Soviet Union.','Kim Philby, Burgess, Maclean, Blunt, Cairncross. Defected. MI6 compromised for decades.',['kgb','mi6','cambridge_five'],'UK'),
    _hc('CON069','Venona Project','Conspiracy','intelligence','1943-1980','R','NSA',5,7,
       'Decrypt: Reveal ALL opponent face-down. Intelligence +3.','US/UK decrypted Soviet diplomatic traffic, exposed atomic spies.','349 Soviet agents identified. Kept secret from Truman. McCarthy could have used it.',['nsa','kgb','decrypt']),
    _hc('CON070','Operation Valkyrie','Conspiracy','military','1944','R','None',5,5,
       'Assassination Plot: Remove 1 Figure. +3 to military. Risk: Failure, execution.','German officers plotted to assassinate Hitler with briefcase bomb.','Stauffenberg. July 20 plot. Bomb moved. 5K+ executed in retaliation.',['hitler','assassination','nazi'],'Germany'),
    _hc('CON071','Dreyfus Affair','Conspiracy','foreign','1894-1906','R','None',5,6,
       'Frame-Up: Target Figure -4 influence. Reveal 2 face-down. Risk: Antisemitism scandal.','French Jewish officer wrongly convicted of treason, antisemitism exposed.','Zola "JAccuse." Real spy Esterhazy. Dreyfus pardoned. Herzl inspired Zionism.',['dreyfus','antisemitism','france'],'France'),
    _hc('CON072','Zinoviev Letter','Conspiracy','foreign','1924','R','MI6',4,6,
       'Forged Letter: Create fake Event. Social -3. Risk: Reveal = Scandal.','MI6 forged letter from Soviet leader urging British revolution.','Helped defeat Labour in 1924 election. Conservative victory. Forgery confirmed later.',['mi6','forgery','soviet'],'UK'),
    _hc('CON073','Klaus Fuchs','Conspiracy','intelligence','1941-1950','R','KGB',6,6,
       'Atom Spy: Soviet +4 to military. Destroy 1 nuclear card. Reveal 1.','German physicist passed Manhattan Project secrets to USSR.','Confessed 1950. 9 years prison. East Germany asylum. Hastened Soviet bomb by 2 years.',['kgb','atomic_spy','manhattan']),
    _hc('CON074','Operation Unthinkable','Conspiracy','military','1945','R','None',5,5,
       'Attack Russia: +3 to military. Destroy 2 Soviet cards. Risk: WWIII.','Churchill ordered secret plan to attack USSR right after WWII.','Deemed impossible. Soviet troop advantage 3:1. Scrapped. Revealed 1998.',['churchill','soviet','cold_war'],'UK'),
    # ── Batch 4 Conspiracies ──
    _hc('CON075','Operation PBSUCCESS','Conspiracy','foreign','1954','UR','CIA',7,7,
       'Guatemala Coup: Remove 1 democratic foreign Figure. Install puppet.','CIA overthrew Arbenz for United Fruit Company.','Eisenhower approved. Castillo Armas installed. 40-year civil war. 200K+ dead.',['cia','guatemala','united_fruit'],'Guatemala'),
    _hc('CON076','Project Artichoke','Conspiracy','intelligence','1951-1953','R','CIA',5,6,
       'Interrogation: Control 1 Figure for 1 turn. Reveal 1 face-down. Risk: Scandal.','CIA mind control research, precursor to MKUltra.','Hypnosis, LSD. "Can we get control of an individual?" Bluebird successor.',['cia','mind_control','experiment']),
    _hc('CON077','Propaganda Due','Conspiracy','foreign','1966-1981','UR','None',6,8,
       'Shadow Lodge: +3 to intelligence. Control 1 Org. Reveal 2 face-down.','Secretive Italian Masonic lodge, P2, embedded in government/military/intelligence.','Propaganda Due. Sindona, Calvi bank scandals. "Strategy of tension."',['p2','masonic','italy'],'Italy'),
    _hc('CON078','Operation Megiddo','Conspiracy','intelligence','1999','R','FBI',4,6,
       'Pre-Y2K: Reveal 3 face-down. Intelligence +1. Risk: Overreaction.','FBI report on potential domestic terrorism around Y2K.','Identified militias, religious extremists. Pre-9/11 intelligence. Never acted on.',['fbi','domestic_terror','y2k']),
    _hc('CON079','Operation Charly','Conspiracy','foreign','1979-1984','R','CIA',5,6,
       'Dirty War Export: Destroy 2 social cards. CIA +2. Risk: Condor link.','CIA helped export Argentine dirty war methods to Central America.','Galtieri. Death squads. Nun murders. France trained torturers.',['cia','argentina','dirty_war'],'Argentina'),
    _hc('CON080','Operation Bluebird','Conspiracy','intelligence','1950','R','CIA',4,5,
       'Memory Wipe: Negate 1 Figure effect. Reveal 1 face-down. Risk: MKUltra.','CIA first mind control program, renamed Artichoke.','Multiple personalities. Amnesia drugs. Hypnosis. Precursor to MKUltra.',['cia','mind_control','bluebird']),
    _hc('CON081','Banana Wars','Conspiracy','foreign','1898-1934','R','None',6,5,
       'Gunboat Diplomacy: +3 to military. Control 1 Central American Org.','US military interventions in Central America/Caribbean for fruit companies.','Nicaragua, Haiti, Dominican Republic, Honduras. Marines occupied for decades.',['us','central_america','intervention'],'Honduras'),
    _hc('CON082','Operation Washtub','Conspiracy','intelligence','1952-1956','R','CIA',4,5,
       'Stay-Behind: Place 2 face-down cards in Guatemala. +1 to intelligence.','CIA planted weapons caches in Guatemala for anti-communist resistance.','Nicaragua and Guatemala bases. Exposed 1997. Part of broader stay-behind network.',['cia','guatemala','stay_behind'],'Guatemala'),
    # ── Batch 5 Conspiracies: Advanced Political Operations ──
    _hc('CON083','Operation Timber Sycamore','Conspiracy','foreign','2012-2017','UR','CIA',7,6,
       'Arms Pipeline: +3 to military. Create 2 rebel cards. Risk: Blowback, ISIS.','CIA program to train and arm Syrian rebels against Assad.','$1B/year. Saudi co-funded. Weapons diverted to Al-Qaeda affiliate. Trump cancelled.',['cia','syria','arms'],'Syria'),
    _hc('CON084','Operation Gold','Conspiracy','intelligence','1953-1956','R','CIA',5,7,
       'Berlin Tunnel: Peek at 3 face-down. Intelligence +2. Risk: KGB knew all along.','CIA/MI6 tapped Soviet landlines in East Berlin.','George Blake, KGB mole, told Soviets from start. 441 days of useless intel.',['cia','mi6','berlin'],'Germany'),
    _hc('CON085','Operation Acoustic Kitty','Conspiracy','intelligence','1960s','U','CIA',2,4,
       'Cat Spy: Peek 1 face-down. Risk: $20M wasted, cat hit by taxi.','CIA implanted listening devices in cats to spy on Soviets.','First cat hit by taxi on test run. $20M 1960s dollars. Declassified 2001.',['cia','surveillance','absurd']),
    _hc('CON086','Operation Trust','Conspiracy','intelligence','1921-1929','R','KGB',5,7,
       'Honeypot: Steal 2 face-down cards. Reveal 1. Risk: Exposed by defector.','Soviet counter-intel operation posing as anti-Bolshevik monarchist movement.','Entrapped real dissidents. OGPU created fake opposition. Reuteman exposed.',['kgb','soviet','counter_intel'],'USSR'),
    _hc('CON087','Iran Nuclear Deal Sabotage','Conspiracy','foreign','2010-2018','R','Mossad',6,6,
       'Assassinate Scientists: Destroy 2 nuclear cards. Reveal 2 face-down. Risk: Escalation.','Israel assassinated Iranian nuclear scientists, sabotaged program.','Stuxnet, car bombs. 5 scientists killed. JCPOA opposed. Trump withdrew 2018.',['mossad','iran','nuclear'],'Iran'),
    _hc('CON088','Operation Fast and Furious','Conspiracy','intelligence','2006-2011','R','ATF',4,5,
       'Gun Walking: Give opponent 2 cards. Risk: Scandal +3 vs you.','ATF let guns walk to Mexican cartels to trace trafficking.','2K guns lost. Brian Terry killed. Holder contempt of Congress.',['atf','cartel','scandal'],'Mexico'),
    _hc('CON089','Five Eyes Echelon','Conspiracy','intelligence','1946-present','UR','NSA',7,9,
       'Global Intercept: Peek at ALL face-down cards. Intelligence +3. Risk: Ally backlash.','Five Eyes intelligence alliance: US, UK, Canada, Australia, NZ.','UKUSA Agreement. ECHELON, PRISM. Mass surveillance. Snowden exposed.',['nsa','five_eyes','surveillance'],'Global'),
    _hc('CON090','Operation Straggle','Conspiracy','foreign','1956-1958','R','CIA',4,5,
       'Destabilize Syria: Destroy 2 economic cards. +2 to military. Risk: Blowback.','CIA plotted to overthrow Syrian government, staged border incidents.','Turkey, Iraq involvement. Failed. Precursor to later Syria interventions.',['cia','syria','destabilization'],'Syria'),
    # ── Batch 6 Conspiracies: Covert Operations ──
    _hc('CON091','Operation Bodyguard','Conspiracy','military','1944','R','None',5,7,
       'Deception: Place 3 face-down dummy cards. Opponent wastes 2 attacks.','Allied deception plan to mislead Nazis about D-Day landing location.','Patton ghost army. Calais feint. Hitler held 15 divisions. Success.',['wwii','deception','d_day'],'UK'),
    _hc('CON092','Operation Sunrise','Conspiracy','intelligence','1945','R','OSS',4,6,
       'Secret Surrender: Negotiate 1 face-down. Peek 2. Intelligence +2.','OSS negotiated secret surrender of German forces in Italy ahead of formal end.','Allen Dulles. Operation Sunrise. SS General Wolff. Violated Yalta. Soviets furious.',['oss','wwii','dulles'],'Italy'),
    _hc('CON093','Operation LAC','Conspiracy','intelligence','1957-1958','U','CIA',3,5,
       'Biological Test: Destroy 1 social card. Peek 2. Risk: Public health scandal.','CIA released biological aerosols over US cities to test dispersion.','Zinc cadmium sulfide. St. Louis, Minneapolis. Declassified 1990s.',['cia','biological','experiment']),
    _hc('CON094','Operation Sea-Spray','Conspiracy','intelligence','1950','U','Navy',3,4,
       'Bio Attack Sim: Peek 1 face-down. Destroy 1 medical card. Risk: Lawsuits.','Navy sprayed Serratia bacteria over San Francisco to test biowarfare spread.','83rd outbreak. One death. Hospital infections. Kept secret 26 years.',['navy','biological','experiment']),
    _hc('CON095','Operation Dark Winter','Conspiracy','intelligence','2001','R','None',4,6,
       'Pandemic War Game: Peek 3 face-down. Negate 1 pandemic Event. Intelligence +2.','US bioterror simulation 3 months before 9/11, smallpox attack scenario.','Tara OToole. 3 states, 1M casualties simulated. Lockdown blueprint. Exposed health system gaps.',['bioterror','simulation','pandemic']),
    _hc('CON096','Operation Gladio B','Conspiracy','intelligence','1990s-present','UR','CIA',6,7,
       'Stay-Behind 2.0: Place 2 face-down. +2 to military. Risk: False-flag terrorism.','Alleged continuation of Gladio using Islamist proxies instead of fascists.','Sibel Edmonds exposed. Central Asia, Balkans. Chechen connections. Denied.',['cia','gladio','false_flag']),
    _hc('CON097','Operation Minaret','Conspiracy','intelligence','1960s-1973','R','NSA',5,7,
       'Warrantless Wiretap: Peek 3 face-down. Intelligence +2. Risk: Church Committee exposes.','NSA program warrantlessly intercepted telegrams of US citizens.','CIA, FBI, Secret Service recipients. 1.8M messages. Exposed by Church Committee 1975. Shamrock related.',['nsa','surveillance','warrantless']),
    _hc('CON098','Operation Merlin','Conspiracy','intelligence','2000','R','CIA',4,5,
       'Flawed Blueprints: Peek 1 face-down. Negate 1 nuclear card. Risk: Iran learns.','CIA tried to feed Iran flawed nuclear weapon designs to slow program.','Russian scientist delivered. Iran may have detected flaws. Risen exposed.',['cia','iran','nuclear'],'Iran'),
    # ── Batch 7 Conspiracies: Unproven Theories & Shadow Operations ──
    _hc('CON099','Princess Diana Assassination','Conspiracy','foreign','1997','UR','None',7,8,
       'Tunnel Plot: Remove 1 Figure. Reveal 3 face-down. Risk: Official ruling is accident.','Theory: Diana was assassinated for dating Dodi Fayed and threatening royal family.','Paparazzi chase. Mercedes in Pont de lAlma tunnel. White Fiat Uno. Mohamed Al Fayed allegations.',['diana','royal','assassination'],'UK'),
    _hc('CON100','Monarch Program','Conspiracy','intelligence','1950s-present','UR','CIA',7,9,
       'Trauma Programming: Control 2 Figures permanently. Risk: Discredited as fiction.','Alleged CIA continuation of MKUltra using trauma-based mind control to create alters.','Project Monarch never officially confirmed. Butterfly symbolism. Cathy OBrien claims.',['cia','mkultra','mind_control']),
    _hc('CON101','Tavistock Institute','Conspiracy','social','1947-present','R','None',5,7,
       'Social Engineering: +3 to media. Control 1 social card. Risk: Discredited.','Theory: Tavistock Institute shapes public opinion through psychological manipulation.','Real social science think tank. Conspiracy: mass psychology, cultural programming. Beatles?',['tavistock','psychology','social_engineering']),
    _hc('CON102','Sandy Hook Truthers','Conspiracy','domestic','2012','R','None',4,5,
       'Crisis Actor: Negate 1 social card. Reveal 2. Risk: Harassment lawsuits.','Conspiracy theory that Sandy Hook shooting was staged with crisis actors.','Alex Jones sued $1.5B. Parents harassed. FAKE hoax theories. Real children died.',['sandy_hook','conspiracy','truther']),
    _hc('CON103','Pizzagate','Conspiracy','domestic','2016','U','None',3,4,
       'Code Words: Peek 2 face-down. Reveal 1. Risk: Gunman investigates.','Theory that DC pizzeria Comet Ping Pong was front for trafficking ring based on leaked emails.','Edgar Welch fired rifle inside restaurant. No evidence. QAnon precursor.',['pizzagate','conspiracy','trafficking']),
    _hc('CON104','QAnon','Conspiracy','domestic','2017-present','UR','None',6,8,
       'The Storm: Reveal 3 face-down. +2 to all Conspiracy. Risk: Discredited, FBI threat.','Pro-Trump conspiracy movement claiming deep state cabal of satanic pedophiles runs government.','Q clearance patriot. Adrenochrome. JFK Jr alive? Prayed at rallies. January 6.',['qanon','conspiracy','deep_state']),
    _hc('CON105','Chemtrails','Conspiracy','military','1990s-present','U','None',3,5,
       'Aerosol Spray: Negate 1 environmental card. Peek 1 face-down. Risk: Debunked.','Theory that airplane contrails contain chemical/biological agents for weather control or population reduction.','Geoengineering. Aluminum, barium. Solar radiation management. IPCC mentions.',['chemtrails','geoengineering','conspiracy']),
    _hc('CON106','Flat Earth Network','Conspiracy','social','2014-present','C','None',2,4,
       'Dome Theory: Negate 1 space card. Risk: Laughed off board.','Theory that Earth is flat, NASA conceals the truth.','Antarctic ice wall. Firmament. FEIC conferences. NBA Kyrie. B.o.B.',['flat_earth','conspiracy','nasa']),
    _hc('CON107','Malcolm X Assassination Plot','Conspiracy','domestic','1965','R','FBI',6,7,
       'FBI Infiltration: Remove Malcolm X. Reveal 2 face-down. FBI -3.','Theory: FBI/Nation of Islam collaborated to assassinate Malcolm X.','COINTELPRO memo targeted him. Talmadge Hayer. NOI members convicted. $10M wrongful death suit 2021.',['malcolm_x','assassination','fbi']),
    _hc('CON108','USS Liberty Cover-Up','Conspiracy','military','1967','R','None',5,7,
       'Silenced: Reveal 3 face-down. Destroy 1 military. Risk: Survivors gagged.','Theory that USS Liberty attack was deliberate and covered up by both US and Israel.','Johnson may have recalled rescue planes. Survivors ordered silent. NSA transcripts sealed.',['uss_liberty','israel','coverup'],'Israel'),
    _hc('CON109','Operation 40','Conspiracy','intelligence','1960-1970','R','CIA',5,6,
       'Assassination Squad: Remove 1 Figure. +2 to intelligence. Risk: JFK connection.','CIA assassination team formed after Bay of Pigs, included Watergate burglars.','Frank Sturgis, E. Howard Hunt, Felix Rodriguez. JFK, Castro targets. Watergate connection.',['cia','assassination','bay_of_pigs']),
    _hc('CON110','Promis Software Backdoor','Conspiracy','intelligence','1980s-2000s','R','None',5,7,
       'Backdoor Access: Peek at ALL face-down. Intelligence +2. Risk: Casolaro death.','Inslaw PROMIS software allegedly modified with backdoor, sold to governments for spying.','Danny Casolaro died investigating. Octopus. Wackenhut. Israel, South Africa purchased.',['promis','inslaw','espionage']),
    _hc('CON111','Operation Staple','Conspiracy','intelligence','1950s','U','CIA',3,4,
       'Mind Control Files: Peek 2 face-down. Risk: Destroyed records.','Alleged CIA program destroying MKUltra records before Church Committee.','Helms ordered destruction 1973. 20 boxes destroyed. What was lost? Unknown scope.',['cia','mkultra','coverup']),
    _hc('CON112','Las Vegas Shooting Mystery','Conspiracy','domestic','2017','R','None',5,6,
       'Multiple Shooters: Reveal 3 face-down. Destroy 1 domestic. Risk: Lone gunman official.','Theory that 2017 Las Vegas massacre involved multiple shooters, not just Stephen Paddock.','58 killed. Mandalay Bay. Multiple windows? Hotel security timeline gaps. ISIS claim?',['las_vegas','conspiracy','mass_shooting']),
    _hc('CON113','Svalbard Seed Vault','Conspiracy','economic','2008-present','U','None',2,5,
       'Doomsday Vault: +2 to economic. Negate 1 military card. Risk: Conspiracy theories.','Arctic seed vault on Norwegian island, conspiracy theorists claim dual purpose.','Real seed bank. Conspiracy: elite survival bunker. GMO backup. Doomsday preparation.',['svalbard','seeds','conspiracy']),
    # ── Batch 8 Conspiracies: Deep Covert Operations ──
    _hc('CON114','Operation Cyclone II','Conspiracy','intelligence','1985-1989','UR','CIA',6,6,
       'Stinger Pipeline: +3 to military. Create 2 rebel cards. Risk: Blowback, Taliban.','CIA escalated Afghanistan aid with Stinger missiles, via ISI, to Mujahideen.','$630M/year. ISI distributed. Gulbuddin Hekmatyar. Bin Laden benefited. Blowback: 9/11.',['cia','afghanistan','stinger'],'Afghanistan'),
    _hc('CON115','Extraordinary Rendition','Conspiracy','intelligence','2001-present','UR','CIA',6,6,
       'Black Site: Remove 1 Figure. Control 1 face-down. Risk: Torture scandal.','CIA kidnapped suspects worldwide, sent to black sites for interrogation.','Poland, Romania, Lithuania hosted. Waterboarding. 1365 rendered. ACLU lawsuits.',['cia','torture','rendition']),
    _hc('CON116','Operation Momentum','Conspiracy','social','1960-1970','R','CIA',5,7,
       'Cultural Cold War: +3 to media. Control 1 media card. Peek 2 face-down. Risk: Congress exposes.','CIA cultural warfare program funding magazines, concerts, art to counter Soviet influence.','Encounter magazine. Congress for Cultural Freedom. Tom Braden. Abstract expressionism promoted.',['cia','culture','propaganda']),
    _hc('CON117','Total Information Awareness','Conspiracy','intelligence','2002-2003','R','DARPA',5,7,
       'Panopticon: Peek ALL face-down. Intelligence +3. Risk: Congress defunds, NSA continues.','DARPA program to track everything: credit cards, emails, phones, medical records.','Poindexter director. Adm. logo: all-seeing eye. Congress defunded. Continued at NSA.',['darpa','surveillance','poindexter']),
    _hc('CON118','Operation Speedboat','Conspiracy','intelligence','1980s','R','CIA',4,5,
       'Nicaragua Hit: Destroy 2 revolutionary cards. +2 to military. Risk: Iran-Contra exposure.','CIA directed Contra attacks on Nicaraguan infrastructure from Costa Rica.','Mining harbors. World Court ruled against US. $370M damages unpaid.',['cia','contra','nicaragua'],'Nicaragua'),
    # ── Batch 9 Conspiracies: Financial & Geopolitical ──
    _hc('CON119','BIS Nazi Gold','Conspiracy','economic','1930s-1945','R','BIS',5,6,
       'Washing Blood Gold: +3 to economic. Negate 1 Scandal. Risk: Exposure destroys BIS.','Bank for International Settlements accepted looted Nazi gold during WWII.','BIS transferred Czech gold to Reich. McFadden accused. Bretton Woods nearly dissolved BIS.',['bis','nazi','gold'],'Switzerland'),
    _hc('CON120','Vatican Ratlines','Conspiracy','intelligence','1945-1952','R','Vatican',6,6,
       'Escape Route: Remove 1 Figure from board. Place face-down. Risk: Exposure = Scandal.','Vatican helped Nazi and fascist officials escape to South America after WWII.','Bishop Hudal. Klaus Barbie, Mengele, Eichmann escaped. Red Cross passports. Peron Argentina.',['vatican','nazi','escape'],'Vatican'),
    _hc('CON121','Clinton Body Count','Conspiracy','domestic','1980s-present','L','None',8,7,
       'Arkancide: Remove 1 Figure. Reveal 3 face-down. Risk: Dismissed as conspiracy.','Theory that associates of the Clintons who died mysteriously were silenced.','Vince Foster. Seth Rich. Ron Brown. James McDougal. 50+ names on lists. No convictions.',['clinton','arkansas','conspiracy']),
    _hc('CON122','Operation Paperclip II','Conspiracy','intelligence','1990s','R','CIA',4,5,
       'Recruit Scientists: +2 to intelligence. Create 1 Figure from discard. Risk: Nazi connection.','Alleged continuation of Paperclip recruiting foreign scientists and intelligence officers post-Cold War.','Soviet scientists. Iraqi weapons experts. Bioweapons researchers. Visa waivers.',['cia','paperclip','recruitment']),
    _hc('CON123','Liberia Blood Timber','Conspiracy','economic','1990s-2003','R','None',5,4,
       'Conflict Resources: +3 to economic. Destroy 2 social. Risk: Charles Taylor exposure.','Timber and diamond trafficking funded Charles Taylor war in Liberia and Sierra Leone.','Blood diamonds. Timber concessions. Chinese, French firms. UN sanctions 2003.',['liberia','blood_diamonds','timber'],'Liberia'),
    # ── Batch 10 Conspiracies: Deep State Operations ──
    _hc('CON124','Operation Midnight Climax','Conspiracy','intelligence','1953-1966','R','CIA',4,5,
       'Sex Honey Trap: Control 1 Figure. Peek 2 face-down. Risk: Church Committee exposure.','CIA MKUltra subproject using safe houses with prostitutes to dose unwitting men with LSD.','Bordellos in San Francisco, NYC. George White. One-way mirrors. No useful intel gathered. Declassified 1975.',['cia','mkultra','honey_trap']),
    _hc('CON125','Operation Condor Training','Conspiracy','intelligence','1970s-1980s','R','CIA',5,6,
       'Interrogation School: Destroy 2 social Figures. +2 to intelligence. Risk: Condor exposure.','CIA trained Latin American intelligence services in interrogation and counterinsurgency at School of the Americas.','SOA/WHINSEC. Panama, Fort Benning. Manual de Contrainteligencia. Torture manuals. 60K+ disappeared across continent.',['cia','soa','dirty_war'],'South America'),
    _hc('CON126','The Enterprise','Conspiracy','intelligence','1984-1986','UR','NSA',6,7,
       'Shadow Government: Trade 3 cards secretly. +3 to intelligence. Risk: Iran-Contra exposure.','Oliver North shadow network bypassing Congress to fund Contras and run covert ops.','Secord, Hakim, Lake Resources. Swiss bank accounts. Arms pipeline. Ollie North shredding. Poindexter.',['iran_contra','north','shadow_gov']),
    _hc('CON127','Operation TP-AJAX Succession','Conspiracy','foreign','1953-1979','R','CIA',5,7,
       'Puppet Blowback: +2 to intelligence. Remove 1 Figure. Risk: Islamic Revolution 26 years later.','CIA installed Shah puppet after 1953 coup, trained SAVAK secret police, created conditions for 1979 revolution.','SAVAK trained by CIA/MI6. 30 years of terror. Oil guarantees. Nixon doctrine. Revolution: hostages, Khomeini, US embassy.',['cia','iran','savak'],'Iran'),
    _hc('CON128','Yellowcake Forgeries','Conspiracy','foreign','2001-2003','R','CIA',5,7,
       'Fake Nuclear Evidence: Create 1 fake intelligence card. +3 to military. Risk: Wilson exposes, Plame outed.','Forged documents claimed Iraq sought uranium from Niger, used to justify Iraq War.','Italian SISMI. Rocco Martino. Wilson debunked. Cheney office retaliated. Libby convicted. 16 words.',['iraq','wmd','forgery']),
    # ── Batch 11 Conspiracies: Corporate & Intelligence Operations ──
    _hc('CON129','Parallel Construction','Conspiracy','intelligence','1990s-present','UR','NSA',5,7,
       'Evidence Laundering: +2 to intelligence. Peek 2 face-down. Negate 1 Scandal. Risk: Fourth Amendment violation.','DEA and NSA practice of recreating evidence trails to hide surveillance origins from courts.','NSA tips to DEA. SOD. Reversing investigation direction. IRS DEA phone database. Reuters exposed 2013.',['nsa','dea','surveillance']),
    _hc('CON130','Operation CHAMPION','Conspiracy','intelligence','2013','R','FBI',4,6,
       'Insider Threat: +2 to intelligence. Control 1 Figure. Peek 1 face-down. Risk: Snowden retaliation.','Obama Insider Threat Program requiring federal employees to report suspicious coworkers.','1.5M+ cleared personnel. Snowden cited as catalyst. Leaks = mental health flag. Pentagon, NSA, CIA.',['nsa','insider_threat','surveillance']),
    _hc('CON131','Human Ecology Fund','Conspiracy','intelligence','1955-1965','U','CIA',3,6,
       'Behavioral Control: +2 to intelligence. +2 to social. Control 1 social card. Risk: MKUltra exposure.','CIA front organization funding behavioral research at universities via Society for the Investigation of Human Ecology.','MKUltra Subproject 84. Harvard, MIT, Yale grants. Personality studies. Gittinger. Used to identify interrogation subjects.',['cia','mkultra','psychology']),
    _hc('CON132','BlackRock Aladdin Control','Conspiracy','economic','1990s-present','UR','BlackRock',6,8,
       'Systemic Control: +3 to economic. Peek 3 face-down. Negate 1 financial Scandal. Risk: Too big to regulate.','BlackRocks Aladdin risk platform monitors $20T+ in assets, giving unprecedented visibility into global markets.','Centralized risk model. Fed used BlackRock for COVID bailouts. Owns shares in every S&P 500 company. Larry Fink.',['blackrock','aladdin','systemic']),
    _hc('CON133','Operation Paperclip Cover-Up','Conspiracy','intelligence','1945-1990','R','CIA',4,6,
       'Nazi Whitewash: +2 to intelligence. Negate 1 Scandal. Reveal 1 face-down. Risk: War criminal exposure.','CIA and US military concealed Nazi pasts of recruited scientists, scrubbed records.','Von Braun SS file. Arthur Rudolph deported 1984. Hubertus Strughold. JIOA altered files. Congress investigated 1980s.',['cia','nazi','paperclip']),
    # ── Batch 12 Conspiracies: Corporate Cover-Ups & Shadow Ops ──
    _hc('CON134','Exxon Knew','Conspiracy','economic','1977-2015','UR','None',5,7,
       'Climate Suppression: +3 to economic. Negate 1 climate Policy. Peek 2 face-down. Risk: Lawsuits, divestment.','Exxon scientists confirmed fossil fuel warming in 1970s, then funded denial for decades.','James Black 1977 internal memo. API task force. Climate denial network. NY, MA lawsuits. Rockefeller descendants divested.',['exxon','climate_denial','coverup']),
    _hc('CON135','Tobacco Research Council','Conspiracy','social','1954-1999','R','None',4,6,
       'Doubt is Our Product: +2 to media. Negate 2 health cards. Peek 1 face-down. Risk: Master Settlement.','Tobacco industry coordinated campaign to manufacture doubt about smoking and cancer.','Hill & Knowlton PR. "Doubt is our product." Tobacco Institute. Cigarette Papers. 1998 Master Settlement $206B.',['tobacco','pr','coverup']),
    _hc('CON136','Yukos Oil Expropriation','Conspiracy','foreign','2003-2007','UR','Kremlin',6,6,
       'Oligarch Takedown: +3 to economic. Remove 1 foreign Figure. Peek 2 face-down. Risk: Investment flight.','Putin jailed Khodorkovsky and seized Yukos oil company, redistributed to loyal oligarchs.','Khodorkovsky 10 years. Rosneft got assets. Sechin benefited. $40B expropriation. Foreign investors fled.',['russia','oil','oligarch'],'Russia'),
    _hc('CON137','Operation Mockingbird Media','Conspiracy','intelligence','1948-1976','R','CIA',5,7,
       'Press Infiltration: +2 to media. +2 to intelligence. Peek 2 face-down. Risk: Church Committee exposure.','CIA program to influence domestic and foreign media, recruit journalists as assets.','Carl Bernstein exposed 1977. 400+ journalists. NYT, CBS, Time, Newsweek. Propaganda placement. Foreign press. Watergate.',['cia','media','propaganda']),
    _hc('CON138','Five Eyes ECHELON Corporate Espionage','Conspiracy','intelligence','1990s-present','R','NSA',4,7,
       'Corporate Intercept: +2 to intelligence. +2 to economic. Peek 3 face-down. Risk: EU diplomatic crisis.','NSA used ECHELON to intercept European corporate communications, shared intel with US firms.','Boeing vs Airbus. Raytheon. 2001 EU report confirmed. Echelon eavesdropped on trade negotiations. Diplomatic uproar.',['nsa','echelon','corporate_espionage']),
]

SCANDALS = [
    _hc('SCN001','Watergate','Scandal','domestic','1972-1974','UR','FBI',7,9,
       'Cover-Up: Target Figure -5 influence. Reveal face-down cards.','Nixon campaign burgled DNC, cover-up.','Deep Throat, Saturday Night Massacre. Nixon resigned.',['watergate','nixon','coverup']),
    _hc('SCN002','Monica Lewinsky','Scandal','domestic','1998','R','Media',5,7,
       'Impeachment: Target Figure -3 influence. Media +3 power.','Clinton-Lewinsky affair, impeachment.','Starr Report, blue dress.',['clinton','impeachment','media']),
    _hc('SCN003','Iran-Contra Scandal','Scandal','foreign','1986-1987','UR','Media',6,7,
       'Arms Scandal: Foreign cards -3 influence. Reveal 1 Conspiracy.','Reagan admin arms to Iran, Contra funding.','North testified in uniform.',['iran_contra','reagan','scandal']),
    _hc('SCN004','Teapot Dome','Scandal','economic','1921-1923','U','Big Oil',4,5,
       'Oil Bribery: Target Figure -2 influence. +1 from discard.','Harding admin oil lease bribery.','Sec. Fall bribed. First cabinet member jailed.',['harding','oil','bribery']),
    _hc('SCN005','Pentagon Papers','Scandal','intelligence','1971','R','Media',6,8,
       'Truth Bomb: Reveal all face-down cards. Gov -3 influence.','Ellsberg leaked classified Vietnam history.','Nixon tried to block. SC ruled for press.',['vietnam','ellsberg','press']),
    _hc('SCN006','My Lai Massacre','Scandal','military','1968','R','Pentagon',7,5,
       'War Crime: Military -4 influence. Reveal 1 face-down.','US soldiers killed 500+ Vietnamese civilians.','Cover-up attempted. Calley convicted.',['vietnam','war_crime','coverup']),
    _hc('SCN007','ABSCAM','Scandal','domestic','1978-1980','U','FBI',4,6,
       'Sting: Target Figure -3 influence. FBI +2 power.','FBI sting, politicians bribed by fake sheik.','Sen. Williams convicted. 7 congressmen.',['fbi','bribery','sting']),
    _hc('SCN008','Keating Five','Scandal','economic','1989','U','Congress',3,5,
       'S&L Crisis: Economic -2 influence. McCain implicated.','5 senators intervened for S&L owner.','McCain career nearly ended.',['s&l','bribery','congress']),
    _hc('SCN009','Waco Siege','Scandal','domestic','1993','R','FBI',6,6,
       'Cult Raid: Destroy one domestic card. Both -2 power.','BATF/FBI raid, 76 dead.','Koresh. OKC bombing retaliation.',['waco','fbi','cult']),
    _hc('SCN010','Ruby Ridge','Scandal','domestic','1992','R','FBI',5,5,
       'Standoff: FBI -3 influence. +2 to Conspiracy cards.','FBI siege, Weaver family.','Sniper killed Vicki Weaver.',['fbi','standoff','sniper']),
    _hc('SCN011','Snowden Leak','Scandal','intelligence','2013','UR','NSA',7,9,
       'Whistleblower: All face-down revealed. NSA -4 influence.','Leaked NSA mass surveillance.','Charged under Espionage Act. Exiled.',['nsa','snowden','surveillance']),
    _hc('SCN012','Epstein Case','Scandal','domestic','2008-2019','L','None',8,10,
       'Blackmail Network: Control 2 Figures. Reveal all face-down.','Jeffrey Epstein, trafficking, connections.','Acosta deal, 2019 arrest, death in jail. Cameras off.',['epstein','trafficking','blackmail']),
    _hc('SCN013','Hunter Biden Laptop','Scandal','domestic','2020','R','Media',5,7,
       'Suppressed Story: Media -3 influence. Reveal 1 face-down.','Laptop story suppressed, later confirmed.','51 intel officials called it Russian disinfo.',['biden','media','election']),
    _hc('SCN014','Trump-Ukraine Call','Scandal','foreign','2019','R','White House',5,6,
       'Quid Pro Quo: Target -3 influence. Impeachment.','Trump asked Ukraine to investigate Bidens.','Impeached, acquitted. Zelensky involved.',['trump','ukraine','impeachment']),
    _hc('SCN015','COINTELPRO Exposed','Scandal','intelligence','1971','R','FBI',6,7,
       'FBI Exposed: FBI -4 influence. Surveillance cards revealed.','Citizens burgled FBI office.','Exposed COINTELPRO targeting civil rights.',['fbi','cointelpro','exposed']),
    _hc('SCN016','Bay of Pigs','Scandal','foreign','1961','R','CIA',6,6,
       'Failed Invasion: CIA -3 influence. Castro +2 power.','CIA-trained exiles invaded Cuba, failed.','JFK denied air support. Led to Missile Crisis.',['cia','cuba','failure'],'Cuba'),
    _hc('SCN017','Enron Scandal','Scandal','economic','2001-2002','UR','Wall Street',7,7,
       'Corporate Fraud: Wall Street -4 influence. Destroy 2 economic cards.','Enron bankruptcy, accounting fraud.','Arthur Andersen dissolved. Ken Lay died before sentencing. Skilling jailed.',['enron','fraud','wall_street']),
    _hc('SCN018','Bernie Madoff Ponzi','Scandal','economic','2008-2009','UR','Wall Street',7,6,
       'Ponzi: Destroy 3 economic cards. Wall Street -3 influence.','$65B Ponzi scheme, largest in history.','SEC ignored whistleblower tips. 150 years prison. Son suicide.',['madoff','ponzi','fraud']),
    _hc('SCN019','Phone Hacking Scandal','Scandal','social','2011','R','Media',5,7,
       'Murdoch Scandal: Media -4 influence. Reveal 2 face-down.','News of the World hacked phones of celebrities, murder victim.','Murdoch closed NOTW. Brooks acquitted. Settlements.',['murdoch','media','hacking'],'UK'),
    _hc('SCN020','Bridgegate','Scandal','domestic','2013','R','None',4,5,
       'Traffic Jam: Target Figure -2 influence. Reveal 1 face-down.','Christie aides closed bridge lanes for political revenge.','Christie denied knowledge. Aides convicted. Political career damaged.',['christie','new_jersey','revenge']),
    _hc('SCN021','Flint Water Crisis','Scandal','domestic','2014-2019','R','None',5,4,
       'Poisoned: Government -3 influence. Social cards +2 power.','Flint MI water supply switched, lead poisoning.','12 dead from Legionnaires. Officials charged. Racial environmental injustice.',['flint','water','racism']),
    _hc('SCN022','College Admissions Scandal','Scandal','domestic','2019','U','None',3,5,
       'Bribery Scheme: Target Figure -2 influence. +1 from discard.','Celebrities bribed college admissions.','Felicity Huffman, Lori Loughlin. Rick Singer mastermind.',['college','bribery','celebrity']),
    _hc('SCN023','Epstein Flight Logs','Scandal','domestic','2019','L','None',8,10,
       'Client List: Reveal ALL face-down cards. Control 3 Figures.','Epstein\'s flight logs name powerful figures.','Clinton, Trump, Prince Andrew, Dershowitz. Maxwell convicted.',['epstein','flight_logs','blackmail']),
    _hc('SCN024','Ghislaine Maxwell Trial','Scandal','domestic','2021-2022','UR','None',7,8,
       'Conviction: Epstein network -5 influence. Reveal 3 face-down.','Maxwell convicted of sex trafficking.','20 year sentence. Co-conspirators not named publicly.',['maxwell','trafficking','epstein']),
    _hc('SCN025','Twitter Files','Scandal','intelligence','2022-2023','R','None',6,7,
       'Platform Censorship: Media -3 influence. Reveal 2 face-down.','Internal Twitter docs showed government censorship requests.','FBI, DHS, White House pressured platforms. Taibbi, Weiss published.',['twitter','censorship','fbi']),
    _hc('SCN026','Sam Bankman-Fried FTX','Scandal','economic','2022','UR','Wall Street',7,6,
       'Crypto Collapse: Destroy 3 economic cards. Both lose 2 cards.','FTX exchange collapsed, $8B customer funds missing.','SBF convicted, 25 years. Democratic donor #2. Parents Stanford law.',['ftx','crypto','fraud']),
    _hc('SCN027','Clinton Foundation','Scandal','economic','2015-present','R','None',5,7,
       'Pay to Play: +2 to Scandal cards. Reveal 2 face-down.','Allegations: donations linked to State Dept access.','Haiti earthquake funds questions. CGI donors. No charges.',['clinton','foundation','corruption']),
    _hc('SCN028','Uranium One Deal','Scandal','foreign','2010','R','None',5,6,
       'Russian Uranium: Russian cards +2 influence. Reveal 1 face-down.','ROSATOM got US uranium assets, Clinton Foundation donations.','Hillary Clinton on CFIUS. $145M to foundation from investors. Disputed.',['russia','uranium','clinton']),
    _hc('SCN029','NSA warrantless surveillance','Scandal','intelligence','2005-2006','R','NSA',6,7,
       'Warrantless: NSA -3 influence. Reveal all NSA face-down.','Bush authorized warrantless wiretaps post-9/11.','NYT held story for a year. FISA court concerns. Amnestied telecoms.',['nsa','surveillance','bush']),
    _hc('SCN030','Operation Chaos','Scandal','intelligence','1960s-1970s','R','CIA',5,6,
       'Infiltration: CIA +2 power. Social cards -2 influence.','CIA infiltrated anti-war, student groups illegally.','Revealed by Church Committee. Domestic operations banned.',['cia','infiltration','protest']),
    _hc('SCN031','Iran Air 655 Shootdown','Scandal','military','1988','R','Pentagon',6,4,
       'Civilian Airliner: Military -3 influence. Destroy 1 foreign card.','USS Vincennes shot down Iranian airliner, 290 dead.','US: mistaken identity. Iran: deliberate. Compensation paid. Never apologized.',['iran','airliner','war_crime'],'Iran'),
    _hc('SCN032','My Lai Cover-up','Scandal','military','1968-1969','R','Pentagon',6,6,
       'Cover-up: Pentagon -3 influence. Reveal 2 face-down.','Military covered up My Lai for a year.','Ron Ridenhour exposed. Hugh Thompson stopped massacre. Calley pardoned by Nixon.',['vietnam','my_lai','coverup']),
    _hc('SCN033','DEA Drug War Profiteering','Scandal','intelligence','1970s-present','R','None',5,6,
       'Drug War Fraud: +2 to Cartel cards. -2 to FBI power.','DEA profited from asset forfeiture, informant deals.','CIA Contra crack connection. Mass incarceration. Asset forfeiture abuse.',['dea','drugs','profiteering']),
    # ── Global Scandals ──
    _hc('SCN034','1MDB Scandal','Scandal','foreign','2015','UR','None',7,6,
       'Sovereign Wealth Fraud: Destroy 2 economic cards. Reveal 2 face-down.','Malaysian sovereign wealth fund looted, $4.5B stolen.','Goldman Sachs, Jho Low, Najib Razak. Hollywood money laundering.',['malaysia','goldman','fraud'],'Malaysia'),
    _hc('SCN035','Dieselgate','Scandal','foreign','2015','UR','None',6,5,
       'Emissions Cheat: Economic -3 influence. Destroy 1 organization card.','VW cheated emissions tests, 40x NOx limit.','11M cars worldwide. $30B+ penalties. CEO jailed.',['volkswagen','fraud','emissions'],'Germany'),
    _hc('SCN036','Panama Papers','Scandal','foreign','2016','L','None',8,9,
       'Offshore Leaks: Reveal ALL face-down cards. Economic -3 influence globally.','11.5M documents exposed offshore tax havens.','Mossack Fonseca. World leaders implicated. Journalist killed.',['panama_papers','tax_haven','offshore'],'Global'),
    _hc('SCN037','Pandora Papers','Scandal','foreign','2021','UR','None',7,8,
       'More Offshore: Reveal 4 face-down. Economic -2 influence.','12M documents, more offshore wealth exposed.','King Abdullah, Putin, Blair. ICIJ investigation.',['pandora_papers','offshore','tax_haven'],'Global'),
    _hc('SCN038','Odebrecht Scandal','Scandal','foreign','2014-2017','UR','None',7,6,
       'Corruption Machine: Destroy 2 Latin American cards. Reveal 3 face-down.','Brazilian construction giant bribed across 12 countries.','$3.3B in bribes. Operation Car Wash. Presidents jailed.',['brazil','corruption','car_wash'],'Brazil'),
    _hc('SCN039','Gupta State Capture','Scandal','foreign','2010-2018','R','None',5,6,
       'State Capture: +2 to economic. Risk: -3 influence. Reveal 2 face-down.','Indian Gupta family influenced South African government.','Zuma ally. Cabinet appointments. Eskom contracts.',['south_africa','corruption','guptas'],'South Africa'),
    _hc('SCN040','Skripal Aftermath','Scandal','foreign','2018','R','KGB',5,5,
       'Chemical Weapons on Soil: Russia -3 influence. Destroy 1 diplomatic card.','Novichok killed UK civilian after Skripal attack.','Dawn Sturgess died. Russia expelled diplomats.',['russia','poison','uk'],'UK'),
    _hc('SCN041','Wagner Group Mutiny','Scandal','foreign','2023','R','Kremlin',6,5,
       'March on Moscow: Kremlin -4 influence. Military -2 power.','Prigozhin led Wagner mercenary mutiny against Putin.','"Justice march." Deal brokered by Lukashenko. Prigozhin died 2 months later.',['russia','wagner','putin'],'Russia'),
    _hc('SCN042','Nord Stream Explosion','Scandal','foreign','2022','R','None',5,6,
       'Energy Sabotage: Destroy 2 economic cards. Reveal 2 face-down.','Nord Stream pipelines blown up, who did it?','Hersh: US/Norway. Others: Ukraine/pro-Ukraine group. No definitive answer.',['nord_stream','sabotage','energy'],'Germany'),
    _hc('SCN043','FIFA Corruption','Scandal','foreign','2015','R','None',5,5,
       'World Cup Bribes: Economic -2 influence. Reveal 2 face-down.','FIFA officials indicted, $150M in bribes.','Qatar 2022, Russia 2018. Blatter, Platini. Swiss/US DOJ.',['fifa','corruption','bribery'],'Global'),
    # ── New Scandals ──
    _hc('SCN044','Credit Mobilier','Scandal','economic','1867-1873','R','None',5,6,
       'Railroad Graft: Economic -3 influence. Target Figure -2. +$4 treasury.','Union Pacific insiders created shell company to skim railroad funds.','Congressmen bribed with discounted stock. 1872 election scandal.',['credit_mobilier','railroad','graft']),
    _hc('SCN045','Black Sox Scandal','Scandal','domestic','1919','R','None',4,5,
       'Thrown World Series: Social -2. Destroy 1 sports card. Reveal 2.','8 Chicago White Sox players conspired to throw the World Series.','Shoeless Joe Jackson. Kenesaw Landis banned them for life.',['black_sox','baseball','gambling']),
    _hc('SCN046','WorldCom Fraud','Scandal','economic','2002','UR','Wall Street',6,6,
       '$11B Accounting Fraud: Destroy 2 economic cards. Wall Street -3.','Telecom giant inflated assets by $11B, largest fraud until then.','Ebbers convicted. 20K jobs lost. SOX law followed.',['worldcom','fraud','accounting']),
    _hc('SCN047','Purdue Pharma','Scandal','domestic','1999-2020','UR','None',7,6,
       'Opioid Crisis: Destroy 3 social cards. Medical -4. Reveal 2.','Sackler family pushed OxyContin, downplayed addiction.','500K+ overdose deaths. Bankruptcy settlement. Sacklers immune?',['purdue','opioid','sackler']),
    _hc('SCN048','Boeing 737 MAX','Scandal','economic','2018-2020','R','None',5,5,
       'MCAS Cover-Up: Destroy 1 military card. Economic -2. Reveal 2.','Boeing hid MCAS flaws, 346 dead in two crashes.','Self-certification. Lion Air, Ethiopian. Grounded worldwide.',['boeing','mcas','aviation']),
    _hc('SCN049','Wells Fargo Fake Accounts','Scandal','economic','2016','U','None',3,4,
       '2M Fake Accounts: Economic -1. Target Figure -2. +$2 treasury.','Wells Fargo employees created millions of unauthorized accounts.','Sales quotas. Fired 5K+ employees. $3B fines. Stumpf resigned.',['wells_fargo','fraud','banking']),
    _hc('SCN050','Solyndra Bankruptcy','Scandal','economic','2011','U','None',3,4,
       'Green Energy Boondoggle: Economic -2. Destroy 1 solar card.','Solar panel company went bankrupt after $535M federal loan guarantee.','Obama stimulus program. FBI raided. Taxpayers lost.',['solyndra','bankruptcy','green_energy']),
    # ── Batch 2 Scandals ──
    _hc('SCN051','Whiskey Ring','Scandal','economic','1875-1876','U','None',3,5,
       'Tax Evasion: Economic -2. Target Figure -2. Reveal 1 face-down.','Distillers bribed Treasury officials to avoid whiskey taxes.','Grant private secretary involved. 110 indicted. Impeachment calls.',['whiskey_ring','tax_evasion','grant']),
    _hc('SCN052','Star Route Scandal','Scandal','economic','1872-1882','U','None',3,4,
       'Postal Graft: Economic -1. Reveal 2 face-down. +$2.','Corrupt postal officials awarded lucrative routes to cronies.','Garfield investigated. Walsh, Brady acquitted. Jury tampering.',['star_route','postal','graft']),
    _hc('SCN053','Savings and Loan Crisis','Scandal','economic','1986-1995','UR','Congress',6,5,
       'S&L Collapse: Destroy 3 economic cards. Wall Street -3. $132B bailout.','1K+ savings and loan associations failed, taxpayer bailout.','Keating Five. Deregulation. Junk bonds. Milken.',['s&l','bailout','deregulation']),
    _hc('SCN054','Michael Milken','Scandal','economic','1986','R','Wall Street',5,6,
       'Junk Bond King: Economic -2. Destroy 1 Org. Reveal 2.','Drexel Burnham financier, junk bonds, insider trading.','SEC, Boesky. $600M fine. 2 years prison. Philanthropy redemption.',['milken','junk_bonds','insider_trading']),
    _hc('SCN055','Dred Scott Backlash','Scandal','domestic','1857','R','None',5,4,
       'Judicial Overreach: Social -3. Destroy 1 Policy. Lincoln +3 influence.','Supreme Court Dred Scott ruling sparked national outrage.','Lincoln-Douglas debates. House Divided speech. Republican Party grew.',['dred_scott','supreme_court','lincoln']),
    _hc('SCN056','October Surprise','Scandal','foreign','1980','R','None',5,6,
       'Secret Deal: Reveal 3 face-down. Target Figure -3. Risk: Conspiracy cards double.','Allegation that Reagan team delayed hostage release to win 1980 election.','Hostages released minutes after Reagan inauguration. Investigated, never proven.',['october_surprise','reagan','iran'],'Iran'),
    _hc('SCN057','Plessy v Ferguson','Scandal','domestic','1896','R','None',4,3,
       'Separate but Equal: Social -4. Segregation cards +3. Risk: 58 years of Jim Crow.','Supreme Court upheld racial segregation, "separate but equal."','Plessy 7-1 decision. Overturned by Brown v Board 1954.',['plessy','segregation','supreme_court']),
    # ── Batch 3 Scandals ──
    _hc('SCN058','Yazoo Land Fraud','Scandal','economic','1795-1814','U','None',3,4,
       'Land Swindle: Economic -2. Reveal 2 face-down. Destroy 1 territorial card.','Georgia officials sold vast land to speculators at bargain prices.','Peck v Fletcher. Supreme Court voided repeal. Fletcher v Peck first SC voiding state law.',['yazoo','georgia','land_fraud']),
    _hc('SCN059','Whitewater','Scandal','domestic','1978-1990s','R','None',4,5,
       'Real Estate Scandal: Target Figure -2. Reveal 2 face-down. Risk: Impeachment.','Clinton investment in failed Whitewater Development.','Starr investigation expanded. McDougal convicted. Clintons cleared.',['clinton','whitewater','starr']),
    _hc('SCN060','Tyco Corporate Fraud','Scandal','economic','2002','R','None',4,5,
       'Looting: Economic -2. Destroy 1 Org. Target Figure -3.','CEO Dennis Kozlowski looted $600M from Tyco International.','$6K shower curtain. $2M toga party. 8-25 years prison.',['tyco','fraud','kozlowski']),
    _hc('SCN061','Adelphia Collapse','Scandal','economic','2002','U','None',3,4,
       'Family Business: Economic -2. Reveal 1 face-down. Destroy 1 cable card.','Rigas family looted cable TV company, hid $2.3B debt.','John Rigas founded. Father/son jailed. Bankruptcy 6th largest at time.',['adelphia','cable','rigas']),
    _hc('SCN062','HealthSouth Fraud','Scandal','economic','2003','R','None',4,4,
       'Fake Earnings: Economic -2. Destroy 1 medical card. Reveal 1.','CEO Richard Scrushy inflated HealthSouth earnings by $1.4B.','First CEO tried under Sarbanes-Oxley. Acquitted, later jailed on bribery.',['healthsouth','fraud','scrushy']),
    _hc('SCN063','Refco Collapse','Scandal','economic','2005','U','None',3,4,
       'Hidden Debt: Economic -2. Destroy 1 financial card. Reveal 1.','Commodity broker concealed $430M in debt, collapsed after IPO.','IPO at $1.9B valuation. Bankruptcy within 2 months. CEO Phillip Bennett jailed.',['refco','fraud','commodity']),
    _hc('SCN064','Options Backdating','Scandal','economic','2006-2007','R','None',4,5,
       'Retrodated: Economic -2. Reveal 3 face-down. Target Figure -2.','Executives backdated stock options to inflate profits.','Apple, Brocade, Comverse. Reyes convicted. Hevesi jailed. Dozens implicated.',['options','backdating','fraud']),
    # ── Batch 4 Scandals ──
    _hc('SCN065','Theranos Fraud','Scandal','economic','2015-2018','UR','None',6,5,
       'Fake Blood Tests: Destroy 2 medical cards. Economic -2. Reveal 2.','Elizabeth Holmes claimed revolutionary blood testing, $9B valuation.','Walgreens partnership. Whistleblower Tyler Shultz. 19 years prison.',['theranos','holmes','fraud']),
    _hc('SCN066','Wirecard Scandal','Scandal','economic','2020','UR','None',6,6,
       'Missing $2B: Destroy 2 economic cards. Reveal 2 face-down.','German payment processor faked 1.9B euros in assets.','Auditor EY failed. CEO Braun arrested. BaFin regulator complicit.',['wirecard','fraud','germany'],'Germany'),
    _hc('SCN067','Lava Jato','Scandal','foreign','2014-2021','UR','None',7,6,
       'Car Wash: Destroy 3 economic cards. Reveal 3 face-down. Political -3.','Brazilian corruption probe, construction firms bribed politicians.','Odebrecht, Petrobras. Lula jailed then freed. Operation Car Wash.',['brazil','petrobras','corruption'],'Brazil'),
    _hc('SCN068','Jack Abramoff','Scandal','domestic','2005-2006','R','Congress',5,5,
       'Super Lobbyist: Target Figure -3. Reveal 2 face-down. Congress -2.','Lobbyist bribed congressmen, casino clients.','DeLay, Ney, Scanlon. Tribal clients fleeced. 4 years prison.',['abramoff','lobbying','bribery']),
    _hc('SCN069','Satyam Fraud','Scandal','foreign','2009','R','None',4,5,
       'Indias Enron: Destroy 2 economic cards. Reveal 1 face-down.','Indian IT company falsified $1.5B in assets.','Raju confessed. PwC auditor banned. Indias largest corporate fraud.',['satyam','fraud','india'],'India'),
    _hc('SCN070','Peanut Corporation','Scandal','domestic','2008-2009','R','None',4,3,
       'Tainted Food: Destroy 2 medical cards. Social -2. Reveal 1.','Peanut Corporation shipped salmonella-contaminated products, 9 dead.','CEO Parnell knew. 28 years prison. Food Safety Modernization Act followed.',['peanut','salmonella','food_safety']),
    _hc('SCN071','Tom DeLay Scandal','Scandal','domestic','2005','R','Congress',4,4,
       'Hammer: Congress -2 influence. Target Figure -2. Reveal 1.','House Majority Leader indicted for campaign finance violations.','TRMPAC. Money laundering. Convicted then overturned. Resigned.',['delay','campaign_finance','congress']),
    # ── Batch 5 Scandals: Modern Financial & Political ──
    _hc('SCN072','LIBOR Scandal','Scandal','economic','2008-2012','UR','None',6,7,
       'Rate Rigging: Destroy 2 economic cards. Reveal 3 face-down. Wall Street -3.','Banks manipulated London Interbank Offered Rate, $350T+ tied to it.','Barclays $450M fine. UBS, Deutsche, RBS. Tom Hayes convicted. Global rate rigging.',['libor','rate_rigging','fraud'],'UK'),
    _hc('SCN073','Danske Bank Scandal','Scandal','foreign','2007-2013','UR','None',6,6,
       'Russian Laundry: Destroy 2 economic cards. Reveal 3 face-down. Russian +2.','Estonian branch of Danske Bank laundered $234B from Russia.','Non-resident portfolio. UK, Cyprus shell companies. CEO resigned. Largest European laundering.',['danske','money_laundering','russia'],'Denmark'),
    _hc('SCN074','LuxLeaks','Scandal','foreign','2012-2015','R','None',4,6,
       'Tax Deals: Economic -2. Reveal 2 face-down. Destroy 1 corporate card.','PricewaterhouseCoopers leaked Luxembourg tax rulings.','340 companies. Amazon, Pepsi, IKEA. Secret advance tax agreements. Whistleblower Antoine Deltour jailed.',['luxleaks','tax','luxembourg'],'Luxembourg'),
    _hc('SCN075','Steinhoff Collapse','Scandal','foreign','2017','UR','None',6,6,
       'Accounting Fraud: Destroy 2 economic cards. Reveal 2 face-down. African -2.','South African-German retailer, $7B+ accounting fraud.','CEO Markus Jooste resigned. Shares crashed 96%. Largest SA corporate fraud.',['steinhoff','fraud','accounting'],'South Africa'),
    _hc('SCN076','Deutsche Bank Surveillance','Scandal','intelligence','2017-2020','R','None',5,6,
       'Spying: Peek 3 face-down. Intelligence +2. Reveal 1. Risk: CEO ousted.','Deutsche Bank hired private investigators to spy on critics and investors.','Ackermann, Jain, Cryan involved. Fake identities. Regulatory backlash.',['deutsche_bank','surveillance','espionage'],'Germany'),
    _hc('SCN077','Cambridge Analytica Scandal','Scandal','intelligence','2018','UR','None',7,8,
       'Data Harvesting: Reveal ALL face-down. Intelligence -3. Destroy 1 tech card.','87M Facebook profiles harvested for political targeting.','Cambridge Analytica. Brexit, Trump 2016. Zuckerberg testified. $5B FTC fine.',['cambridge_analytica','facebook','data']),
    _hc('SCN078','Swiss Leaks','Scandal','foreign','2015','R','None',4,6,
       'HSBC Files: Reveal 3 face-down. Economic -2. Destroy 1 bank card.','HSBC Swiss private bank helped clients evade taxes.','30K accounts. $100B+ in assets. G7, FIFA officials, dictators. ICIJ investigation.',['hsbc','tax_evasion','swiss'],'Switzerland'),
    # ── Batch 6 Scandals: Political & Financial ──
    _hc('SCN079','Iran-Contra Cover-Up','Scandal','intelligence','1986-1992','UR','CIA',7,8,
       'Shredding: Destroy 3 face-down. Reveal 2. CIA -3. Risk: Pardons.','Reagan administration destroyed evidence of arms-for-hostages deal.','North, Poindexter convicted then pardoned by Bush. Fawn Hall shredding.',['iran_contra','coverup','reagan']),
    _hc('SCN080','Watergate Tapes','Scandal','domestic','1973-1974','UR','None',6,8,
       'Smoking Gun: Reveal ALL face-down. Target Figure -5. Nixon -4.','Nixons secret tape recordings proved cover-up.','18.5 minute gap. Smoking gun tape. Saturday Night Massacre. Nixon resigned.',['watergate','nixon','tapes']),
    _hc('SCN081','Teapot Dome Revival','Scandal','economic','1921-1927','R','None',4,5,
       'Oil Bribery: Economic -2. Target Figure -3. Reveal 1.','Hardings Interior Secretary Fall leased oil reserves without competitive bidding.','Sinclair Oil. Fall first Cabinet member jailed. Elk Hills, Teapot Dome. Harding died.',['teapot_dome','oil','bribery']),
    _hc('SCN082','Pentagon Papers Leak','Scandal','intelligence','1971','UR','None',6,8,
       'Truth Bomb: Reveal ALL face-down. Intelligence -3. Destroy 1 military card.','Daniel Ellsberg leaked classified Pentagon study showing US gov knew Vietnam was unwinnable.','Nixon tried to stop publication. Supreme Court ruled for press. Plumbers unit created.',['pentagon_papers','vietnam','whistleblower']),
    _hc('SCN083','Tuskegee Experiment','Scandal','domestic','1932-1972','UR','None',7,3,
       'Medical Atrocity: Destroy 3 social cards. Medical -5. Reveal 2. Risk: Trust destroyed.','US government let 399 Black men with syphilis go untreated for 40 years to study disease.','Penicillin withheld. 128 died, 40 wives infected, 19 children born with it. Exposed 1972.',['tuskegee','syphilis','racism']),
    _hc('SCN084','COINTELPRO Blackmail','Scandal','intelligence','1964-1971','UR','FBI',6,7,
       'King Suicide Letter: Reveal 3 face-down. FBI -4. Destroy 1 civil rights card.','FBI sent MLK letter urging him to kill himself, harassed civil rights leaders.','William Sullivan. KING, there is only one thing left for you to do. Exposed 1971.',['cointelpro','fbi','mlk']),
    _hc('SCN085','Olympic Bribery','Scandal','foreign','1998-1999','R','None',3,5,
       'Gold Medal Graft: Economic -2. Reveal 2 face-down. Destroy 1 sports card.','Salt Lake City bribed IOC members for 2002 Winter Olympics.','10 IOC members expelled/resigned. Bid cities investigated. Reform followed.',['olympics','bribery','ioc']),
    # ── Batch 7 Scandals: Cover-Ups & Conspiracy Scandals ──
    _hc('SCN086','Church Committee Revelations','Scandal','intelligence','1975-1976','UR','None',6,9,
       'Family Jewels: Reveal ALL face-down. CIA -5. Intelligence -3. Destroy 1 CIA card.','Senate committee exposed CIA assassination plots, MKUltra, domestic surveillance.','Frank Church. Pike Committee. CIA targeted Castro, Lumumba. "Rogue elephant" myth.',['church_committee','cia','exposure']),
    _hc('SCN087','Iran-Contra Pardons','Scandal','domestic','1989-1992','R','White House',4,6,
       'Get Out of Jail: Negate 1 Scandal. Restore 3 face-down. Risk: Public outrage.','Bush Sr. pardoned 6 Iran-Contra figures including Weinberger, North, Poindexter.','Christmas Eve 1992. Walsh called it cover-up. Weinberger diary withheld. Bush own involvement?',['iran_contra','pardon','bush']),
    _hc('SCN088','Maxwell Media Empire Collapse','Scandal','foreign','1991','R','None',4,6,
       'Mirror Group: Economic -2. Reveal 2 face-down. Destroy 1 media card.','Robert Maxwell died mysteriously, empire collapsed, pension fund looted.','Found dead off yacht Lady Ghislaine. MI6/Mossad links. $600M pension hole. Daughter Ghislaine.',['maxwell','media','mossad']),
    _hc('SCN089','DNC Server Hack','Scandal','intelligence','2016','R','None',5,7,
       'Server Mystery: Reveal 2 face-down. Intelligence -2. Risk: CrowdStrike, no FBI inspection.','DNC refused FBI access to hacked servers, relied on private CrowdStrike analysis.','Seth Rich theories. Awan brothers. Imran Awan. Debbie Wasserman Schultz. Server destroyed.',['dnc','hack','crowdstrike']),
    _hc('SCN090','Acosta Sweetheart Deal','Scandal','domestic','2008','UR','None',6,8,
       'Immunity: Negate 1 Scandal. Restore 3 face-down. Risk: Co-conspirator protection.','Labor Secretary Acosta gave Epstein 2008 non-prosecution agreement protecting co-conspirators.','13-month work release. No federal charges. 36 victims. Sealed deal. Acosta resigned 2019.',['acosta','epstein','immunity']),
    # ── Batch 8 Scandals: Intelligence Failures & Political Scandals ──
    _hc('SCN091','Plame Affair','Scandal','intelligence','2003','UR','White House',6,7,
       'Outed Spy: Destroy 1 CIA card. Intelligence -3. Reveal 2 face-down.','Cheney aide Scooter Libby leaked CIA officer Valerie Plames identity to punish husband Wilson.','Iraq yellowcake debunked. Novak column. Libby convicted, commuted by Bush. Armitage source.',['plame','cia','libby']),
    _hc('SCN092','Operation Greylord','Scandal','domestic','1980-1984','R','FBI',4,5,
       'Judicial Sting: Target Figure -3 influence. FBI +2. Reveal 1 face-down. Destroy 1 judicial card.','FBI sting in Chicago, judges and lawyers taking bribes, fixing cases.','17 judges convicted. 92 indictments. Marcy Biland. Operation Gambat. Judicial corruption exposed.',['fbi','bribery','judicial']),
    _hc('SCN093','Iraq WMD Intelligence Failure','Scandal','intelligence','2002-2003','UR','CIA',7,6,
       'No WMD Found: Intelligence -5. Destroy 2 military cards. Reveal 2 face-down.','US invaded Iraq based on WMD claims, no weapons found after occupation.','Curveball. Yellowcake. Aluminum tubes. Mobile labs. $2T war. 500K+ dead. ISG report.',['iraq','wmd','intelligence_failure']),
    _hc('SCN094','CIA Torture Report','Scandal','intelligence','2014','UR','CIA',7,8,
       'Enhanced Interrogation: CIA -5. Reveal 3 face-down. Destroy 1 intelligence.','Senate report exposed CIA torture program: waterboarding, rectal feeding, mock executions.','6400-page report. Feinstein. Panetta review. CIA hacked Senate computers. No prosecutions.',['cia','torture','senate']),
    _hc('SCN095','Twitter Files Revelations','Scandal','domestic','2022-2023','R','None',4,6,
       'Censorship Exposed: Media -2. Reveal 2 face-down. Peek 1. Risk: Partisan framing debate.','Internal Twitter documents revealed government pressure to suppress content and accounts.','Matt Taibbi, Bari Weiss. FBI liaison. Hunter laptop suppression. Election interference debate. Twitter/X released.',['twitter_files','media','censorship']),
    # ── Batch 9 Scandals: Financial & Political Scandals ──
    _hc('SCN096','Clinton Pardon Scandal','Scandal','domestic','2001','R','White House',5,7,
       'Midnight Pardons: Negate 2 Scandals. Restore 3 face-down. Risk: Congressional investigation.','Clinton issued 140 pardons on last day, including Marc Rich, FALN members.','Denise Rich donations. Hugh Rodham payments. Pardongate. Congressional hearings. Bar revoked.',['clinton','pardon','rich']),
    _hc('SCN097','HSBC Cartel Money Laundering','Scandal','economic','2012','UR','None',6,6,
       'Washing Cartel Cash: Economic -3. Destroy 2 cartel cards. Risk: No prosecutions.','HSBC laundered $881M for cartels, violated sanctions on Iran, Sudan, Libya.','Too big to jail. $1.9B fine, no indictments. Eric Holder: banks too big. Cartel tunnels.',['hsbc','cartel','money_laundering']),
    _hc('SCN098','Manafort Ukraine Payments','Scandal','foreign','2004-2014','R','None',4,6,
       'Black Ledger: Target Figure -3 influence. Reveal 2 face-down. Risk: Trump campaign exposure.','Paul Manafort took millions from pro-Russian Ukraine politicians, undisclosed lobbying.','Yanukovych Party of Regions. Black ledger. $12.7M cash. FARA violation. Mueller prosecuted.',['manafort','ukraine','russia']),
    _hc('SCN099','1MDB Embezzlement','Scandal','economic','2009-2015','UR','None',6,7,
       'Sovereign Wealth Heist: Economic -4. Destroy 1 Organization. Reveal 2 face-down.','Malaysias $4.5B sovereign wealth fund looted by PM Najib Razak and associates.','Goldman Sachs $600M fees. Jho Low. Wolf of Wall Street financing. Red Granite Pictures. Najib convicted 2020.',['1mdb','malaysia','goldman']),
    _hc('SCN100','Epstein Black Book','Scandal','social','2019-2024','L','None',8,9,
       'Little Black Book: Reveal ALL face-down. Control 2 Figures. Peek 3. Risk: Names still sealed.','Epsteins private contact book with powerful contacts beyond flight logs.','Gates, Cuomo, Bloomberg, Dershowitz, Hofstadter. 1,510 entries. Unsealed 2024. Many names still contested.',['epstein','black_book','blackmail']),
    # ── Batch 10 Scandals: Political & Intelligence Scandals ──
    _hc('SCN101','Petraeus Affair','Scandal','domestic','2012','R','None',4,6,
       'Fallen General: Target Figure -4 influence. CIA -2. Reveal 2 face-down.','CIA director David Petraeus resigned over affair with biographer Paula Broadwell.','Classified documents on her laptop. Jill Kelley whistleblower. FBI agent shirtless photo. No jail time.',['petraeus','affair','classified']),
    _hc('SCN102','ATF Gun Walking Scandal','Scandal','foreign','2006-2011','UR','ATF',5,6,
       'Gun Walking: Destroy 2 domestic. +2 to intelligence. Risk: Border Patrol agent killed.','ATF allowed guns to walk to Mexican cartels to trace networks, lost track of 2,000+ weapons.','Brian Terry killed. DOJ held in contempt of Congress. Eric Holder. 2K+ guns. Mexico protested.',['atf','guns','mexico']),
    _hc('SCN103','Uranium One','Scandal','economic','2010','R','None',4,7,
       'Russian Uranium: Economic -2. Intelligence -2. Reveal 2 face-down. Risk: Partisan weaponization.','Rosatom acquired Canadian uranium mining rights, Clinton Foundation received donations.','Frank Giustra donations. CFIUS approved. Hillary State Dept. 20% US uranium capacity. Hannity obsessed.',['uranium_one','russia','clinton']),
    _hc('SCN104','CIA Senate Hacking','Scandal','intelligence','2014','R','CIA',4,5,
       'Spying on Senate: CIA -3. Reveal 3 face-down. Negate 1 intelligence.','CIA searched Senate Intelligence Committee computers during torture report investigation.','Brennan denied, then admitted. Feinstein accused CIA. IG found improper search. No prosecutions.',['cia','senate','torture_report']),
    _hc('SCN105','FISA Court Abuses','Scandal','intelligence','2016-2020','UR','FBI',6,7,
       'Warrant Abuse: Intelligence -3. Reveal 3 face-down. Destroy 1 intelligence. Risk: Carter Page exposure.','FISA court found FBI abused surveillance authority, including Carter Page warrants.','Horowitz report. 17 errors. Crossfire Hurricane. Steele dossier. FISC rebuke. Woods procedures violated.',['fisa','fbi','surveillance']),
    # ── Batch 11 Scandals: Corporate & Political Scandals ──
    _hc('SCN106','Credit Suisse Archegos Collapse','Scandal','economic','2021','UR','None',5,6,
       'Family Office Blowup: Destroy 2 economic cards. Reveal 2 face-down. Risk: $5.5B loss, systemic risk.','Credit Suisse lost $5.5B when Archegos Capital Management defaulted on margin calls.','Bill Hwang. Total return swaps. Goldman, Morgan Stanley escaped. Credit Suisse caught. CEO resigned. Final nail in Credit Suisse coffin.',['credit_suisse','archegos','derivatives']),
    _hc('SCN107','Abu Ghraib Torture','Scandal','foreign','2003-2004','UR','Pentagon',6,7,
       'Torture Photos: Destroy 2 diplomatic. Military -3. Reveal 2 face-down. Risk: Recruiting tool for insurgents.','US military police tortured and humiliated Iraqi detainees at Abu Ghraib prison.','Lynndie England, Charles Graner. Hooded man, leash, pyramid. Taguba Report. Rumsfeld responsible. No high-level convictions.',['abu_ghraib','torture','iraq']),
    _hc('SCN108','Robinhood Trading Halt','Scandal','economic','2021','R','None',4,5,
       'Market Manipulation: Economic -2. Destroy 1 tech card. Peek 2 face-down. Risk: Citadel conflict of interest.','Robinhood halted retail buying of GameStop and meme stocks, protecting hedge fund shorts.','Vlad Tenev. Citadel payment for order flow. NSCC collateral demand. Congressional hearing. PFOF conflict.',['robinhood','gamestop','citadel']),
    _hc('SCN109','Boeing 737 MAX Crashes','Scandal','economic','2018-2020','UR','None',5,6,
       'Corporate Murder: Destroy 2 economic. Reveal 2 face-down. Risk: MCAS cover-up, FAA capture.','Boeing 737 MAX crashed twice killing 346, MCAS software hidden from pilots.','Lion Air, Ethiopian Airlines. FAA delegated certification to Boeing. $2.5B settlement. No exec jailed.',['boeing','faa','corporate']),
    _hc('SCN110','Ailes Harassment Scandal','Scandal','social','2016-2017','R','Media',4,7,
       'Fox Culture: Media -2. Control 2 social Figures. Reveal 2 face-down. Risk: OReilly, Hannity exposure.','Fox News CEO Roger Ailes ousted after sexual harassment lawsuits from Gretchen Carlson, Megyn Kelly.','$40M severance. Roger Ailes. Bill OReilly $32M settlement. Fox paid out $100M+. Ailes died 2017. Culture of harassment.',['ailes','fox','harassment']),
    # ── Batch 12 Scandals: Environmental, Corporate & Cyber ──
    _hc('SCN111','BP Deepwater Horizon','Scandal','economic','2010','UR','None',6,7,
       'Oil Spill: Destroy 3 economic. Oil -3. Reveal 2 face-down. Risk: $65B liability, 11 dead.','BP rig exploded in Gulf of Mexico, worst oil spill in history, 210M gallons.','Macondo well. Haliburton cement. Transocean rig. 11 dead. $20B fund. Tony Hayward "Id like my life back."',['bp','oil_spill','gulf']),
    _hc('SCN112','Volkswagen Emissions Scandal','Scandal','economic','2015','UR','None',5,6,
       'Defeat Devices: Destroy 2 economic. Reveal 2 face-down. Risk: $30B+ fines, diesel collapse.','VW installed software to cheat emissions tests, 11M cars worldwide emitted 40x legal NOx.','EPA exposed. Winterkorn resigned. $30B+ penalties. CRD scandal. Audi, Porsche implicated. Dieselgate.',['volkswagen','emissions','fraud'],'Germany'),
    _hc('SCN113','SolarWinds Hack','Scandal','intelligence','2020','UR','None',6,8,
       'Supply Chain Attack: Intelligence -3. Peek 3 face-down. Reveal 2. Risk: Russian SVR infiltration','Russian intelligence compromised SolarWinds software, infiltrated 18,000+ organizations including US government.','SVR Cozy Bear. Orion platform. Treasury, Commerce, DHS breached. FireEye discovered. Microsoft. 9 months undetected.',['solarwinds','russia','cyber']),
    _hc('SCN114','Colonial Pipeline Ransomware','Scandal','economic','2021','R','None',4,5,
       'Pipeline Shutdown: Economic -3. Destroy 1 energy card. Reveal 1 face-down. Risk: Gas shortages, panic buying.','DarkSide ransomware attack shut down major US fuel pipeline for 6 days, gas crisis on East Coast.','Colonial Pipeline. 5,500 miles. $4.4M ransom paid. FBI recovered some. Panic buying. DOT emergency. DarkShadow.',['colonial','ransomware','cyber']),
    _hc('SCN115','FTX Collapse','Scandal','economic','2022','UR','None',6,7,
       'Crypto Fraud: Destroy 3 economic. Reveal 3 face-down. Risk: $8B missing, political donations scandal.','Sam Bankman-Frieds crypto exchange collapsed, $8B in customer funds missing.','Alameda Research. Caroline Ellison. Bahamian villa. Democratic donor #2. Effective altruism fraud. 25 years prison.',['ftx','crypto','fraud']),
]

ORGS = [
    _hc('ORG001','CIA','Organization','intelligence','1947-present','UR','CIA',8,9,
       'The Agency: +2 influence to intelligence. Peek 1 opponent card/turn.','Central Intelligence Agency.','Coups, renditions, black sites. 1947 NSA Act.',['intelligence','covert']),
    _hc('ORG002','FBI','Organization','intelligence','1908-present','UR','FBI',7,8,
       'Federal Bureau: +2 power to Scandal cards. Blackmail 1 Figure.','Domestic intelligence, law enforcement.','Hoovers files, COINTELPRO, surveillance.',['fbi','domestic','surveillance']),
    _hc('ORG003','NSA','Organization','intelligence','1952-present','UR','NSA',7,9,
       'Signal Intel: Reveal 1 face-down/turn. +2 to Conspiracy cards.','National Security Agency.','PRISM, bulk collection, Five Eyes.',['nsa','surveillance','five_eyes']),
    _hc('ORG004','Federal Reserve','Organization','economic','1913-present','UR','Federal Reserve',6,10,
       'Money Printer: +1 card/turn. Control economic Event cards.','US central bank.','Private banks own stock. Audit the Fed.',['fed','banking','money']),
    _hc('ORG005','Pentagon','Organization','military','1943-present','R','Pentagon',8,7,
       'War Machine: +3 power to military. +2 influence to foreign Policy.','Dept of Defense HQ.','$800B+ budget. Military-industrial complex.',['military','defense']),
    _hc('ORG006','Wall Street','Organization','economic','1792-present','R','Wall Street',6,8,
       'The Street: +2 influence to economic. Risk: Crash cards double.','Financial district, exchanges.','2008 crash, bailouts, insider trading.',['finance','banks']),
    _hc('ORG007','Big Pharma','Organization','economic','1990s-present','R','Big Pharma',5,7,
       'Drug Money: +2 influence. Negate one health Policy. Risk: Scandal.','Pharmaceutical industry.','Opioid crisis, FDA capture, pricing.',['pharma','opioid','lobby']),
    _hc('ORG008','Big Oil','Organization','economic','1900s-present','R','Big Oil',6,7,
       'Black Gold: +2 power. Negate environmental Policy. Risk: Scandal.','Oil industry, petroleum lobby.','Exxon climate cover-up, wars for oil.',['oil','energy','lobby']),
    _hc('ORG009','Mainstream Media','Organization','social','1920s-present','R','Media',5,8,
       'Narrative Control: +3 influence to Scandal. Negate one Conspiracy.','TV networks, major newspapers.','Mockingbird, narrative framing.',['media','propaganda']),
    _hc('ORG010','Military-Industrial Complex','Organization','military','1961-present','UR','Military-Industrial',7,8,
       'Perpetual War: +2 power to military/turn. Both pay 1 card.','Eisenhower warned of it.','Defense contractors, revolving door.',['military','defense','lobby']),
    _hc('ORG011','KGB','Organization','intelligence','1954-1991','UR','KGB',8,8,
       'Soviet Intel: Steal 1 card. +2 to Conspiracy cards.','Soviet secret police.','Putin was KGB. Active measures.',['soviet','intelligence','putin'],'USSR'),
    _hc('ORG012','Mossad','Organization','intelligence','1949-present','R','Mossad',7,7,
       'By Way of Deception: Assassinate 1 foreign Figure.','Israeli intelligence.','Targeted kills, Stuxnet, Dubai hit.',['israel','intelligence','assassination'],'Israel'),
    _hc('ORG013','UN','Organization','foreign','1945-present','U','UN',4,7,
       'World Body: +2 influence to foreign Policy. Negate 1 military Event.','United Nations.','Security Council vetoes limit power.',['un','diplomacy'],'Global'),
    _hc('ORG014','WHO','Organization','social','1948-present','U','WHO',4,6,
       'Global Health: Negate pandemic Event. +2 to health Policy.','World Health Organization.','COVID response criticized. China influence.',['who','health'],'Global'),
    _hc('ORG015','Trilateral Commission','Organization','economic','1973-present','U','Trilateral Commission',4,7,
       'Global Coordination: +2 influence to Organization cards.','Elite forum, NA/Europe/Japan.','Conspiracy: shadow government. Carter member.',['elite','global','conspiracy'],'Global'),
    _hc('ORG016','DEA','Organization','intelligence','1973-present','R','None',5,5,
       'Drug War: +2 power to FBI. Cartel cards +2 power. Social -1 influence.','Drug Enforcement Administration.','Asset forfeiture, informants, cartel collusion. Failed drug war.',['dea','drugs','forfeiture']),
    _hc('ORG017','ATF','Organization','intelligence','1972-present','U','None',3,4,
       'Alcohol Tobacco Firearms: +1 power to Scandal cards. Risk: Waco.','Bureau of Alcohol, Tobacco, Firearms and Explosives.','Fast and Furious, Waco, Ruby Ridge. Underfunded, politicized.',['atf','guns','scandal']),
    _hc('ORG018','DHS','Organization','intelligence','2002-present','R','None',6,6,
       'Homeland Security: +2 power to intelligence. Social -1 influence. Border +2.','Department of Homeland Security.','Created post-9/11. ICE, CBP, TSA. Border separation controversy.',['dhs','border','surveillance']),
    _hc('ORG019','Council on Foreign Relations','Organization','economic','1921-present','U','CFR',4,7,
       'Policy Elite: +2 influence to foreign Policy cards. +1 to Organization cards.','Elite foreign policy think tank.','Every Sec of State member. Conspiracy: globalist. Journalist network.',['cfr','elite','foreign_policy']),
    _hc('ORG020','Skull & Bones','Organization','intelligence','1832-present','R','Skull & Bones',4,7,
       'Secret Society: +2 influence to Figure cards. Reveal 1 face-down.','Yale secret society, elite members.','Bush 41, Bush 43, Kerry. "Bonesmen." Conspiracy: power network.',['skull_bones','elite','secret_society']),
    # ── Global Organizations ──
    _hc('ORG021','SVR','Organization','intelligence','1991-present','UR','KGB',7,8,
       'Post-Soviet Intel: +2 to Conspiracy. Peek 1 card/turn. +1 to KGB cards.','Russian Foreign Intelligence Service, KGB successor.','Litvinenko, Skripal operations. Active measures. Cyber.',['svr','russia','intelligence'],'Russia'),
    _hc('ORG022','Shin Bet','Organization','intelligence','1948-present','R','None',6,7,
       'Internal Security: +2 to intelligence. Negate one domestic Scandal.','Israel Security Agency, internal intelligence.','Interrogation techniques. Targeted assassinations.',['israel','intelligence','security'],'Israel'),
    _hc('ORG023','MI6','Organization','intelligence','1909-present','UR','MI6',7,8,
       'Secret Service: +2 to intelligence. Peek 1 face-down/turn.','British foreign intelligence.','Cambridge Five, Goldfinger, Brexit disinfo.',['mi6','uk','intelligence'],'UK'),
    _hc('ORG024','Stasi','Organization','intelligence','1950-1990','R','Stasi',6,7,
       'East German Secret Police: +2 to surveillance. Reveal 2 face-down.','Ministry for State Security.','1 in 63 East Germans were informants. Files preserved.',['stasi','surveillance','east_germany'],'Germany'),
    _hc('ORG025','World Economic Forum','Organization','economic','1971-present','UR','None',5,9,
       'Davos Elite: +3 influence to Organization. +2 to economic. Reveal 1 face-down.','International organization for public-private cooperation.','Schwab, stakeholder capitalism, Great Reset.',['wef','davos','globalist'],'Switzerland'),
    _hc('ORG026','IMF','Organization','economic','1944-present','UR','IMF',6,8,
       'Global Lender: +2 to economic. Negate one debt crisis. Structural adjustment.','International Monetary Fund.','Austerity, bailouts. US veto power. Conditionality.',['imf','economy','bailout']),
    _hc('ORG027','Bilderberg Group','Organization','economic','1954-present','R','Bilderberg',4,8,
       'Annual Conference: +2 influence to Figure. Peek 2 face-down.','Secretive annual conference of elites.','No minutes, no press. Conspiracy: world government.',['bilderberg','elite','secret_society']),
    _hc('ORG028','Blackwater','Organization','military','1997-2014','R','None',6,5,
       'Private Military: +3 power to military. Risk: Scandal cards double.','Private military company, Iraq war.','Nisour Square massacre. Erik Prince. Rebranded Academi.',['blackwater','military','iraq']),
    _hc('ORG029','East India Company','Organization','economic','1600-1858','UR','British Crown',7,8,
       'Corporate Empire: +3 to economic. +2 to military. Risk: Opium cards.','British trading corporation, ruled India.','Opium trade, Bengal famine. First multinational.',['british_crown','imperialism','opium'],'UK'),
    _hc('ORG030','OPEC','Organization','economic','1960-present','UR','OPEC',6,7,
       'Oil Cartel: +3 to economic. Oil cards +2 power. Risk: Price wars.','Organization of Petroleum Exporting Countries.','1973 oil embargo. Price crashes. Saudi dominance.',['opec','oil','cartel']),
    # ── New Organizations ──
    _hc('ORG031','Palantir','Organization','intelligence','2003-present','R','None',6,8,
       'All-Seeing: +3 to intelligence. Peek 2 face-down/turn. Risk: Privacy Scandal.','Peter Thiel data analytics firm, CIA/ICE contracts.','Gotham, Foundry. NYPD, ICE, military. Surveillance capitalism.',['palantir','surveillance','data']),
    _hc('ORG032','Wagner Group','Organization','military','2014-2023','UR','Kremlin',7,5,
       'Mercenary Army: +4 to military. Risk: Mutiny Scandal. Economic -2.','Russian private military company, Prigozhin.','Syria, Africa, Ukraine. Africa Corps successor.',['wagner','mercenary','russia'],'Russia'),
    _hc('ORG033','SpaceX','Organization','military','2002-present','UR','None',7,7,
       'Mars or Bust: +3 to military. Economic +2. Negate one Russian space card.','Elon Musk aerospace company, reusable rockets.','Starlink, Falcon, Starship. Pentagon contracts. Ukraine internet.',['spacex','musk','starlink']),
    _hc('ORG034','BlackRock','Organization','economic','1988-present','UR','BlackRock',7,9,
       'Asset Giant: +4 to economic. Control 1 Org card. Risk: Conflict of interest.','World largest asset manager, $10T+ AUM.','Aladdin. ESG push. Owns shares in everything. Larry Fink.',['blackrock','esg','finance']),
    _hc('ORG035','United Nations','Organization','foreign','1945-present','R','UN',5,7,
       'World Body: +2 to social. +2 to diplomatic. Risk: Veto paralysis, useless.','International organization for peace, security, cooperation.','Security Council vetoes. Peacekeepers. WHO, UNESCO.',['un','diplomacy','globalist'],'Global'),
    # ── Batch 2 Organizations ──
    _hc('ORG036','Pinkerton Detective Agency','Organization','intelligence','1850-present','R','None',5,6,
       'Private Eyes: +2 to intelligence. Destroy 1 labor card. Peek 1 face-down.','Private detective/security agency, union busting.','Lincoln employed them. Homestead Strike. Still exists as Securitas subsidiary.',['pinkerton','labor','surveillance']),
    _hc('ORG037','Standard Oil','Organization','economic','1870-1911','UR','None',7,8,
       'Monopoly: +4 to economic. Destroy 1 rival Org. Risk: Antitrust breakup.','Rockefeller oil monopoly, 90% of US refining.','Sherman Antitrust. 1911 breakup into 34 companies. Exxon, Chevron origins.',['rockefeller','oil','monopoly']),
    _hc('ORG038','Tammany Hall','Organization','domestic','1789-1960s','R','Tammany Hall',5,6,
       'Political Machine: +3 to domestic. +$2/turn. Risk: Scandal cards double.','New York Democratic political machine, patronage and corruption.','Boss Tweed era. Irish immigrant base. FDR broke it. Last boss: Carmine DeSapio.',['tammany','corruption','new_york']),
    _hc('ORG039','Vatican','Organization','foreign','1929-present','UR','Vatican',6,9,
       'Holy See: +3 to social. +2 to diplomatic. Negate 1 Scandal. Risk: Reformation.','Sovereign city-state, headquarters of Catholic Church.','1.4B followers. Bank scandals. Diplomatic relations with 183 countries.',['vatican','catholic','diplomacy'],'Vatican'),
    _hc('ORG040','United Fruit Company','Organization','economic','1899-1970','UR','None',6,7,
       'Banana Republic: +3 to economic. Remove 1 Central American Figure. Risk: Coup scandal.','US fruit corporation, dominated Central American politics.','1954 Guatemala coup. "Banana republic" term coined. Became Chiquita.',['united_fruit','banana','coup'],'Central America'),
    # ── Batch 3 Organizations ──
    _hc('ORG041','De Beers','Organization','economic','1888-present','UR','None',6,8,
       'Diamond Monopoly: +4 to economic. Control 1 mineral card. Reveal 1 face-down.','South African diamond mining cartel, controlled 80%+ of global supply.','Cecil Rhodes. Oppenheimer family. "A diamond is forever" campaign. Blood diamonds.',['de_beers','diamonds','monopoly'],'South Africa'),
    _hc('ORG042','Hudson Bay Company','Organization','economic','1670-present','UR','British Crown',6,7,
       'Fur Trade: +3 to economic. +2 to territorial cards. Peek 1 face-down.','Oldest corporation in North America, fur trade empire.','Ruperts Land. 15% of Canada. Still operates retail. Controlled vast territory.',['hudson_bay','fur_trade','colonial'],'Canada'),
    _hc('ORG043','Knights Templar','Organization','military','1119-1312','UR','None',6,8,
       'Holy Warriors: +3 to military. +2 to economic. Reveal 2 face-down. Risk: Friday 13th purge.','Catholic military order, Crusades, early banking.','Temple of Solomon. Friday October 13, 1307 arrested. Burned. Treasure legends.',['templar','crusades','banking'],'Israel'),
    _hc('ORG044','Google','Organization','intelligence','1998-present','UR','None',7,9,
       'Search Engine: +3 to intelligence. Peek 2 face-down/turn. +2 to economic. Risk: Antitrust.','Tech giant, search, data, advertising monopoly.','90% of search. Gmail, YouTube, Android. Project Maven. Pentagon AI.',['google','tech','surveillance']),
    _hc('ORG045','Microsoft','Organization','economic','1975-present','UR','None',6,8,
       'Desktop Monopoly: +3 to economic. +2 to intelligence. Negate 1 antitrust card. Risk: Antitrust.','Software giant, Windows, Office, Azure, LinkedIn.','90% desktop OS. Gates. Antitrust 1990s. Cloud wars. OpenAI investor.',['microsoft','tech','monopoly']),
    # ── Batch 4 Organizations ──
    _hc('ORG046','Amazon','Organization','economic','1994-present','UR','None',7,8,
       'Everything Store: +3 to economic. +2 to intelligence. Destroy 1 retail card. Risk: Antitrust.','E-commerce, cloud (AWS), logistics empire.','Bezos. 40% e-commerce. AWS runs internet. CIA $600M contract. Ring surveillance.',['amazon','tech','aws']),
    _hc('ORG047','Apple','Organization','economic','1976-present','UR','None',6,8,
       'Walled Garden: +3 to economic. +2 to intelligence. Negate 1 rival tech card.','Consumer tech giant, iPhone, App Store, services.','First $3T company. Jobs. Cook. 30% App Store tax. China dependency. Foxconn.',['apple','tech','iphone']),
    _hc('ORG048','OpenAI','Organization','intelligence','2015-present','UR','None',5,9,
       'AGI: +4 to intelligence. Peek 1 face-down/turn. Risk: Alignment, safety scandal.','AI research lab, ChatGPT, GPT models.','Altman, Musk co-founder. Microsoft invested $13B. Nonprofit to for-profit transition. Board drama.',['openai','ai','chatgpt']),
    _hc('ORG049','Saudi Aramco','Organization','economic','1933-present','UR','None',8,9,
       'Oil Giant: +4 to economic. Oil cards +3. Control 1 Middle East card. Risk: Climate policy.','Saudi state oil company, largest oil producer, $2T+ valuation.','Ghawar field. Aramco IPO 2019. OPEC swing producer. Saudi wealth fund.',['aramco','oil','saudi'],'Saudi Arabia'),
    _hc('ORG050','Vanguard Group','Organization','economic','1975-present','UR','None',6,8,
       'Index Giant: +3 to economic. +2 to intelligence. Peek 1 face-down. Risk: Passive bubble.','World second-largest asset manager, $8T+ AUM, index funds pioneer.','Jack Bogle. Lowest fees. Owned by shareholders. 401K backbone.',['vanguard','index_funds','finance']),
    # ── Batch 5 Organizations: Geopolitical Alliances ──
    _hc('ORG051','Warsaw Pact','Organization','military','1955-1991','UR','KGB',7,6,
       'Soviet Bloc: +3 to military. +2 to communist cards. Negate 1 NATO card. Risk: 1956, 1968 uprisings.','Soviet-led military alliance of Eastern European communist states.','8 members. Invaded Hungary 1956, Czechoslovakia 1968. Dissolved with USSR.',['warsaw_pact','soviet','cold_war'],'USSR'),
    _hc('ORG052','African Union','Organization','foreign','2002-present','R','None',4,6,
       'Pan-African: +2 to social. +2 to diplomatic. Negate 1 colonial card. Risk: Coup culture.','Continental union of 55 African states, replaced OAU.','AU Peace and Security Council. AGOA. African Standby Force. Underfunded.',['african_union','africa','pan_african'],'Ethiopia'),
    _hc('ORG053','Meta Platforms','Organization','intelligence','2004-present','UR','None',7,9,
       'Social Graph: +3 to intelligence. Peek 2 face-down/turn. +2 to media. Risk: Antitrust, privacy.','Facebook, Instagram, WhatsApp. 3B+ users. Data empire.','Cambridge Analytica. Section 230. Oculus, metaverse. Political ad targeting.',['meta','facebook','surveillance']),
    _hc('ORG054','BIS (Bank for Intl Settlements)','Organization','economic','1930-present','UR','None',5,9,
       'Central Bank of Central Banks: +3 to economic. Peek 1 face-down. Negate 1 bank Scandal.','Bank for International Settlements, coordinates global monetary policy.','Basel, Switzerland. Basel III accords. $200B+ in gold. Nazi gold controversy WWII.',['bis','central_bank','basel'],'Switzerland'),
    _hc('ORG055','BRICS','Organization','foreign','2009-present','R','None',5,7,
       'Multipolar: +2 to economic. +2 to diplomatic. Negate 1 Western sanction card.','Bloc of Brazil, Russia, India, China, South Africa (+Iran, UAE, Egypt, Ethiopia 2024).','40% world population. 30% GDP. New Development Bank. Counterweight to G7.',['brics','multipolar','emerging_markets'],'Global'),
    # ── Batch 6 Organizations: Military-Industrial & Tech ──
    _hc('ORG056','Lockheed Martin','Organization','military','1995-present','UR','Pentagon',7,8,
       'Defense Giant: +4 to military. +2 to intelligence. Risk: Cost overruns, F-35.','Largest defense contractor, F-35, F-22, satellites.','$65B revenue. F-35 $1.7T program. Skunk Works. Classified programs.',['lockheed','defense','military_industrial']),
    _hc('ORG057','Raytheon','Organization','military','1922-present','UR','Pentagon',6,7,
       'Missiles: +3 to military. +2 to intelligence. Destroy 1 economic card. Risk: Saudi deals.','Defense contractor, missiles, Patriot, Tomahawk.','Patriot missiles. Tomahawk cruise missiles. Saudi arms deals controversial. Merged with UTC 2020.',['raytheon','missiles','defense']),
    _hc('ORG058','Tesla','Organization','economic','2003-present','UR','None',6,7,
       'EV Revolution: +3 to economic. +2 to military. Negate 1 oil card. Risk: Musk volatility.','Electric vehicle and battery company, SpaceX sister.','Musk. Gigafactories. Autopilot crashes. Pentagon contracts. Cybertruck.',['tesla','ev','musk']),
    _hc('ORG059','State Street','Organization','economic','1978-present','R','None',5,7,
       'Custodian: +2 to economic. +2 to intelligence. Peek 1 face-down. Risk: Passive concentration.','Third-largest US asset manager, $4T+ AUM, custody services.','SPDR ETFs. Index pioneer. Shareholder voting power. Concentration risk.',['state_street','asset_manager','finance']),
    _hc('ORG060','Shanghai Cooperation Organisation','Organization','foreign','2001-present','R','None',4,6,
       'Eurasian Bloc: +2 to military. +2 to diplomatic. Negate 1 NATO card. Risk: China-dominated.','SCO security and economic bloc: China, Russia, India, Pakistan, Central Asia.','Counterterrorism exercises. Iran, Belarus joined. Energy cooperation. Chinese influence tool.',['sco','eurasian','china'],'China'),
    # ── Batch 7 Organizations: Shadowy Groups ──
    _hc('ORG061','Knights of Malta','Organization','intelligence','1048-present','R','None',4,7,
       'Sovereign Order: +2 to diplomatic. +2 to intelligence. Peek 1 face-down. Risk: Elite networking.','Sovereign Military Order of Malta, Catholic chivalric order with diplomatic status.','13K+ knights. Passports. CIA connections. Russia, Cuba back-channel. Bill Casey member.',['malta','catholic','elite'],'Vatican'),
    _hc('ORG062','Palantir Foundry','Organization','intelligence','2008-present','R','None',5,7,
       'Data Integration: +2 to intelligence. +2 to economic. Peek 2 face-down. Risk: Privacy scandal.','Palantirs commercial data integration platform, used by corporations and governments.','Foundry. Gotham. Apollo. Predictive analytics. COVID tracking. NHS partnership.',['palantir','data','surveillance']),
    _hc('ORG063','Open Society Foundations','Organization','social','1993-present','UR','None',5,8,
       'Open Society: +3 to social. +2 to diplomatic. Negate 1 authoritarian card. Risk: Soros conspiracy target.','George Soros-funded global network promoting democracy, human rights.','$32B+ donated. 120+ countries. Color revolutions. Conspiracy target. Fidesz, Orban clashes.',['soros','ngos','democracy']),
    _hc('ORG064','Bohemian Club','Organization','economic','1872-present','R','None',3,7,
       'Cremation of Care: +2 to economic. +2 influence to Figure. Peek 1 face-down. Risk: Secrecy.','Exclusive all-male elite summer camp at Bohemian Grove, California.','Nixon, Reagan, Bush, Kissinger attended. Owl shrine. Mock sacrifice. Lakeside chats.',['bohemian','elite','secret_society']),
    _hc('ORG065','Palantir Gotham','Organization','intelligence','2008-present','UR','None',6,8,
       'All-Seeing Eye: +3 to intelligence. Peek 3 face-down/turn. Risk: Privacy scandal.','Palantirs government platform, used by CIA, military, ICE, police.','Gotham counter-terrorism. Foundry data integration. Predictive policing. Thiel.',['palantir','surveillance','data']),
    # ── Batch 8 Organizations: Intelligence & Strategic ──
    _hc('ORG066','Office of Special Plans','Organization','intelligence','2002-2003','R','Pentagon',5,6,
       'Stovepipe: +2 to intelligence. Create 1 fake intelligence card. Risk: WMD failure.','Pentagon unit created by Wolfowitz/Feith to stovepipe Iraq intelligence bypassing CIA.','Cherry-picked raw intel. Curveball. No WMD found. Disbanded after Iraq invasion.',['osp','iraq','wmd']),
    _hc('ORG067','NED','Organization','foreign','1983-present','R','None',4,7,
       'Democracy Promotion: +3 to revolutionary. +2 to diplomatic. Negate 1 authoritarian. Risk: Regime change tool.','National Endowment for Democracy, funds pro-democracy groups worldwide.','Created by Reagan. Color revolutions. Russia banned it. China sanctioned. $300M/year.',['ned','democracy','color_revolution']),
    _hc('ORG068','Academi','Organization','military','2010-present','UR','Pentagon',5,5,
       'Rebranded PMC: +2 to military. Destroy 1 social card. Risk: Legacy of Blackwater scandals.','Blackwater rebranded as Xe Services then Academi, continued defense contracts.','Erik Prince sold. Training center. JSOC contracts. Nisour Square legacy. Merged with Triple Canopy 2014.',['academi','mercenary','iraq']),
    # ── Batch 9 Organizations: Think Tanks & Finance ──
    _hc('ORG069','PNAC','Organization','foreign','1997-2006','R','None',3,8,
       'New American Century: +2 to military. +2 to foreign Policy. Negate 1 diplomatic. Risk: Iraq War disaster.','Project for New American Century, neocon think tank advocating US global hegemony.','Kagan, Kristol, Schmitt founded. 259 signatories. Rumsfeld, Cheney, Wolfowitz, Bolton. Rebuilding Americas Defenses.',['neocon','pnc','hegemony']),
    _hc('ORG070','RAND Corporation','Organization','intelligence','1948-present','UR','Pentagon',5,7,
       'Strategy Factory: +2 to military. +2 to intelligence. Peek 1 face-down. Risk: Cold War mentality.','Nonprofit global policy think tank, originally Air Force research.','Wohlstetter. Game theory. Nuclear strategy. Delphi method. Internet origins. $300M+ revenue.',['rand','strategy','nuclear']),
    _hc('ORG071','BIS','Organization','economic','1930-present','UR','BIS',6,8,
       'Central Bank of Central Banks: +3 to economic. Negate 1 financial Scandal. Peek 2 face-down.','Bank for International Settlements, coordinates global central bank policy.','Basel, Switzerland. Nazi gold scandal. Basel Accords. Too opaque. No democratic accountability.',['bis','central_banking','basel'],'Switzerland'),
    # ── Batch 10 Organizations: Media & Intelligence ──
    _hc('ORG072','AEI','Organization','foreign','1943-present','R','None',3,8,
       'Neocon Incubator: +2 to foreign Policy. +2 to military. Peek 1 face-down. Risk: Echo chamber.','American Enterprise Institute, neoconservative think tank, incubator for Bush era hawks.','Perle, Wolfowitz, Bolton, Kristol fellows. Iraq War intellectual home. Irving Kristol. Funded by corporate donors.',['aei','neocon','think_tank']),
    _hc('ORG073','JSOC','Organization','military','2003-present','UR','Pentagon',7,6,
       'Tier One: +3 to military. Remove 1 Figure. Peek 2 face-down. Risk: Unaccountable killings.','Joint Special Operations Command, secret military assassination and raid unit.','Delta Force, SEAL Team 6. Night raids. Kill/capture. McRaven. Iraq, Afghanistan, Syria, Africa.',['jsoc','special_ops','assassination']),
    _hc('ORG074','In-Q-Tel','Organization','intelligence','1999-present','R','CIA',4,7,
       'Venture Intel: +2 to intelligence. +2 to economic. Peek 1 face-down. Risk: Tech monopoly capture.','CIA venture capital arm investing in startups with intelligence applications.','Keyhole (Google Earth). Palantir early investor. Facebook. AI surveillance. Silicon Valley-CIA pipeline.',['cia','venture_capital','silicon_valley']),
    # ── Batch 11 Organizations: Media & Finance ──
    _hc('ORG075','Fox News','Organization','social','1996-present','UR','Media',5,9,
       'Conservative Megaphone: +3 to media. +2 to social. Negate 1 Scandal. Risk: Dominion lawsuit, polarization.','Conservative cable news network, most-watched in US, created by Roger Ailes for Rupert Murdoch.','Primetime hosts. Talking points. GOP messaging arm. $787M Dominion settlement. Tucker fired. Ailes era.',['fox','media','conservative']),
    _hc('ORG076','Citadel Securities','Organization','economic','2002-present','UR','None',5,7,
       'Order Flow Master: +3 to economic. Peek 2 face-down. Negate 1 market Scandal. Risk: Conflict of interest, retail capture.','Worlds largest market maker, processes 40% of US retail stock trades, Ken Griffin firm.','Payment for order flow. Robinhood revenue source. Melvin Capital bailout. Surveyed Treasury market. Chicago.',['citadel','market_maker','finance']),
    _hc('ORG077','SCL Group','Organization','intelligence','1990-2018','UR','None',5,8,
       'Psyops Parent: +3 to intelligence. +2 to media. Peek 3 face-down. Risk: Cambridge Analytica exposure.','British behavioral research and strategic communications firm, parent of Cambridge Analytica.','Military psyops. MOD contracts. Elections worldwide. Nigeria, Kenya, Czech Republic. Mercer funded. Bannon. Nix. Dissolved 2018.',['scl_group','psyops','data']),
    # ── Batch 12 Organizations: Energy, Lobbying & Cyber ──
    _hc('ORG078','ExxonMobil','Organization','economic','1999-present','UR','None',7,8,
       'Oil Supermajor: +4 to economic. Oil cards +3. Negate 1 climate Policy. Risk: Climate lawsuits, stranded assets.','Largest US oil company, formed by Exxon-Mobil merger, climate denial funder.','Lee Raymond, Rex Tillerson. $400B+ revenue. Iraq, Chad, Nigeria operations. Climate suppression. ExxonKnew lawsuits.',['exxon','oil','climate_denial']),
    _hc('ORG079','Koch Industries','Organization','economic','1940-present','UR','None',6,8,
       'Dark Money Empire: +3 to economic. +2 to political. Negate 1 climate Policy. Risk: Populist backlash.','Charles Koch conglomerate, oil refining, chemical, largest privately held US company.','Americans for Prosperity. Donors Trust. $100M+ political network. Climate denial. Libertarian. Cato Institute. Tea Party funding.',['koch','oil','dark_money']),
    _hc('ORG080','NSO Group','Organization','intelligence','2010-present','UR','Mossad',5,8,
       'Digital Mercenary: +3 to intelligence. Peek 2 face-down permanently. Risk: Blacklist, lawsuits.','Israeli cyber intelligence company, Pegasus spyware sold to governments worldwide.','Zero-click exploits. WhatsApp, iMessage vulnerabilities. Saudi, Mexico, India clients. Khashoggi associates targeted. US blacklisted 2021.',['nso','pegasus','surveillance']),
]

POLICIES = [
    _hc('POL001','Patriot Act','Policy','domestic','2001','UR','Congress',7,8,
       'Surveillance State: Intelligence +3 power. Social -2 influence.','Post-9/11 surveillance law.','Section 215 bulk collection.',['surveillance','911','nsa']),
    _hc('POL002','New Deal','Policy','economic','1933-1939','R','White House',6,7,
       'Relief: Restore 3 from discard. +1 influence to social.','FDR response to Depression.','Social Security, WPA, SEC.',['fdr','new_deal','social']),
    _hc('POL003','Civil Rights Act','Policy','social','1964','R','Congress',6,8,
       'Equality: Nullify racial Scandal cards. +3 influence to social.','Banned discrimination.','LBJ signed. MLK pressure. Filibuster broken.',['civil_rights','lbj','equality']),
    _hc('POL004','Monroe Doctrine','Policy','foreign','1823','U','White House',5,6,
       'Sphere of Influence: +3 to Western Hemisphere cards.','Europe stay out of Americas.','Roosevelt Corollary expanded it.',['monroe','latin_america','hegemony']),
    _hc('POL005','NATO Alliance','Policy','foreign','1949','R','NATO',6,7,
       'Collective Defense: +2 power to allied foreign cards.','North Atlantic Treaty Org.','Article 5 invoked once: after 9/11.',['nato','alliance','cold_war'],'Global'),
    _hc('POL006','War on Drugs','Policy','domestic','1971-present','R','White House',5,4,
       'Mass Incarceration: FBI +3 power. Social -2. Cartel +2.','Nixon declared drug war.','Racial disparity, cartel enrichment.',['nixon','drugs','incarceration']),
    _hc('POL007','Affordable Care Act','Policy','domestic','2010','R','White House',5,6,
       'Healthcare: +2 influence to social. Big Pharma +2 power.','Obamacare, insurance expansion.','Individual mandate. 20M+ insured.',['obama','healthcare','aca']),
    _hc('POL008','Tax Cuts and Jobs Act','Policy','economic','2017','U','Congress',4,5,
       'Trickle Down: +2 economic. Risk: -1 influence/turn after 3.','Trump tax cuts, corp 35% to 21%.','Added $1T+ to deficit.',['trump','tax','economy']),
    _hc('POL009','AUMF 2001','Policy','military','2001','UR','Congress',7,6,
       'Forever War: Military +2 power permanently.','Authorization for Use of Military Force.','Used for Afghanistan, Iraq, Syria, Yemen.',['911','war','military']),
    _hc('POL010','Executive Order 9066','Policy','domestic','1942','R','White House',6,3,
       'Internment: Remove all cards from one region. -3 influence.','FDR ordered Japanese-American internment.','120K imprisoned. Reagan apologized 1988.',['fdr','internment','racism']),
    _hc('POL011','Nuremberg Trials','Policy','foreign','1945-1946','R','None',6,7,
       'Accountability: Remove all war-crime cards. +3 influence.','Nazi leaders prosecuted.','Following orders defense rejected.',['nazi','wwii','justice'],'Germany'),
    _hc('POL012','Marshall Plan','Policy','foreign','1948','R','White House',6,7,
       'Rebuild: +3 influence to European cards.','US economic aid to rebuild Europe.','$13B. Counter Soviet influence.',['wwii','europe','cold_war'],'Europe'),
    _hc('POL013','Detente','Policy','foreign','1969-1979','U','White House',4,6,
       'Thaw: Both +2 influence. Nuclear -3 power for 2 turns.','Nixon-Kissinger easing tensions.','SALT I, Apollo-Soyuz.',['cold_war','nixon','diplomacy'],'Global'),
    _hc('POL014','NAFTA','Policy','economic','1994','U','Congress',4,5,
       'Free Trade: +2 economic. Risk: domestic -1 power.','North American Free Trade Agreement.','Clinton signed. Manufacturing debate.',['trade','clinton','economy']),
    _hc('POL015','Citizens United','Policy','economic','2010','R','Congress',5,7,
       'Money = Speech: +2 influence to Organization cards. -2 to social.','SC ruling allowed unlimited corporate political spending.','Super PACs created. Dark money.',['scotus','money','corruption']),
    _hc('POL016','Social Security Act','Policy','social','1935','R','White House',5,7,
       'Safety Net: +2 influence to social cards. Negate one economic crash.','FDR created Social Security retirement system.','Most popular US program. Payroll tax. Trust fund depletion debate.',['fdr','social_security','new_deal']),
    _hc('POL017','Medicare Act','Policy','social','1965','R','White House',5,7,
       'Healthcare for Elderly: +3 influence to social. Big Pharma +2 power.','LBJ signed Medicare and Medicaid.','Single-payer for 65+. Controversial then, essential now.',['lbj','medicare','health']),
    _hc('POL018','Alien & Sedition Acts','Policy','domestic','1798','U','White House',4,4,
       'Suppress Dissent: Negate one social card. Risk: -2 influence.','Adams admin restricted immigrant rights and free speech.','Virginia & Kentucky Resolutions. Expired. Early overreach.',['adams','censorship','immigration']),
    _hc('POL019','Homestead Act','Policy','domestic','1862','U','White House',4,5,
       'Free Land: +2 influence to domestic territorial cards. Native -3 power.','Gave 160 acres to settlers. Westward expansion.','Accelerated native displacement. 10% of US land given away.',['lincoln','westward','native']),
    _hc('POL020','Sherman Anti-Trust Act','Policy','economic','1890','U','Congress',4,5,
       'Break Monopoly: Destroy one Organization card. Economic +1 influence.','First federal anti-trust law.','Used vs Standard Oil, AT&T. Rarely enforced recently.',['antitrust','monopoly','congress']),
    _hc('POL021','G.I. Bill','Policy','social','1944','R','White House',5,6,
       'Veterans Benefits: +2 influence to social. Military +1 power.','WWII veterans education, housing, unemployment benefits.','Created middle class. Redlining excluded Black veterans.',['wwii','veterans','education']),
    _hc('POL022','FISA Court','Policy','intelligence','1978','R','Congress',5,6,
       'Secret Court: Intelligence +2 power. Risk: Rubber stamp, no oversight.','Foreign Intelligence Surveillance Act court.','99% approval rate. Secret rulings. Snowden exposed scope.',['fisa','surveillance','secret_court']),
    _hc('POL023','Dodd-Frank Act','Policy','economic','2010','R','Congress',4,5,
       'Wall Street Reform: Economic -2 power. Negate one crash Event.','Post-2008 financial regulation law.','Volcker Rule, CFPB. Rollbacks under Trump. Wall Street lobbying.',['dodd_frank','reform','wall_street']),
    _hc('POL024','Operation Warp Speed','Policy','domestic','2020','R','White House',6,7,
       'Vaccine Race: Negate COVID Event. Big Pharma +3 power.','Trump admin accelerated COVID vaccine development.','$18B. Pfizer, Moderna. mRNA technology. Distribution challenges.',['covid','vaccine','trump']),
    _hc('POL025','Border Wall','Policy','domestic','2017-2021','U','White House',3,4,
       'Build the Wall: +2 power to domestic. Social -1 influence. Risk: Wasted money.','Trump border wall with Mexico.','$15B+ spent. Mexico didn\'t pay. Eminent domain disputes.',['trump','border','immigration']),
    _hc('POL026','Roe v Wade Overturn','Policy','social','2022','UR','None',6,7,
       'Bodily Autonomy Lost: Social -3 influence. Religious +2 power. Both lose 2 cards.','Dobbs decision overturned Roe v Wade.','Leaked opinion. SCOTUS conservative majority. State-by-state chaos.',['roe','scotus','abortion']),
    # ── Global Policies ──
    _hc('POL027','Bretton Woods','Policy','economic','1944','UR','Federal Reserve',6,8,
       'Global Financial Order: +3 to economic. USD becomes reserve currency.','Established IMF, World Bank, dollar-gold standard.','Nixon ended convertibility 1971. Petrodollar replaced.',['imf','world_bank','fed']),
    _hc('POL028','NATO Formation','Policy','foreign','1949','UR','Pentagon',6,7,
       'Collective Defense: +3 power to military. Soviet -2 influence.','North Atlantic Treaty Organization.','Article 5 mutual defense. Cold War alliance. Expansion debate.',['nato','cold_war','military']),
    _hc('POL029','Schengen Agreement','Policy','foreign','1985','R','EU',4,6,
       'Open Borders: +2 influence to European. Risk: Migration Scandal cards double.','European free movement zone.','26 countries. No passport checks. Migration crisis strain.',['eu','european','migration']),
    _hc('POL030','China WTO Entry','Policy','economic','2001','UR','None',5,7,
       'Trade Integration: +3 to economic. Risk: China +3 power.','China joined WTO, manufacturing boom.','Factory of the world. US deindustrialization. Trade deficits.',['china','economy','trade']),
    _hc('POL031','Quantitative Easing','Policy','economic','2008-2022','UR','Federal Reserve',5,7,
       'Money Printer Go Brrr: +3 to economic. Risk: Inflation cards triple.','Fed bought trillions in bonds after 2008 and COVID.','Asset bubbles. Wealth inequality. Cantillon effect.',['fed','qe','inflation']),
    _hc('POL032','EU Sanctions on Russia','Policy','foreign','2022','R','EU',5,5,
       'Economic Warfare: Russian -3 power. Risk: Energy -2 influence.','EU sanctions after Ukraine invasion.','Oil price cap, SWIFT ban. Energy crisis. Ruble recovery.',['russia','sanctions','eu']),
    _hc('POL033','Belt and Road Initiative','Policy','foreign','2013-present','UR',' CCP',6,7,
       'Debt Trap Diplomacy: +2 to economic. +3 influence to Chinese cards.','China global infrastructure investment strategy.','$1T+ in 150+ countries. Sri Lanka port default. Debt concerns.',['china','economic','debt']),
    _hc('POL034','Reconstruction Acts','Policy','domestic','1867-1877','R','Congress',5,5,
       'Post-Civil War: +3 to social. Military +1. Risk: Backlash from South.','Radical Republican reconstruction of the South.','Freedmen Bureau. 13th-15th Amendments. Ended by Compromise of 1877.',['reconstruction','civil_war','freedmen']),
    _hc('POL035','Glass-Steagall Repeal','Policy','economic','1999','UR','Wall Street',5,6,
       'Bank Deregulation: +3 to economic. Risk: Crash Event cards triple.','Repealed separation of commercial/investment banking.','Led to 2008 crash. Too big to fail. Citigroup merger enabled.',['wall_street','deregulation','crash']),
    _hc('POL036','Apartheid Laws','Policy','foreign','1948-1994','R','None',5,3,
       'Racial Segregation: +2 power to domestic. Social -4 influence. Risk: Mandela.','South African apartheid system.','Pass laws, homelands, Soweto uprising. Divested 1980s.',['apartheid','racism','segregation'],'South Africa'),
    # ── New Policies ──
    _hc('POL037','Interstate Highway Act','Policy','economic','1956','R','White House',5,6,
       'Infrastructure: +3 to economic. Military +1. Connect all domestic cards.','Eisenhower interstate highway system, 47K miles.','$500B in today dollars. Suburbs. Defense logistics.',['eisenhower','highway','infrastructure']),
    _hc('POL038','Voting Rights Act','Policy','social','1965','UR','Congress',6,8,
       'Ballot Access: +4 to social. Destroy all segregation cards. +2 influence.','LBJ signed, banned racial voting discrimination.','Selma, MLK, Bloody Sunday. Section 5 gutted by SCOTUS 2013.',['lbj','voting','civil_rights']),
    _hc('POL039','CHIPS and Science Act','Policy','economic','2022','R','Congress',4,6,
       'Reshore Chips: +3 to economic. Military +1. Negate Taiwan invasion.','Subsidies for domestic semiconductor manufacturing.','TSMC, Intel, Samsung fabs. China competition.',['chips','semiconductor','biden']),
    _hc('POL040','Kansas-Nebraska Act','Policy','domestic','1854','U','Congress',3,3,
       'Popular Sovereignty: +1 to domestic. Risk: Bleeding Kansas, Civil War cards triple.','Allowed territories to vote on slavery, overturned Missouri Compromise.','Douglas sponsored. Lincoln-Douglas debates. Led to Civil War.',['kansas','slavery','civil_war']),
    _hc('POL041','Treaty of Versailles','Policy','foreign','1919','UR','None',5,4,
       'Punitive Peace: German -5 influence. Military -2. Risk: WWII Event cards triple.','Ended WWI, imposed harsh reparations on Germany.','War guilt clause. Keynes warned. Led to WWII.',['wwi','versailles','reparations'],'France'),
    # ── Batch 2 Policies ──
    _hc('POL042','GI Bill','Policy','social','1944','R','Congress',5,7,
       'Veterans Education: +3 to social. Military +2. Economic +2.','Servicemens Readjustment Act, educated WWII veterans.','College for millions. Suburbs. Black veterans denied benefits.',['gi_bill','veterans','wwii']),
    _hc('POL043','19th Amendment','Policy','social','1920','UR','Congress',6,8,
       'Womens Suffrage: +4 to social. +2 influence to all female Figures.','Granted women the right to vote.','72-year struggle. Seneca Falls 1848. Tennessee ratified by 1 vote.',['suffrage','womens_rights','amendment']),
    _hc('POL044','Chinese Exclusion Act','Policy','domestic','1882-1943','R','Congress',4,3,
       'Ban Immigrants: -2 to social. Immigrant -3. Risk: Backlash, repeal.','First federal law restricting immigration by nationality.','10-year ban, then extended. Repealed 1943 during WWII.',['chinese','immigration','racism']),
    _hc('POL045','Indian Removal Act','Policy','domestic','1830','R','White House',5,2,
       'Forced Relocation: Destroy all native-tagged cards. Domestic +2. Risk: Trail of Tears.','Jackson signed, forced native tribes west of Mississippi.','Cherokee, Creek, Chickasaw, Choctaw, Seminole. Trail of Tears.',['jackson','native','trail_of_tears']),
    _hc('POL046','Dawes Act','Policy','domestic','1887-1934','U','Congress',3,3,
       'Allotment: Destroy 2 native-tagged cards. Economic +2. Risk: Land loss, cultural destruction.','Broke up tribal lands into individual allotments.','90M acres lost. Boarding schools. Assimilation policy.',['dawes','native','assimilation']),
    # ── Batch 3 Policies ──
    _hc('POL047','Missouri Compromise','Policy','domestic','1820','U','Congress',4,5,
       'Balance: +2 to domestic. Negate 1 slavery Event. Risk: Kansas-Nebraska overturns.','Admitted Missouri as slave, Maine as free, banned slavery north of 3630.','Clay brokered. 36 years of balance. Overturned 1854.',['missouri','slavery','compromise']),
    _hc('POL048','Compromise of 1850','Policy','domestic','1850','U','Congress',4,4,
       'Delayed War: +1 to domestic. Fugitive Slave Act +2. Risk: Civil War accelerated.','Clay compromise: California free, Utah/NM popular sovereignty, Fugitive Slave Act.','Webster 7th March speech. Fillmore signed. Failed within 11 years.',['compromise','slavery','fugitive_slave']),
    _hc('POL049','Pendleton Act','Policy','domestic','1883','R','Congress',4,6,
       'Civil Service Reform: +2 to economic. Negate 1 Spoils card. Scandal -2.','Established merit-based civil service after Garfield assassination.','Assassinated by disgruntled office seeker. Exams replaced patronage.',['pendleton','civil_service','reform']),
    _hc('POL050','Wagner Act','Policy','social','1935','UR','Congress',5,7,
       'Labor Rights: +3 to social. Labor cards +2 power. +1 to economic.','National Labor Relations Act, protected union organizing rights.','FDR signed. Strikes surged. Taft-Hartley rolled it back 1947.',['labor','wagner','nlra']),
    _hc('POL051','Taft-Hartley Act','Policy','domestic','1947','R','Congress',4,5,
       'Anti-Labor: Labor -3 power. +2 to economic. Risk: Union decline.','Restricted union power, banned closed shops, allowed right-to-work.','Truman vetoed, overridden. 28 states passed RTW. Union decline began.',['taft_hartley','labor','right_to_work']),
    # ── Batch 4 Policies ──
    _hc('POL052','Espionage Act','Policy','domestic','1917','UR','Congress',6,5,
       'Silence Dissent: Intelligence +2. Negate 1 social card. Risk: Whistleblowers.','WWI law criminalizing dissent, still used against whistleblowers.','Schenck, Ellsberg, Snowden, Assange charged under it. 100+ years.',['espionage','wwi','censorship']),
    _hc('POL053','Glass-Steagall Act','Policy','economic','1933-1999','R','Congress',5,7,
       'Firewall: +3 to economic. Negate 1 bank Scandal. Risk: Repeal = 2008 crash.','Separated commercial and investment banking after Great Depression.','FDR signed. Repealed 1999 by Gramm-Leach-Bliley. Led to 2008 crash.',['glass_steagall','banking','depression']),
    _hc('POL054','Sarbanes-Oxley Act','Policy','economic','2002','R','Congress',4,6,
       'Corporate Accountability: +2 to economic. Negate 1 fraud Scandal. Reveal 1.','Post-Enron corporate governance reform.','CEO/CFO certification. PCAOB. Section 404. Costs controversial.',['sox','enron','corporate_governance']),
    _hc('POL055','Helsinki Accords','Policy','foreign','1975','R','None',4,7,
       'Human Rights Basket: +3 to social. +2 to diplomatic. Soviet -2. Risk: Hollow promises.','35-nation agreement on European security and human rights.','Basket III human rights monitored. Dissidents cited it. Led to Helsinki Watch.',['helsinki','cold_war','human_rights'],'Finland'),
    _hc('POL056','McCarran Act','Policy','domestic','1950','R','Congress',4,4,
       'Internment Ready: +2 to intelligence. Negate 1 communist card. Risk: Concentration camps.','Internal Security Act required communist registration, authorized detention camps.','Truman vetoed, overridden. Eisenhower used it. Mostly voided by courts.',['mccarran','cold_war','internment']),
    # ── Batch 5 Policies: Advanced Political Strategy ──
    _hc('POL057','INF Treaty','Policy','foreign','1987','R','None',5,7,
       'Missile Ban: Nuclear cards -4 power. Both +2 influence. Risk: US withdrawal 2019.','Reagan-Gorbachev treaty eliminated intermediate-range nuclear missiles.','First treaty to actually destroy weapons. 2692 missiles eliminated. Trump withdrew 2019.',['inf','cold_war','arms_control'],'USSR'),
    _hc('POL058','START Treaty','Policy','foreign','2010','R','None',4,7,
       'New START: Nuclear cards -3 power. Both +3 influence. Risk: Expires 2026.','US-Russia treaty reduced strategic nuclear warheads by 30%.','1550 deployed warheads each. Inspections. New START. Last remaining arms control treaty.',['start','nuclear','arms_control'],'USSR'),
    _hc('POL059','Kyoto Protocol','Policy','foreign','1997','R','None',3,6,
       'Emissions Cap: +2 to social. Oil cards -2. Risk: US never ratified.','International treaty to reduce greenhouse gas emissions.','37 industrialized countries. US signed but never ratified. Canada withdrew 2012.',['kyoto','climate','emissions'],'Japan'),
    _hc('POL060','Korean War Armistice','Policy','foreign','1953','U','Pentagon',3,5,
       'Frozen Conflict: Both lose 1 card. Stalemate. Negate 1 military Event.','Armistice ended Korean War fighting, no peace treaty, still technically at war.','38th parallel. DMZ. 70+ years no peace treaty. Trump-Kim summit 2018 failed.',['korea','armistice','cold_war'],'Korea'),
    _hc('POL061','Treaty of Tordesillas Policy','Policy','foreign','1494','U','Vatican',3,5,
       'Papal Division: +2 to diplomatic. Control 1 colonial card. Risk: Overlap conflicts.','Papal treaty divided New World between Spain and Portugal.','Pope Alexander VI. Line of demarcation. Portugal got Brazil. Colonial framework.',['tordesillas','colonial','vatican'],'Vatican'),
    # ── Batch 6 Policies: Advanced Political Strategy ──
    _hc('POL062','Nuclear Non-Proliferation Executive Order','Policy','foreign','2015','R','White House',4,7,
       'JCPOA: Nuclear cards -4. Iran +2 diplomatic. Risk: Trump withdraws, Iran resumes.','Iran nuclear deal (JCPOA) lifted sanctions in exchange for nuclear limits.','5+1 powers. $100B+ unfrozen. IAEA inspections. Trump withdrew 2018. Iran enriched.',['jcpoa','iran','nuclear'],'Iran'),
    _hc('POL063','Gramm-Leach-Bliley Act','Policy','economic','1999','R','Congress',3,6,
       'Bank Merger: +4 to economic. Negate Glass-Steagall. Risk: 2008 crash.','Repealed Glass-Steagall, allowed commercial-investment bank mergers.','Citigroup created. $10T mergers. Led directly to 2008. Too big to fail.',['gramm_leach_bliley','banking','deregulation']),
    _hc('POL064','War Powers Resolution','Policy','domestic','1973','R','Congress',4,5,
       'Check on War: President must withdraw in 60 days. Negate 1 undeclared war.','Limited presidential war-making without declaration after Vietnam.','Nixon vetoed, overridden. Mostly ignored. Libya, Syria, Yemen undeclared.',['war_powers','congress','vietnam']),
    _hc('POL065','Maastricht Treaty','Policy','foreign','1992','R','None',5,8,
       'European Union: +3 to diplomatic. +2 to economic. Negate 1 nationalist card. Risk: Brexit.','Created EU, euro currency, common foreign policy.','12 members. Euro 1999. Schengen. ECB. Sovereignty debates. Brexit 2020.',['eu','maastricht','euro'],'Netherlands'),
    _hc('POL066','Project for a New American Century','Policy','foreign','1997-2006','R','Pentagon',5,6,
       'Neocon Blueprint: +4 to military. +2 to intelligence. Risk: Iraq, quagmire.','Think tank advocating US global hegemony, regime change in Iraq.','Kagan, Kristol, Cheney, Rumsfeld, Wolfowitz signed letters. 9/11 enabled agenda. Iraq.',['neocon','iraq','hegemony']),
    # ── Batch 7 Policies: Controversial Laws & Executive Orders ──
    _hc('POL067','COINTELPRO Directive','Policy','intelligence','1956-1971','UR','FBI',6,7,
       'Counter-Intelligence: Destroy 2 revolutionary cards. FBI +3. Reveal 2. Risk: Church Committee.','FBI program to disrupt, discredit domestic political groups.','MLK, Black Panthers, anti-war, SDS. Blackmail letters. Infiltration. Exposed 1971.',['cointelpro','fbi','surveillance']),
    _hc('POL068','Alien and Sedition Acts','Policy','domestic','1798','R','Congress',4,4,
       'Dissent Crushed: Social -3. Destroy 1 media card. Negate 1 foreign Figure.','Adams administration laws criminalizing criticism of government, deported non-citizens.','Jefferson and Madison opposed. Kentucky/Virginia Resolutions. Expired. Free speech test.',['alien_sedition','adams','free_speech']),
    _hc('POL069','FISA Court Establishment','Policy','intelligence','1978','R','Congress',4,7,
       'Secret Court: Intelligence +2. Peek 2 face-down. Negate 1 warrantless wiretap Scandal.','Foreign Intelligence Surveillance Act created secret court for national security warrants.','11 judges. Rubber stamp allegations. 99% approval. Section 702 mass surveillance. Snowden exposed.',['fisa','surveillance','secret_court']),
    _hc('POL070','National Security Directive 77','Policy','foreign','1983','R','White House',4,6,
       'Public Diplomacy: +3 to media. +2 to diplomatic. Risk: Propaganda, Iran-Contra.','Reagan NSDD 77 created inter-agency group for public diplomacy, used to sell Contra policy.','Walter Raymond Jr. from CIA. Domestic propaganda. Office of Public Diplomacy. Iran-Contra linked.',['nsdd77','reagan','propaganda']),
    _hc('POL071','NDAA Indefinite Detention','Policy','domestic','2012','R','Congress',4,5,
       'Indefinite Hold: Remove 1 Figure. Negate 1 habeas corpus. Risk: ACLU lawsuit.','NDAA 2012 Section 1021 allows indefinite military detention without trial.','Obama signed with signing statement. Hedges v Obama challenged. SCOTUS declined. Gitmo parallel.',['ndaa','detention','civil_liberties']),
    # ── Batch 8 Policies: Intelligence & Foreign Policy ──
    _hc('POL072','Stellar Wind','Policy','intelligence','2001-2007','UR','NSA',6,7,
       'Warrantless Wiretap: Intelligence +3. Peek 3 face-down. Risk: Comey confrontation, Snowden.','Bush NSA program for warrantless wiretapping of Americans post-9/11.','Cheney pushed. Ashcroft hospital showdown. Comey threatened resignation. Continued under FISA Amendments.',['stellar_wind','nsa','warrantless']),
    _hc('POL073','AUMF 2002','Policy','military','2002','UR','Congress',6,5,
       'Iraq Authorization: +4 to military. Negate 1 diplomatic card. Risk: No WMD, quagmire.','Authorization for Use of Military Force Against Iraq, passed Congress October 2002.','77-23 Senate. Hillary, Kerry, Biden voted yes. Based on WMD claims. Still in force. Repeal attempts failed.',['aumf','iraq','war']),
    _hc('POL074','Section 702 Reauthorization','Policy','intelligence','2008-2024','R','Congress',4,7,
       'Mass Surveillance: Intelligence +2. Peek 2 face-down/turn. Risk: Privacy violation, FBI abuses.','FISA Amendments Act Section 702 allows warrantless surveillance of foreigners, sweeps Americans.','PRISM. Upstream. FBI backdoor searches. 702 reauthorized 2024. Privacy advocates failed to reform.',['section_702','fisa','surveillance']),
    # ── Batch 9 Policies: Financial & Foreign Policy ──
    _hc('POL075','Commodity Futures Modernization Act','Policy','economic','2000','UR','Congress',5,7,
       'Dark Markets: +3 to economic. Peek 2 face-down. Risk: 2008 crash, Enron loophole.','CFMA exempted derivatives from regulation, enabled Enron and 2008 financial crisis.','Phil Gramm. Wendy Gramm on Enron board. $370T derivatives market. AIG, Lehman. No exchange trading. Dark pools.',['cfma','deregulation','derivatives']),
    _hc('POL076','Countering Americas Adversaries Act','Policy','foreign','2017','UR','Congress',5,6,
       'Sanctions Weapon: +3 to military. Destroy 2 economic cards. Risk: Dedollarization, BRICS.','CAATSA sanctions on Russia, Iran, North Korea, expanded secondary sanctions on EU firms.','Mandatory sanctions. Nord Stream 2 threatened. Turkey S-400 sanctions. Russia dedollarization push.',['caatsa','sanctions','russia']),
    _hc('POL077','Executive Order 12333','Policy','intelligence','1981','R','White House',4,6,
       'CIA Charter Expansion: +2 to intelligence. CIA can operate domestically. Risk: Church Committee reversal.','Reagan EO expanded CIA powers, loosened restrictions on domestic intelligence gathering.','Rescinded Ford/Carter restrictions. CIA-FBI coordination. Assassination ban (2.11) widely debated.',['eo12333','cia','intelligence']),
    # ── Batch 10 Policies: Intelligence & Media ──
    _hc('POL078','Smith-Mundt Modernization','Policy','domestic','2013','R','Congress',3,7,
       'Propaganda Legalized: +3 to media. +2 to intelligence. Risk: Domestic disinformation.','Smith-Mundt Act modernization allowed US propaganda produced for foreign audiences to be available domestically.','BBG, Voice of America, Radio Free Europe. Thornberry amendment. Critics: government propaganda at home.',['propaganda','media','smith_mundt']),
    _hc('POL079','National Security Action Memorandum 263','Policy','military','1963','R','White House',4,5,
       'Vietnam Withdrawal Plan: +2 to diplomatic. Military -2. Risk: Reversed by NSAM 273 after Dallas.','JFK memo ordering withdrawal of 1,000 US personnel from Vietnam by end of 1963.','Signed Oct 11, 1963. NSAM 273 reversed it Nov 26, 1963, 4 days after JFK assassination. Conspiracy: motive.',['jfk','vietnam','withdrawal']),
    _hc('POL080','FISA Amendments Act 2008','Policy','intelligence','2008','UR','Congress',5,7,
       'Retroactive Immunity: +3 to intelligence. Negate 1 Scandal. Peek 2 face-down. Risk: Telecom collusion.','Granted retroactive immunity to telecoms for warrantless wiretapping, codified Bush surveillance program.','Obama voted yes. Verizon, AT&T immunity. Section 702 created. ACLU opposed. Stemmed from Stellar Wind.',['fisa','warrantless','telecom']),
    # ── Batch 11 Policies: Financial Deregulation & Tech ──
    _hc('POL081','Brooksley Born OTC Warning','Policy','economic','1998','R','CFTC',3,6,
       'Unheeded Warning: +2 to economic. Negate 1 deregulation Policy. Risk: Overruled by Rubin, Summers, Greenspan.','CFTC chair Brooksley Born warned unregulated OTC derivatives posed systemic risk, was silenced by Clinton officials.','Born proposed regulating swaps. Rubin, Summers, Greenspan crushed her. LTCM proved her right. 2008 proved her right again. Congress stripped CFTC authority.',['cftc','derivatives','born_warning']),
    _hc('POL082','Section 230 Communications Decency Act','Policy','social','1996','R','Congress',3,9,
       'Platform Immunity: +3 to media. +2 to tech. Negate 2 Scandals. Risk: Disinformation, Section 230 reform.','Legal shield protecting internet platforms from liability for user content, foundation of social media economy.','"Twenty-six words that created the internet." Google, Facebook, Twitter rely on it. Trump, Biden both wanted reform.',['section_230','tech','platform_immunity']),
    _hc('POL083','Volcker Rule','Policy','economic','2010-2018','R','Congress',3,5,
       'Prop Trading Ban: +2 to economic. Negate 1 Wall Street Org. Risk: Lobbying exemptions, rollback.','Dodd-Frank provision banning banks from proprietary trading with depositor funds.','Paul Volcker. Goldman, JPMorgan lobbied exemptions. Hedging exception. Trump rolled back 2018. SVB collapse 2023.',['volcker_rule','prop_trading','financial_reform']),
    # ── Batch 12 Policies: Tech, Climate & Campaign Finance ──
    _hc('POL084','Export Control Act','Policy','economic','2022','R','White House',4,6,
       'Tech Decoupling: +2 to military. +2 to intelligence. Negate 1 China card. Risk: Retaliation, supply chain disruption.','Biden administration export controls on advanced semiconductors and chipmaking equipment to China.','ASML EUV banned. NVIDIA H100 modified. SMIC. Yangtze Memory. Entity List expansion. Raytheon, KLA. Chip war escalation.',['export_control','semiconductor','china']),
    _hc('POL085','Inflation Reduction Act','Policy','economic','2022','R','White House',4,8,
       'Green New Deal Lite: +3 to social. Oil -2. +2 to economic. Risk: Manchin negotiations, permitting delays.','Largest climate investment in US history, $369B for clean energy, drug price negotiation, IRS funding.','Manchin deal. EV tax credits. Solar, wind subsidies. Methane fee. Drug negotiation. 87K IRS agents. Scorekeeping fight.',['ira','climate','clean_energy']),
    _hc('POL086','McCain-Feingold Act','Policy','domestic','2002-2010','R','Congress',3,6,
       'Campaign Finance Reform: +2 to social. Negate 1 dark money card. Risk: Citizens United overturns.','Bipartisan Campaign Reform Act, banned soft money, restricted issue ads before elections.','527 groups loophole. Swift Boat Veterans. Citizens United 2010 killed it. FEC gridlocked. Super PACs emerged.',['campaign_finance','mccain_feingold','reform']),
]


# ==============================================================================
# SECTION: HISTORY MODE — Political Arena TCG Engine
# ==============================================================================

HISTORY_LIFE = 30
HISTORY_DECK_SIZE = 30
HISTORY_HAND_SIZE = 7
HISTORY_MAX_BOARD = 7
HISTORY_MAX_DISCARDS = 3

# ── Synergy Matrix ────────────────────────────────────────────────────────────
# Tag-pair correlations: when two board cards share tags from a synergy group,
# each card in the group gets +1 PWR and +1 INF per matching pair (max +2).
SYNERGY_GROUPS = [
    # Cold War bloc
    {'tags': {'cold_war', 'soviet', 'cia', 'kgb'}, 'name': 'Cold War', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Intelligence network
    {'tags': {'cia', 'fbi', 'nsa', 'mossad', 'mi6', 'intelligence'}, 'name': 'Intel Network', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Revolutionaries
    {'tags': {'revolution', 'revolutionary'}, 'name': 'Revolutionary Wave', 'bonus_pwr': 2, 'bonus_inf': 0},
    # Dictators
    {'tags': {'dictator'}, 'name': 'Iron Fist', 'bonus_pwr': 1, 'bonus_inf': 0},
    # Bankers & finance
    {'tags': {'wall_street', 'fed', 'banker', 'imf', 'economy', 'economic'}, 'name': 'Money Trail', 'bonus_pwr': 0, 'bonus_inf': 2},
    # Oil & energy
    {'tags': {'oil', 'big_oil', 'nuclear'}, 'name': 'Resource Curse', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Media control
    {'tags': {'media', 'fox', 'mogul'}, 'name': 'Narrative Control', 'bonus_pwr': 0, 'bonus_inf': 2},
    # Secret societies
    {'tags': {'bilderberg', 'cfr', 'trilateral', 'skull_bones', 'freemasons', 'elite'}, 'name': 'Hidden Hand', 'bonus_pwr': 1, 'bonus_inf': 2},
    # Assassination targets
    {'tags': {'assassination'}, 'name': 'Martyrs', 'bonus_pwr': 0, 'bonus_inf': 3},
    # Anti-establishment
    {'tags': {'whistleblower', 'conspiracy', 'activist'}, 'name': 'Truth Seekers', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Military-industrial
    {'tags': {'military', 'pentagon', 'military_industrial', 'war'}, 'name': 'War Machine', 'bonus_pwr': 2, 'bonus_inf': 0},
    # Civil rights
    {'tags': {'civil_rights', 'mlk', 'black_power', 'labor'}, 'name': 'Social Justice', 'bonus_pwr': 0, 'bonus_inf': 3},
    # Communist bloc
    {'tags': {'communist', 'socialist', 'soviet', 'bolsheviks'}, 'name': 'Red Tide', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Rothschild / Rockefeller banking dynasties
    {'tags': {'rothschild', 'rockefeller', 'banker', 'monopoly'}, 'name': 'Old Money', 'bonus_pwr': 0, 'bonus_inf': 2},
    # Bush dynasty
    {'tags': {'bush', 'cia', 'skull_bones', 'deep_state'}, 'name': 'Dynasty', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Russia / Kremlin
    {'tags': {'russia', 'kgb', 'kremlin', 'oligarch', 'soviet'}, 'name': 'Kremlin Power', 'bonus_pwr': 1, 'bonus_inf': 1},
    # China / CCP
    {'tags': {'china', 'communist', 'surveillance'}, 'name': 'Red Dragon', 'bonus_pwr': 2, 'bonus_inf': 0},
    # Israel / Mossad
    {'tags': {'israel', 'mossad'}, 'name': 'Zionist Network', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Colonial / imperial
    {'tags': {'imperialism', 'colonialism', 'british_crown', 'opium'}, 'name': 'Empire', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Nazi / fascist
    {'tags': {'nazi', 'fascist', 'antisemitism'}, 'name': 'Dark Axis', 'bonus_pwr': 2, 'bonus_inf': -1},
    # Drug trade
    {'tags': {'drugs', 'cartel', 'cia', 'mafia'}, 'name': 'Shadow Trade', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Surveillance state
    {'tags': {'surveillance', 'nsa', 'fisa', 'stasi', 'gestapo'}, 'name': 'Panopticon', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Global governance
    {'tags': {'wef', 'davos', 'globalist', 'un', 'imf', 'world_bank'}, 'name': 'New World Order', 'bonus_pwr': 0, 'bonus_inf': 3},
    # Populist wave
    {'tags': {'populist', 'nationalist', 'brexit', 'trump'}, 'name': 'Populist Revolt', 'bonus_pwr': 2, 'bonus_inf': 0},
    # European integration
    {'tags': {'eu', 'european', 'germany', 'france'}, 'name': 'European Project', 'bonus_pwr': 0, 'bonus_inf': 2},
    # Corruption network
    {'tags': {'corruption', 'scandal', 'kleptocrat', 'plunder'}, 'name': 'Graft', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Nobel laureates
    {'tags': {'nobel'}, 'name': 'Peace Prize', 'bonus_pwr': 0, 'bonus_inf': 3},
    # Vietnam era
    {'tags': {'vietnam', 'vietnam_war', 'protest', 'counterculture'}, 'name': 'Anti-War Movement', 'bonus_pwr': 0, 'bonus_inf': 2},
    # Founding era
    {'tags': {'founding_father', 'founding', 'constitution'}, 'name': 'Founding Fathers', 'bonus_pwr': 1, 'bonus_inf': 2},
    # Epstein / blackmail
    {'tags': {'epstein', 'blackmail', 'trafficking'}, 'name': 'Blackmail Network', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Watergate / Nixon
    {'tags': {'watergate', 'nixon', 'coverup'}, 'name': 'Cover-Up', 'bonus_pwr': 1, 'bonus_inf': 1},
    # 9/11 era
    {'tags': {'911', 'terrorism', 'al_qaeda', 'patriot_act'}, 'name': 'War on Terror', 'bonus_pwr': 2, 'bonus_inf': 0},
    # Oil states
    {'tags': {'oil', 'saudi', 'opec', 'libya', 'venezuela'}, 'name': 'Petrodollar', 'bonus_pwr': 1, 'bonus_inf': 2},
    # Ukraine / Russia conflict
    {'tags': {'ukraine', 'russia', 'war', 'sanctions'}, 'name': 'East-West Clash', 'bonus_pwr': 2, 'bonus_inf': 0},
    # African independence
    {'tags': {'congo', 'africa', 'apartheid', 'independence'}, 'name': 'African Liberation', 'bonus_pwr': 1, 'bonus_inf': 2},
    # Latin American left
    {'tags': {'bolivar', 'chile', 'venezuela', 'cuba', 'socialist'}, 'name': 'Latin Left', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Tech billionaires
    {'tags': {'tech', 'disruptor', 'twitter', 'billionaire'}, 'name': 'Tech Bro', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Climate / environmental
    {'tags': {'climate', 'amazon', 'dust_bowl', 'flint'}, 'name': 'Environmental Crisis', 'bonus_pwr': 0, 'bonus_inf': 2},
    # Religious right
    {'tags': {'religious', 'hindu', 'islamic', 'vatican'}, 'name': 'Faith & Power', 'bonus_pwr': 1, 'bonus_inf': 1},
    # Deep state
    {'tags': {'deep_state', 'cia', 'fbi', 'nsa', 'pentagon'}, 'name': 'Deep State', 'bonus_pwr': 1, 'bonus_inf': 2},
    # ── Batch 5 Synergy Groups: Advanced Strategy ──
    # Roman Empire
    {'tags': {'rome', 'roman', 'byzantine', 'constantinople'}, 'name': 'Roman Legacy', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Persian/Achaemenid
    {'tags': {'persia', 'achaemenid', 'iran', 'cyrus'}, 'name': 'Persian Empire', 'bonus_pwr': 1, 'bonus_inf': 2},
    # Asian history
    {'tags': {'japan', 'shogun', 'tokugawa', 'meiji', 'sengoku'}, 'name': 'Rising Sun', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Indian subcontinent
    {'tags': {'india', 'mughal', 'maurya', 'buddhism', 'hindu'}, 'name': 'Subcontinent', 'bonus_pwr': 1, 'bonus_inf': 2},
    # African kingdoms
    {'tags': {'africa', 'zulu', 'mali', 'gold', 'angola'}, 'name': 'African Kingdoms', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Arms control & treaties
    {'tags': {'arms_control', 'detente', 'inf', 'salt', 'nuclear'}, 'name': 'Arms Control', 'bonus_pwr': 0, 'bonus_inf': 3},
    # Financial crime network
    {'tags': {'fraud', 'money_laundering', 'tax_evasion', 'offshore', 'corruption'}, 'name': 'White Collar Crime', 'bonus_pwr': 1, 'bonus_inf': 2},
    # Tech surveillance
    {'tags': {'tech', 'surveillance', 'data', 'ai', 'meta', 'google'}, 'name': 'Digital Panopticon', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Colonialism
    {'tags': {'colonial', 'imperialism', 'british_crown', 'opium', 'tordesillas'}, 'name': 'Colonial Powers', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Geopolitical alliances
    {'tags': {'nato', 'warsaw_pact', 'brics', 'african_union', 'alliance'}, 'name': 'Alliance System', 'bonus_pwr': 1, 'bonus_inf': 2},
    # Religious wars & crusades
    {'tags': {'crusades', 'jerusalem', 'religious', 'ottoman', 'byzantine'}, 'name': 'Holy Wars', 'bonus_pwr': 2, 'bonus_inf': 0},
    # Whistleblowers & transparency
    {'tags': {'whistleblower', 'panama_papers', 'pandora_papers', 'luxleaks', 'offshore'}, 'name': 'Transparency', 'bonus_pwr': 0, 'bonus_inf': 3},
    # Dark money & political spending
    {'tags': {'dark_money', 'citizens_united', 'lobbying', 'campaign_finance', 'super_pac'}, 'name': 'Bought Democracy', 'bonus_pwr': 2, 'bonus_inf': 1},
    # ── Batch 6 Synergy Groups: Advanced Geopolitical Strategy ──
    # Cold War superpower rivalry
    {'tags': {'cold_war', 'soviet', 'detente', 'glasnost', 'stagnation'}, 'name': 'Cold War Rivalry', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Military-industrial complex
    {'tags': {'military_industrial', 'lockheed', 'raytheon', 'defense', 'pentagon'}, 'name': 'Military-Industrial Complex', 'bonus_pwr': 3, 'bonus_inf': 1},
    # Non-Aligned Movement
    {'tags': {'non_aligned', 'india', 'yugoslavia', 'ghana', 'pan_african'}, 'name': 'Non-Aligned Movement', 'bonus_pwr': 0, 'bonus_inf': 3},
    # Fascist dictators
    {'tags': {'fascist', 'mussolini', 'franco', 'dictator', 'spain'}, 'name': 'Fascist Axis', 'bonus_pwr': 3, 'bonus_inf': 0},
    # Israeli-Arab conflict
    {'tags': {'israel', 'arab', 'six_day', 'yom_kippur', 'palestine'}, 'name': 'Holy Land Conflict', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Soviet reform & collapse
    {'tags': {'soviet', 'reform', 'glasnost', 'perestroika', 'stagnation'}, 'name': 'Soviet Collapse', 'bonus_pwr': 1, 'bonus_inf': 3},
    # Deregulation & financial crisis
    {'tags': {'deregulation', 'gramm_leach_bliley', 'banking', 'crash', 'wall_street'}, 'name': 'Deregulation Disaster', 'bonus_pwr': 2, 'bonus_inf': 2},
    # CIA blowback operations
    {'tags': {'blowback', 'afghanistan', 'cyclone', 'syria', 'iran'}, 'name': 'CIA Blowback', 'bonus_pwr': 2, 'bonus_inf': 1},
    # European integration
    {'tags': {'eu', 'maastricht', 'euro', 'europe', 'diplomatic'}, 'name': 'European Project', 'bonus_pwr': 1, 'bonus_inf': 3},
    # Biowarfare & experiments
    {'tags': {'biological', 'bioterror', 'experiment', 'pandemic', 'simulation'}, 'name': 'Biowarfare Program', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Neoconservative hegemony
    {'tags': {'neocon', 'iraq', 'hegemony', 'wmd', 'military'}, 'name': 'Neocon Agenda', 'bonus_pwr': 3, 'bonus_inf': 1},
    # ── Batch 7 Synergy Groups: Conspiracy & Deep State ──
    # JFK assassination web
    {'tags': {'jfk', 'oswald', 'grassy_knoll', 'watergate', 'cia'}, 'name': 'JFK Assassination Web', 'bonus_pwr': 3, 'bonus_inf': 2},
    # MKUltra & mind control
    {'tags': {'mkultra', 'mind_control', 'monarch', 'bluebird', 'experiment'}, 'name': 'Mind Control Program', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Elite secret societies
    {'tags': {'skull_bones', 'bilderberg', 'trilateral', 'cfr', 'bohemian'}, 'name': 'Power Elite', 'bonus_pwr': 1, 'bonus_inf': 3},
    # Epstein-Blackmail network
    {'tags': {'epstein', 'maxwell', 'flight_logs', 'blackmail', 'trafficking'}, 'name': 'Blackmail Network', 'bonus_pwr': 2, 'bonus_inf': 3},
    # Deep state & permanent government
    {'tags': {'deep_state', 'cia', 'nsa', 'fbi', 'surveillance'}, 'name': 'Deep State', 'bonus_pwr': 3, 'bonus_inf': 2},
    # QAnon & modern conspiracy culture
    {'tags': {'qanon', 'pizzagate', 'truther', 'conspiracy', 'jan6'}, 'name': 'Conspiracy Culture', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Church Committee & exposure
    {'tags': {'church_committee', 'exposure', 'whistleblower', 'cointelpro', 'pentagon_papers'}, 'name': 'Great Exposure', 'bonus_pwr': 1, 'bonus_inf': 3},
    # Iran-Contra web
    {'tags': {'iran_contra', 'contra', 'drugs', 'oliver_north', 'pardon'}, 'name': 'Iran-Contra Web', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Operation Condor
    {'tags': {'condor', 'argentina', 'chile', 'assassination', 'disappeared'}, 'name': 'Condor Network', 'bonus_pwr': 3, 'bonus_inf': 1},
    # Civil liberties erosion
    {'tags': {'patriot_act', 'fisa', 'ndaa', 'surveillance', 'civil_liberties'}, 'name': 'Liberty Erosion', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Business plot & corporate coup
    {'tags': {'business_plot', 'fdr', 'coup', 'wall_street', 'military'}, 'name': 'Corporate Coup', 'bonus_pwr': 2, 'bonus_inf': 2},
    # PROMIS/Octopus conspiracy
    {'tags': {'promis', 'inslaw', 'casolaro', 'espionage', 'software'}, 'name': 'The Octopus', 'bonus_pwr': 2, 'bonus_inf': 2},
    # ── Batch 8 Synergy Groups: Neocon, Intelligence & Geopolitical ──
    # Neocon architects (Wolfowitz, Perle, Feith, Abrams, Chalabi)
    {'tags': {'neocon', 'iraq', 'osp', 'pentagon', 'wmd'}, 'name': 'Neocon Architects', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Iraq WMD fabrication web
    {'tags': {'iraq', 'wmd', 'curveball', 'yellowcake', 'intelligence_failure'}, 'name': 'WMD Fabrication', 'bonus_pwr': 2, 'bonus_inf': 3},
    # CIA directors network
    {'tags': {'cia', 'mkultra', 'church_committee', 'torture', 'rendition'}, 'name': 'CIA Directors Web', 'bonus_pwr': 3, 'bonus_inf': 1},
    # Iran-Contra network
    {'tags': {'iran_contra', 'contra', 'nicaragua', 'pardon', 'conviction'}, 'name': 'Iran-Contra Network', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Warrantless surveillance
    {'tags': {'stellar_wind', 'section_702', 'fisa', 'warrantless', 'surveillance'}, 'name': 'Warrantless Surveillance', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Color revolutions
    {'tags': {'color_revolution', 'soros', 'ned', 'revolutionary', 'democracy'}, 'name': 'Color Revolution', 'bonus_pwr': 1, 'bonus_inf': 3},
    # Clean Break / Israel strategy
    {'tags': {'neocon', 'israel', 'iraq', 'clean_break', 'iran'}, 'name': 'Clean Break Strategy', 'bonus_pwr': 3, 'bonus_inf': 2},
    # CIA media manipulation
    {'tags': {'mockingbird', 'media', 'propaganda', 'cia', 'journalist'}, 'name': 'Media Manipulation', 'bonus_pwr': 1, 'bonus_inf': 3},
    # Cyber warfare
    {'tags': {'stuxnet', 'cyber', 'iran', 'israel', 'nsa'}, 'name': 'Cyber Warfare', 'bonus_pwr': 3, 'bonus_inf': 1},
    # Private military contractors
    {'tags': {'blackwater', 'mercenary', 'iraq', 'military', 'pentagon'}, 'name': 'Private Military', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Total surveillance panopticon
    {'tags': {'tia', 'darpa', 'poindexter', 'panopticon', 'surveillance'}, 'name': 'Total Surveillance', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Syria intervention blowback
    {'tags': {'syria', 'timber_sycamore', 'arms', 'blowback', 'isis'}, 'name': 'Syria Blowback', 'bonus_pwr': 2, 'bonus_inf': 1},
    # ── Batch 9 Synergy Groups: Russian Intel, Finance & Geopolitics ──
    # Russian silovik network (FSB/KGB inner circle)
    {'tags': {'fsb', 'kgb', 'russia', 'silovik', 'surveillance'}, 'name': 'Silovik Network', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Russian assassinations and poisonings
    {'tags': {'russia', 'novichok', 'assassination', 'false_flag', 'kgb'}, 'name': 'KGB Hit Squad', 'bonus_pwr': 3, 'bonus_inf': 1},
    # PNAC neocon war agenda
    {'tags': {'neocon', 'pnc', 'iraq', 'hegemony', 'military'}, 'name': 'PNAC War Agenda', 'bonus_pwr': 3, 'bonus_inf': 2},
    # RAND nuclear strategists
    {'tags': {'rand', 'nuclear', 'strategy', 'neocon', 'pentagon'}, 'name': 'RAND Strategists', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Epstein blackmail network
    {'tags': {'epstein', 'blackmail', 'wexner', 'black_book', 'trafficking'}, 'name': 'Epstein Network', 'bonus_pwr': 3, 'bonus_inf': 3},
    # Global banking elite
    {'tags': {'bis', 'imf', 'central_banking', 'basel', 'gold'}, 'name': 'Global Banking Elite', 'bonus_pwr': 1, 'bonus_inf': 3},
    # Clinton scandals web
    {'tags': {'clinton', 'arkansas', 'pardon', 'rich', 'conspiracy'}, 'name': 'Clinton Scandal Web', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Too big to jail banking
    {'tags': {'hsbc', 'cfma', 'deregulation', 'derivatives', 'money_laundering'}, 'name': 'Too Big to Jail', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Sanctions warfare
    {'tags': {'caatsa', 'sanctions', 'russia', 'nord_stream', 'economic'}, 'name': 'Sanctions Warfare', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Vatican intelligence network
    {'tags': {'vatican', 'nazi', 'escape', 'intelligence', 'catholic'}, 'name': 'Vatican Intelligence', 'bonus_pwr': 2, 'bonus_inf': 2},
    # CIA domestic operations
    {'tags': {'eo12333', 'cia', 'domestic', 'intelligence', 'surveillance'}, 'name': 'CIA Domestic Ops', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Foundation globalism network
    {'tags': {'foundations', 'globalism', 'rockefeller', 'cfr', 'bilderberg'}, 'name': 'Foundation Globalism', 'bonus_pwr': 1, 'bonus_inf': 3},
    # ── Batch 10 Synergy Groups: Deep State, Drones & Geopolitics ──
    # Drone assassination program
    {'tags': {'cia', 'drones', 'assassination', 'jsoc', 'special_ops'}, 'name': 'Kill Program', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Neocon intellectual network
    {'tags': {'neocon', 'aei', 'kristol', 'pnc', 'hegemony'}, 'name': 'Neocon Intelligentsia', 'bonus_pwr': 2, 'bonus_inf': 3},
    # Ukraine regime change network
    {'tags': {'ukraine', 'maidan', 'state_dept', 'nuland', 'regime_change'}, 'name': 'Maidan Network', 'bonus_pwr': 2, 'bonus_inf': 2},
    # FISA surveillance state
    {'tags': {'fisa', 'warrantless', 'surveillance', 'fbi', 'telecom'}, 'name': 'FISA Surveillance', 'bonus_pwr': 2, 'bonus_inf': 2},
    # WMD fabrication pipeline
    {'tags': {'iraq', 'wmd', 'forgery', 'yellowcake', 'cia'}, 'name': 'WMD Fabrication', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Iran-Contra shadow government
    {'tags': {'iran_contra', 'north', 'shadow_gov', 'contra', 'poindexter'}, 'name': 'Shadow Government', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Latin American dirty wars
    {'tags': {'cia', 'soa', 'dirty_war', 'south_america', 'assassination'}, 'name': 'Dirty Wars', 'bonus_pwr': 2, 'bonus_inf': 1},
    # Media propaganda pipeline
    {'tags': {'media', 'propaganda', 'smith_mundt', 'mockingbird', 'fairness_doctrine'}, 'name': 'Propaganda Pipeline', 'bonus_pwr': 1, 'bonus_inf': 3},
    # JFK assassination nexus
    {'tags': {'jfk', 'cia', 'assassination', 'conspiracy', 'vietnam'}, 'name': 'JFK Nexus', 'bonus_pwr': 3, 'bonus_inf': 3},
    # Nuclear brinkmanship
    {'tags': {'nuclear', 'cold_war', '1983', 'rand', 'strategy'}, 'name': 'Nuclear Brinkmanship', 'bonus_pwr': 3, 'bonus_inf': 1},
    # Silicon Valley intelligence pipeline
    {'tags': {'cia', 'venture_capital', 'silicon_valley', 'surveillance', 'palantir'}, 'name': 'Tech Intel Pipeline', 'bonus_pwr': 2, 'bonus_inf': 3},
    # MKUltra subprojects
    {'tags': {'cia', 'mkultra', 'honey_trap', 'mind_control', 'experiment'}, 'name': 'MKUltra Programs', 'bonus_pwr': 2, 'bonus_inf': 2},
    # ── Batch 11 Synergy Groups: Media, Finance, Tech & Political Movements ──
    # Conservative media empire
    {'tags': {'fox', 'media', 'ailes', 'conservative', 'murdoch'}, 'name': 'Conservative Media Empire', 'bonus_pwr': 2, 'bonus_inf': 4},
    # Wall Street too big to fail
    {'tags': {'wall_street', 'jpmorgan', 'goldman', 'bailout', 'cdo'}, 'name': 'Too Big to Fail', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Asset manager triumvirate
    {'tags': {'blackrock', 'vanguard', 'asset_management', 'esg', 'aladdin'}, 'name': 'Asset Manager Triumvirate', 'bonus_pwr': 2, 'bonus_inf': 4},
    # Tech surveillance capitalism
    {'tags': {'facebook', 'social_media', 'surveillance', 'section_230', 'platform_immunity'}, 'name': 'Surveillance Capitalism', 'bonus_pwr': 1, 'bonus_inf': 4},
    # Neocon war machine
    {'tags': {'neocon', 'iraq', 'halliburton', 'pentagon', 'wmd'}, 'name': 'Neocon War Machine', 'bonus_pwr': 4, 'bonus_inf': 2},
    # Dark money political network
    {'tags': {'dark_money', 'koch', 'mercer', 'scl_group', 'citadel'}, 'name': 'Dark Money Network', 'bonus_pwr': 2, 'bonus_inf': 3},
    # Financial deregulation pipeline
    {'tags': {'cfma', 'derivatives', 'deregulation', 'born_warning', 'credit_suisse'}, 'name': 'Deregulation Pipeline', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Evidence laundering surveillance state
    {'tags': {'nsa', 'dea', 'surveillance', 'parallel_construction', 'fisa'}, 'name': 'Evidence Laundering', 'bonus_pwr': 2, 'bonus_inf': 3},
    # Populist revolt pipeline
    {'tags': {'tea_party', 'populist', 'koch', 'occupy', 'inequality'}, 'name': 'Populist Revolt Pipeline', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Data-driven election manipulation
    {'tags': {'scl_group', 'data', 'psyops', 'facebook', 'election'}, 'name': 'Election Manipulation', 'bonus_pwr': 2, 'bonus_inf': 4},
    # Corporate regulatory capture
    {'tags': {'boeing', 'faa', 'corporate', 'wells_fargo', 'fraud'}, 'name': 'Regulatory Capture', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Israel lobby network
    {'tags': {'adelson', 'israel', 'casino', 'aipac', 'neocon'}, 'name': 'Israel Lobby', 'bonus_pwr': 2, 'bonus_inf': 3},
    # ── Batch 12 Synergy Groups: Energy, Cyber, Trump Ops & Military-Industrial ──
    # Big Oil climate denial network
    {'tags': {'exxon', 'oil', 'climate_denial', 'koch', 'opec'}, 'name': 'Big Oil Denial Network', 'bonus_pwr': 3, 'bonus_inf': 3},
    # Trump-Russia nexus
    {'tags': {'manafort', 'flynn', 'russia', 'trump', 'giuliani'}, 'name': 'Trump-Russia Nexus', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Plame affair / CIA leak
    {'tags': {'libby', 'plame', 'neocon', 'cia', 'cheney'}, 'name': 'Plame Affair', 'bonus_pwr': 2, 'bonus_inf': 3},
    # Gulf War military machine
    {'tags': {'gulf_war', 'pentagon', 'iraq', 'military', 'schwarzkopf'}, 'name': 'Gulf War Coalition', 'bonus_pwr': 3, 'bonus_inf': 1},
    # JSOC special operations network
    {'tags': {'jsoc', 'special_ops', 'mattis', 'mcchrystal', 'assassination'}, 'name': 'JSOC Kill/Capture', 'bonus_pwr': 4, 'bonus_inf': 1},
    # Cyber warfare and espionage
    {'tags': {'solarwinds', 'cyber', 'russia', 'nso', 'pegasus'}, 'name': 'Cyber Espionage Network', 'bonus_pwr': 2, 'bonus_inf': 4},
    # Climate policy vs denial
    {'tags': {'paris', 'climate', 'ira', 'clean_energy', 'emissions'}, 'name': 'Climate Policy Pipeline', 'bonus_pwr': 1, 'bonus_inf': 4},
    # Corporate science suppression
    {'tags': {'exxon', 'tobacco', 'coverup', 'pr', 'climate_denial'}, 'name': 'Corporate Science Suppression', 'bonus_pwr': 2, 'bonus_inf': 3},
    # Syria covert operations
    {'tags': {'cia', 'syria', 'arms', 'mossad', 'propaganda'}, 'name': 'Syria Covert Ops', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Russia energy weaponization
    {'tags': {'russia', 'oil', 'oligarch', 'yukos', 'nord_stream'}, 'name': 'Russian Energy Weapon', 'bonus_pwr': 3, 'bonus_inf': 2},
    # Crypto collapse pipeline
    {'tags': {'ftx', 'crypto', 'fraud', 'gamestop', 'wall_street'}, 'name': 'Crypto Collapse', 'bonus_pwr': 2, 'bonus_inf': 2},
    # Semiconductor geopolitics
    {'tags': {'chips', 'semiconductor', 'china', 'export_control', 'taiwan'}, 'name': 'Chip War', 'bonus_pwr': 2, 'bonus_inf': 3},
]

def compute_synergy_bonus(board: List[HistoryCard], card: HistoryCard) -> tuple:
    """Returns (bonus_pwr, bonus_inf, synergy_names) for a card based on board synergies."""
    total_pwr = 0
    total_inf = 0
    active_names = []
    for group in SYNERGY_GROUPS:
        group_tags = group['tags']
        if not any(t in card.tags for t in group_tags):
            continue
        # Count how many OTHER board cards share at least one tag from this group
        matching = sum(1 for c in board if c is not card and any(t in c.tags for t in group_tags))
        if matching > 0:
            bonus_mult = min(matching, 2)  # cap at 2 matches
            total_pwr += group['bonus_pwr'] * bonus_mult
            total_inf += group['bonus_inf'] * bonus_mult
            active_names.append(group['name'])
    return total_pwr, total_inf, active_names


class HistoryPlayer:
    def __init__(self, name: str, deck: List[HistoryCard], is_ai: bool = False):
        self.name = name
        self.deck = deck[:]
        random.shuffle(self.deck)
        self.hand: List[HistoryCard] = []
        self.board: List[HistoryCard] = []
        self.face_down: List[HistoryCard] = []
        self.organization: Optional[HistoryCard] = None
        self.policy: Optional[HistoryCard] = None
        self.life = HISTORY_LIFE
        self.is_ai = is_ai
        self.attacks_used = set()  # card_ids that already attacked this turn
        self.just_played = set()   # card_ids played this turn (can't attack yet)
        self.treasury = 0          # money earned from economic cards — spend for bonuses
        self.money_spent = 0       # track total spent for stats
        self.discards_used = 0     # discards used this turn (max 3)

    def earn_money(self, amount: int):
        self.treasury += amount

    def spend_money(self, amount: int) -> bool:
        if self.treasury >= amount:
            self.treasury -= amount
            self.money_spent += amount
            return True
        return False

    def draw(self, n: int = 1):
        for _ in range(n):
            if self.deck:
                self.hand.append(self.deck.pop(0))

    def play_figure(self, card: HistoryCard) -> str:
        if len(self.board) >= HISTORY_MAX_BOARD:
            return "Board is full!"
        self.hand.remove(card)
        self.board.append(card)
        self.just_played.add(card.card_id)
        return f"Played {card.name} (PWR {card.power} INF {card.influence})"

    def play_event(self, card: HistoryCard, opponent: 'HistoryPlayer') -> str:
        self.hand.remove(card)
        dmg = card.power
        heal = card.influence
        opponent.life -= dmg
        self.life = min(HISTORY_LIFE, self.life + heal)
        return f"Event {card.name}: Deal {dmg} damage, heal {heal} influence"

    def play_conspiracy(self, card: HistoryCard) -> str:
        self.hand.remove(card)
        self.face_down.append(card)
        return f"Placed {card.name} face-down as conspiracy trap"

    def play_scandal(self, card: HistoryCard, target: HistoryCard, opponent: 'HistoryPlayer') -> str:
        self.hand.remove(card)
        target._scandal_power = getattr(target, '_scandal_power', 0) + card.power
        target._scandal_influence = getattr(target, '_scandal_influence', 0) + card.influence
        eff_pwr = self.get_effective_power(target)
        eff_inf = self.get_effective_influence(target)
        msg = f"Scandal {card.name} on {target.name}: -{card.power} PWR -{card.influence} INF"
        if eff_inf <= 0:
            opponent.board.remove(target)
            msg += f" | {target.name} destroyed!"
        return msg

    def play_organization(self, card: HistoryCard) -> str:
        self.hand.remove(card)
        old = self.organization
        self.organization = card
        if old:
            return f"Replaced {old.name} with {card.name} as your Organization"
        return f"Established {card.name} as your Organization"

    def play_policy(self, card: HistoryCard) -> str:
        self.hand.remove(card)
        old = self.policy
        self.policy = card
        if old:
            return f"Replaced {old.name} with {card.name} as your Policy"
        return f"Enacted {card.name} as your Policy"

    @staticmethod
    def get_effective_power(card: HistoryCard) -> int:
        base = card.power
        scandal_red = getattr(card, '_scandal_power', 0)
        return max(0, base - scandal_red)

    @staticmethod
    def get_effective_influence(card: HistoryCard) -> int:
        base = card.influence
        scandal_red = getattr(card, '_scandal_influence', 0)
        return max(0, base - scandal_red)

    def get_org_power_bonus(self, card: HistoryCard) -> int:
        if self.organization and card.organization == self.organization.organization:
            return 1
        return 0

    def get_org_influence_bonus(self, card: HistoryCard) -> int:
        if self.organization and card.organization == self.organization.organization:
            return 1
        return 0

    def get_synergy_power_bonus(self, card: HistoryCard) -> int:
        pwr, _, _ = compute_synergy_bonus(self.board, card)
        return pwr

    def get_synergy_influence_bonus(self, card: HistoryCard) -> int:
        _, inf, _ = compute_synergy_bonus(self.board, card)
        return inf

    def get_synergy_names(self, card: HistoryCard) -> list:
        _, _, names = compute_synergy_bonus(self.board, card)
        return names

    def get_total_power(self) -> int:
        return sum(self.get_effective_power(c) + self.get_org_power_bonus(c) + self.get_synergy_power_bonus(c) for c in self.board)

    def get_total_influence(self) -> int:
        return sum(self.get_effective_influence(c) + self.get_org_influence_bonus(c) + self.get_synergy_influence_bonus(c) for c in self.board)

    def has_defense(self) -> bool:
        return any(self.get_effective_influence(c) + self.get_org_influence_bonus(c) + self.get_synergy_influence_bonus(c) > 0 for c in self.board)

    def get_card_attack_power(self, card: HistoryCard) -> int:
        return self.get_effective_power(card) + self.get_org_power_bonus(card) + self.get_synergy_power_bonus(card)

    def get_card_defense_influence(self, card: HistoryCard) -> int:
        return self.get_effective_influence(card) + self.get_org_influence_bonus(card) + self.get_synergy_influence_bonus(card)

    def discard_card(self, card: HistoryCard) -> str:
        """Discard a hand card (up to 3 per turn). Draw a replacement."""
        if card not in self.hand:
            return "Card not in your hand"
        if self.discards_used >= HISTORY_MAX_DISCARDS:
            return f"Already discarded {HISTORY_MAX_DISCARDS} cards this turn"
        self.hand.remove(card)
        self.discards_used += 1
        if self.deck:
            self.draw(1)
            return f"Discarded {card.name} and drew a replacement ({self.discards_used}/{HISTORY_MAX_DISCARDS} discards used)"
        return f"Discarded {card.name} ({self.discards_used}/{HISTORY_MAX_DISCARDS} discards used). Deck empty, no replacement."

    def end_turn_cleanup(self):
        self.attacks_used.clear()
        self.just_played.clear()
        self.discards_used = 0

    def to_dict(self) -> dict:
        return {
            'name': self.name, 'life': self.life, 'is_ai': self.is_ai,
            'deck_count': len(self.deck), 'hand_count': len(self.hand),
            'board_count': len(self.board),
        }


class HistoryGame:
    def __init__(self, p1: HistoryPlayer, p2: HistoryPlayer, max_rounds: int = 30):
        self.players = [p1, p2]
        self.current_player_idx = 0
        self.current_round = 1
        self.max_rounds = max_rounds
        self.game_over = False
        self.winner: Optional[HistoryPlayer] = None
        self.log: List[str] = []
        self.phase = 'play'  # 'play' or 'attack'
        self.ai_difficulty = 'medium'

    @property
    def current_player(self) -> HistoryPlayer:
        return self.players[self.current_player_idx]

    @property
    def opponent(self) -> HistoryPlayer:
        return self.players[1 - self.current_player_idx]

    def setup(self):
        for p in self.players:
            p.draw(HISTORY_HAND_SIZE)
        self.log.append(f"Game started! {self.players[0].name} vs {self.players[1].name}")

    def start_turn(self):
        p = self.current_player
        draw_count = 2 if self.current_player.policy else 1
        p.draw(draw_count)
        self.log.append(f"{p.name} draws {draw_count} card(s)")
        self.phase = 'play'

    def play_card(self, card: HistoryCard, target: Optional[HistoryCard] = None) -> str:
        p = self.current_player
        opp = self.opponent
        # Money/grind mechanic: economic cards and economic-tagged figures earn money
        money_earned = 0
        if card.card_type in ('Event', 'Policy', 'Organization') and card.category == 'economic':
            money_earned = 2
        elif card.card_type == 'Figure' and 'economic' in card.tags:
            money_earned = 1
        elif any(t in card.tags for t in ('wall_street', 'banker', 'fed', 'oil', 'gold')):
            money_earned = 1
        if money_earned:
            p.earn_money(money_earned)
        if card.card_type == 'Figure':
            result = p.play_figure(card)
            return result + (f" (+${money_earned})" if money_earned else "")
        elif card.card_type == 'Event':
            return p.play_event(card, opp) + (f" (+${money_earned})" if money_earned else "")
        elif card.card_type == 'Conspiracy':
            return p.play_conspiracy(card)
        elif card.card_type == 'Scandal':
            if not target or target not in opp.board:
                return "Need to select an opponent figure to scandalize"
            return p.play_scandal(card, target, opp)
        elif card.card_type == 'Organization':
            return p.play_organization(card) + (f" (+${money_earned})" if money_earned else "")
        elif card.card_type == 'Policy':
            return p.play_policy(card) + (f" (+${money_earned})" if money_earned else "")
        return "Unknown card type"

    def attack(self, attacker: HistoryCard, target: Optional[HistoryCard] = None) -> str:
        p = self.current_player
        opp = self.opponent
        if attacker not in p.board:
            return "Card not on your board"
        if attacker.card_id in p.attacks_used:
            return "Already attacked with this card this turn"
        if attacker.card_id in p.just_played:
            return "Card can't attack the turn it's played (summoning sickness)"

        dmg = p.get_card_attack_power(attacker) + getattr(attacker, '_bought_power', 0)
        syn_names = p.get_synergy_names(attacker)
        p.attacks_used.add(attacker.card_id)
        syn_msg = f" [Synergy: {', '.join(syn_names)}]" if syn_names else ""

        if target is None:
            if opp.has_defense():
                return "Must attack a defending figure first!"
            opp.life -= dmg
            msg = f"{attacker.name} attacks directly for {dmg} damage!{syn_msg}"
            # Check for conspiracy trap
            if opp.face_down:
                trap = opp.face_down.pop(0)
                trap_dmg = opp.get_effective_power(trap)
                trap_inf = opp.get_effective_influence(trap)
                p.life -= trap_dmg
                msg += f" | TRAP: {trap.name} counters for {trap_dmg} damage!"
                self.log.append(msg)
                self._check_deaths()
                return msg
            self.log.append(msg)
            self._check_deaths()
            return msg
        else:
            if target not in opp.board:
                return "Invalid target"
            target_inf = opp.get_card_defense_influence(target)
            target_pwr = opp.get_effective_power(target) + opp.get_org_power_bonus(target) + opp.get_synergy_power_bonus(target)
            # Attacker overpowers defender
            if dmg >= target_inf:
                opp.board.remove(target)
                spill = dmg - target_inf
                opp.life -= spill
                msg = f"{attacker.name} destroys {target.name}! {spill} spill damage to opponent.{syn_msg}"
            else:
                # Partial damage — reduce target's effective influence temporarily
                target._temp_inf_reduce = getattr(target, '_temp_inf_reduce', 0) + dmg
                # Counterattack
                counter = min(target_pwr, 3)
                p.life -= counter
                msg = f"{attacker.name} attacks {target.name} for {dmg}. Target survives, counters for {counter}.{syn_msg}"
            self.log.append(msg)
            self._check_deaths()
            return msg

    def _check_deaths(self):
        for p in self.players:
            if p.life <= 0:
                p.life = 0
                self.game_over = True
                winner = self.players[1] if p == self.players[0] else self.players[0]
                self.winner = winner
                self.log.append(f"{p.name} has been defeated! {winner.name} wins!")
                return

    def buy_power(self, card: HistoryCard) -> str:
        """Spend $5 treasury to give a board figure +2 attack power this turn."""
        p = self.current_player
        if card not in p.board:
            return "Card not on your board"
        if not p.spend_money(5):
            return f"Not enough money (need $5, have ${p.treasury})"
        card._bought_power = getattr(card, '_bought_power', 0) + 2
        msg = f"Bought +2 PWR for {card.name} (-$5). Treasury: ${p.treasury}"
        self.log.append(msg)
        return msg

    def buy_heal(self) -> str:
        """Spend $8 treasury to heal 3 life."""
        p = self.current_player
        if not p.spend_money(8):
            return f"Not enough money (need $8, have ${p.treasury})"
        p.life = min(HISTORY_LIFE, p.life + 3)
        msg = f"Bought 3 life back (-$8). Life: {p.life}. Treasury: ${p.treasury}"
        self.log.append(msg)
        return msg

    def sacrifice_card(self, card: HistoryCard) -> str:
        """Discard a hand card to gain $3 treasury. The grind."""
        p = self.current_player
        if card not in p.hand:
            return "Card not in your hand"
        p.hand.remove(card)
        p.earn_money(3)
        msg = f"Sacrificed {card.name} for $3. Treasury: ${p.treasury}"
        self.log.append(msg)
        return msg

    def buy_card(self) -> str:
        """Spend $4 treasury to draw a card from deck."""
        p = self.current_player
        if not p.spend_money(4):
            return f"Not enough money (need $4, have ${p.treasury})"
        if len(p.deck) == 0:
            p.treasury += 4  # refund
            return "Deck is empty — cannot draw"
        p.draw(1)
        msg = f"Bought a card draw (-$4). Hand: {len(p.hand)}. Treasury: ${p.treasury}"
        self.log.append(msg)
        return msg

    def reveal_conspiracy(self) -> str:
        """Spend $6 treasury to reveal one opponent face-down card."""
        p = self.current_player
        opp = self.opponent
        if not p.spend_money(6):
            return f"Not enough money (need $6, have ${p.treasury})"
        if not opp.face_down:
            p.treasury += 6  # refund
            return "Opponent has no face-down cards"
        card = opp.face_down.pop(0)
        msg = f"Revealed {card.name} — conspiracy trap neutralized! (-$6)"
        self.log.append(msg)
        return msg

    def discard_card(self, card: HistoryCard) -> str:
        """Discard a hand card (up to 3 per turn). Draw a replacement."""
        p = self.current_player
        msg = p.discard_card(card)
        self.log.append(msg)
        return msg

    def switch_to_attack_phase(self):
        self.phase = 'attack'
        self.log.append(f"{self.current_player.name} enters attack phase")

    def end_turn(self):
        p = self.current_player
        opp = self.opponent
        p.end_turn_cleanup()
        # Heal temporary reductions on opponent board
        for c in opp.board:
            if hasattr(c, '_temp_inf_reduce'):
                del c._temp_inf_reduce
        # Clear bought power bonuses
        for c in p.board:
            if hasattr(c, '_bought_power'):
                del c._bought_power
        self.current_player_idx = 1 - self.current_player_idx
        if self.current_player_idx == 0:
            self.current_round += 1
        if self.current_round > self.max_rounds and not self.game_over:
            self.game_over = True
            self.winner = max(self.players, key=lambda p: p.life)
            self.log.append(f"Max rounds reached! {self.winner.name} wins with {self.winner.life} influence!")
        if not self.game_over:
            self.start_turn()

    def check_win(self) -> bool:
        return self.game_over

    # ── AI Logic ─────────────────────────────────────────────────────────────

    def ai_take_turn(self, player: HistoryPlayer) -> List[str]:
        opp = self.opponent
        actions = []

        # Phase 1: Play cards
        # Priority: Organization > Policy > Figure (synergy-aware) > Event > Scandal > Conspiracy
        def figure_synergy_score(card):
            """Score a figure by how much synergy it would create on the current board."""
            test_board = player.board + [card]
            _, _, names = compute_synergy_bonus(test_board, card)
            pwr_bonus, inf_bonus, _ = compute_synergy_bonus(test_board, card)
            return len(names) * 10 + pwr_bonus * 3 + inf_bonus * 2

        played_something = True
        while played_something:
            played_something = False
            # Sort figures by synergy score + base power
            hand_figures = [c for c in player.hand if c.card_type == 'Figure']
            hand_figures.sort(key=lambda c: (figure_synergy_score(c), c.power), reverse=True)

            # Try Organization first
            for card in player.hand:
                if card.card_type == 'Organization' and not player.organization:
                    result = self.play_card(card)
                    actions.append(result)
                    played_something = True
                    break
            if played_something:
                continue

            # Try Policy
            for card in player.hand:
                if card.card_type == 'Policy' and not player.policy:
                    result = self.play_card(card)
                    actions.append(result)
                    played_something = True
                    break
            if played_something:
                continue

            # Try best synergy figure
            if hand_figures and len(player.board) < HISTORY_MAX_BOARD:
                best = hand_figures[0]
                result = self.play_card(best)
                actions.append(result)
                played_something = True
                continue

            # Try Event if good value
            for card in player.hand:
                if card.card_type == 'Event':
                    if card.power >= 5 or (card.influence >= 4 and player.life < 15):
                        result = self.play_card(card)
                        actions.append(result)
                        played_something = True
                        break
            if played_something:
                continue

            # Try Scandal on biggest threat
            for card in player.hand:
                if card.card_type == 'Scandal' and opp.board:
                    biggest = max(opp.board, key=lambda c: opp.get_card_defense_influence(c))
                    result = self.play_card(card, target=biggest)
                    actions.append(result)
                    played_something = True
                    break
            if played_something:
                continue

            # Try Conspiracy
            for card in player.hand:
                if card.card_type == 'Conspiracy' and len(player.face_down) < 2:
                    result = self.play_card(card)
                    actions.append(result)
                    played_something = True
                    break

        # Phase 2: Attack
        self.switch_to_attack_phase()
        # AI money usage: buy heal if low life and affordable
        if player.life <= 10 and player.treasury >= 8:
            result = self.buy_heal()
            actions.append(result)
        # AI: sacrifice weakest hand card for money if hand is large and treasury < 5
        if len(player.hand) > 4 and player.treasury < 5:
            weakest = min(player.hand, key=lambda c: c.power + c.influence)
            result = self.sacrifice_card(weakest)
            actions.append(result)
        # AI: buy card draw if hand is small and affordable
        if len(player.hand) <= 2 and player.treasury >= 4 and len(player.deck) > 0:
            result = self.buy_card()
            actions.append(result)
        # AI: discard weakest cards if hand is large (keep best 5)
        while len(player.hand) > 5 and player.discards_used < HISTORY_MAX_DISCARDS:
            weakest = min(player.hand, key=lambda c: c.power + c.influence)
            result = self.discard_card(weakest)
            actions.append(result)
        # AI: reveal opponent conspiracy if affordable and one exists
        if player.treasury >= 6 and len(opp.face_down) > 0:
            result = self.reveal_conspiracy()
            actions.append(result)
        # Sort attackers by synergy-boosted power (highest first)
        attackers = [c for c in player.board
                     if c.card_id not in player.attacks_used
                     and c.card_id not in player.just_played]
        attackers.sort(key=lambda c: player.get_card_attack_power(c), reverse=True)

        for attacker in attackers:
            if self.game_over:
                break
            # AI: buy power for top attacker if affordable and opponent has defense
            if player.treasury >= 5 and opp.has_defense() and attacker == attackers[0]:
                result = self.buy_power(attacker)
                actions.append(result)
            # If opponent has no defense, attack directly
            if not opp.has_defense():
                result = self.attack(attacker, None)
                actions.append(result)
            else:
                # Attack the weakest defender to break through
                defenders = [c for c in opp.board
                             if opp.get_card_defense_influence(c) > 0]
                if defenders:
                    weakest = min(defenders, key=lambda c: opp.get_card_defense_influence(c))
                    result = self.attack(attacker, weakest)
                    actions.append(result)

        # End turn
        self.end_turn()
        actions.append(f"{player.name} ends turn")
        return actions


def build_history_deck(pool: List[HistoryCard], deck_size: int = HISTORY_DECK_SIZE) -> List[HistoryCard]:
    """Build a balanced history deck from the card pool."""
    # Ensure a mix of card types
    by_type = {}
    for c in pool:
        by_type.setdefault(c.card_type, []).append(c)
    deck = []
    # Roughly: 50% Figures, 15% Events, 10% each of Conspiracy/Scandal/Organization/Policy
    ratios = {'Figure': 0.50, 'Event': 0.15, 'Conspiracy': 0.10, 'Scandal': 0.10, 'Organization': 0.08, 'Policy': 0.07}
    for ctype, ratio in ratios.items():
        cards = by_type.get(ctype, [])
        random.shuffle(cards)
        n = max(1, int(deck_size * ratio))
        deck.extend(cards[:n])
    # Trim or pad to exact size
    if len(deck) > deck_size:
        deck = deck[:deck_size]
    elif len(deck) < deck_size:
        remaining = [c for c in pool if c not in deck]
        random.shuffle(remaining)
        deck.extend(remaining[:deck_size - len(deck)])
    return deck


# ==============================================================================
# SECTION: GUI CLIENT (merged from TCG_GUI.py)
# ==============================================================================

# ── Constants ────────────────────────────────────────────────────────────────
FPS = 30

# Dynamic screen size — set after display init for fullscreen
SCREEN_W = 1280
SCREEN_H = 820

# Colors (R, G, B)
BG_DARK     = (18, 22, 30)
BG_PANEL    = (28, 34, 46)
BG_CARD     = (40, 48, 64)
BG_CARD_SEL = (60, 72, 100)
TEXT_WHITE  = (235, 235, 240)
TEXT_DIM    = (140, 145, 160)
TEXT_GOLD   = (255, 200, 80)
TEXT_GREEN  = (100, 220, 120)
TEXT_RED    = (230, 90, 90)
TEXT_BLUE   = (100, 160, 240)
TEXT_CYAN   = (120, 220, 220)
TEXT_MAGENTA= (220, 130, 220)

RARITY_RGB = {
    'C':  (180, 185, 195),
    'U':  (100, 200, 220),
    'R':  (255, 200, 80),
    'UR': (200, 120, 255),
    'L':  (255, 80, 80),
    'SR': (255, 230, 100),
}

RARITY_BORDER = {
    'C':  (100, 105, 120),
    'U':  (60, 160, 180),
    'R':  (200, 150, 30),
    'UR': (150, 70, 200),
    'L':  (200, 40, 40),
    'SR': (230, 180, 30),
}

CARD_TYPE_COLORS = {
    'Figure':       (100, 180, 255),
    'Event':        (255, 160, 80),
    'Conspiracy':   (220, 100, 220),
    'Scandal':      (255, 80, 80),
    'Organization': (100, 220, 120),
    'Policy':       (255, 220, 100),
}

CARD_W = 130
CARD_H = 180
CARD_GAP = 8
SMALL_CARD_W = 90
SMALL_CARD_H = 125

def compute_dynamic_card_sizes():
    """Compute card sizes that fit the current screen resolution."""
    global CARD_W, CARD_H, CARD_GAP, SMALL_CARD_W, SMALL_CARD_H
    # Base design is for 1280x820. Scale proportionally.
    scale = min(SCREEN_W / 1280, SCREEN_H / 820)
    # Hand cards (large)
    CARD_W = max(100, int(130 * scale))
    CARD_H = max(140, int(180 * scale))
    # Board cards (small)
    SMALL_CARD_W = max(70, int(90 * scale))
    SMALL_CARD_H = max(100, int(125 * scale))
    CARD_GAP = max(4, int(8 * scale))

# ── Helper Functions ─────────────────────────────────────────────────────────

def draw_text(surf, text, font, color, x, y, center=False, max_width=None):
    """Draw text on a surface. Returns the rect of the drawn text."""
    if max_width:
        words = text.split(' ')
        lines = []
        current = ''
        for w in words:
            test = (current + ' ' + w).strip()
            if font.size(test)[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = w
        if current:
            lines.append(current)
        for i, line in enumerate(lines):
            surf2 = font.render(line, True, color)
            rect = surf2.get_rect()
            if center:
                rect.centerx = x
            else:
                rect.x = x
            rect.y = y + i * (font.get_height() + 2)
            surf.blit(surf2, rect)
        return pygame.Rect(x, y, max_width, len(lines) * (font.get_height() + 2))
    else:
        surf2 = font.render(text, True, color)
        rect = surf2.get_rect()
        if center:
            rect.centerx = x
        else:
            rect.x = x
        rect.y = y
        surf.blit(surf2, rect)
        return rect

def draw_card(surf, card, x, y, font_name, font_val, font_desc, font_small,
              selected=False, hovered=False, small=False):
    """Draw a card at the given position."""
    w = SMALL_CARD_W if small else CARD_W
    h = SMALL_CARD_H if small else CARD_H

    rarity = card.rarity
    border_color = RARITY_BORDER.get(rarity, (100, 100, 100))
    bg_color = BG_CARD
    if selected:
        bg_color = BG_CARD_SEL
        border_color = (255, 255, 100)
    elif hovered:
        bg_color = (50, 60, 80)

    # Card background
    rect = pygame.Rect(x, y, w, h)
    pygame.draw.rect(surf, bg_color, rect, border_radius=6)
    pygame.draw.rect(surf, border_color, rect, width=2 if selected or hovered else 1, border_radius=6)

    # Rarity bar at top
    rarity_rgb = RARITY_RGB.get(rarity, (200, 200, 200))
    pygame.draw.rect(surf, rarity_rgb, (x, y, w, 4), border_radius=6)

    # Card type icon
    type_color = {
        'Coin': TEXT_GOLD,
        'Note': TEXT_GREEN,
        'Event': TEXT_MAGENTA,
    }.get(card.card_type, TEXT_WHITE)
    type_str = f"[{card.rarity}] {card.card_type}"
    draw_text(surf, type_str, font_small, rarity_rgb, x + 4, y + 6)

    # Card name
    name = card.name
    if len(name) > 22 and small:
        name = name[:20] + '..'
    elif len(name) > 28:
        name = name[:26] + '..'
    draw_text(surf, name, font_name, TEXT_WHITE, x + 4, y + 20, max_width=w - 8)

    # Value
    val_text = f"${card.value:.2f}"
    val_color = TEXT_GOLD if card.value >= 1 else TEXT_DIM
    draw_text(surf, val_text, font_val, val_color, x + 4, y + (38 if small else 42))

    # Composition
    draw_text(surf, card.composition, font_small, TEXT_CYAN, x + 4, y + (56 if small else 62))

    # Ability description (wrapped)
    desc = card.ability_desc
    if desc and desc != 'None':
        desc_y = y + (72 if small else 82)
        draw_text(surf, desc, font_desc, TEXT_DIM, x + 4, desc_y, max_width=w - 8)

    # Year range at bottom
    if card.year_range:
        draw_text(surf, card.year_range, font_small, TEXT_DIM, x + 4, y + h - 16)

    return rect

def draw_button(surf, x, y, w, h, text, font, color=TEXT_WHITE, bg=BG_PANEL,
                hovered=False, disabled=False):
    """Draw a clickable button. Returns the rect."""
    rect = pygame.Rect(x, y, w, h)
    actual_bg = (50, 60, 80) if hovered else bg
    if disabled:
        actual_bg = (35, 38, 48)
        color = TEXT_DIM
    pygame.draw.rect(surf, actual_bg, rect, border_radius=5)
    border_col = (100, 110, 140) if not disabled else (50, 55, 65)
    pygame.draw.rect(surf, border_col, rect, width=1, border_radius=5)
    text_surf = font.render(text, True, color)
    text_rect = text_surf.get_rect(center=rect.center)
    surf.blit(text_surf, text_rect)
    return rect

def draw_progress_bar(surf, x, y, w, h, value, target, color=TEXT_GREEN):
    """Draw a progress bar showing value/target."""
    pygame.draw.rect(surf, (30, 35, 50), (x, y, w, h), border_radius=3)
    if target > 0:
        fill = min(value / target, 1.0)
        fill_w = int(w * fill)
        if fill_w > 0:
            pygame.draw.rect(surf, color, (x, y, fill_w, h), border_radius=3)
    pygame.draw.rect(surf, (80, 90, 110), (x, y, w, h), width=1, border_radius=3)


# ── GUI Game Client ──────────────────────────────────────────────────────────

class GameGUI:
    """Main GUI controller for The Exchange TCG."""

    def __init__(self):
        pygame.init()
        # Fullscreen with dynamic resolution
        info = pygame.display.Info()
        global SCREEN_W, SCREEN_H
        SCREEN_W = info.current_w
        SCREEN_H = info.current_h
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.FULLSCREEN | pygame.SCALED)
        pygame.display.set_caption("The Exchange - Historical U.S. Currency TCG")
        self.clock = pygame.time.Clock()
        compute_dynamic_card_sizes()

        # Fonts — scaled to screen resolution
        fs = max(1.0, min(SCREEN_W / 1280, SCREEN_H / 820))
        self.font_title = pygame.font.SysFont("arial", int(28 * fs), bold=True)
        self.font_header = pygame.font.SysFont("arial", int(20 * fs), bold=True)
        self.font_body = pygame.font.SysFont("arial", int(16 * fs))
        self.font_small = pygame.font.SysFont("arial", int(13 * fs))
        self.font_tiny = pygame.font.SysFont("arial", int(11 * fs))
        self.font_card_name = pygame.font.SysFont("arial", int(13 * fs), bold=True)
        self.font_card_val = pygame.font.SysFont("arial", int(18 * fs), bold=True)
        self.font_card_desc = pygame.font.SysFont("arial", int(11 * fs))

        self.state = 'menu'  # menu, setup, playing, gameover, ai_thinking, duel_setup, duel, duel_gameover, duel_ai
        self.game: Optional[ExchangeGame] = None
        self.human: Optional[Player] = None
        self.ai: Optional[Player] = None
        self.card_pool = create_base_set()

        # Duel state
        self.duel: Optional[ExchangeDuel] = None
        self.duel_human: Optional[DuelPlayer] = None
        self.duel_ai: Optional[DuelPlayer] = None
        self.duel_selected_hand_idx: Optional[int] = None  # selected hand card for playing
        self.duel_selected_portfolio_idx: Optional[int] = None  # selected portfolio card for abilities
        self.duel_offer_mode = False  # building an offer
        self.duel_offer_offered: List[DuelCard] = []  # cards we're offering
        self.duel_offer_offered_from_hand: List[bool] = []  # parallel: True if from hand
        self.duel_offer_requested: List[DuelCard] = []  # opponent cards we want

        # UI state
        self.selected_hand_idx = None
        self.selected_purse_idx = None
        self.hovered_card = None
        self.action_log: List[str] = []
        self.log_scroll = 0
        self.message: str = ""
        self.message_timer: float = 0
        self.ai_action_display: List[str] = []
        self.ai_display_timer: float = 0
        self.challenged_this_turn = False
        self.make_change_mode = False
        self.make_change_small: List[int] = []
        self.make_change_large_idx = None

        # Menu buttons
        self.menu_buttons = []

        # History card browser state
        self.history_cards = create_history_set()
        self.browser_filter_type = None       # None = all types
        self.browser_filter_org = None        # None = all orgs
        self.browser_filter_rarity = None     # None = all rarities
        self.browser_filter_region = None     # None = all regions
        self.browser_filter_tag = None        # None = all tags
        self.browser_sort = 'id'              # 'id', 'power', 'influence', 'name'
        self.browser_search = ''
        self.browser_scroll = 0
        self.browser_scroll_target = 0
        self.browser_selected_card = None
        self.browser_show_detail = False
        self.browser_show_synergy = False     # synergy group browser mode

        # History Mode state
        self.hist_game: Optional[HistoryGame] = None
        self.hist_human: Optional[HistoryPlayer] = None
        self.hist_ai: Optional[HistoryPlayer] = None
        self.hist_selected_hand_idx: Optional[int] = None
        self.hist_selected_board_idx: Optional[int] = None  # selected attacker
        self.hist_selected_target_idx: Optional[int] = None  # selected opponent defender
        self.hist_attack_mode = False
        self.hist_scandal_target_mode = False  # selecting opponent figure for scandal
        self.hist_show_help = False  # toggleable in-game help overlay

    def run(self):
        running = True
        while running:
            dt = self.clock.tick(FPS) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.handle_click(event.pos)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 4:
                    if self.state == 'card_browser':
                        self.browser_scroll_target = max(0, self.browser_scroll_target - 60)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 5:
                    if self.state == 'card_browser':
                        self.browser_scroll_target += 60
                elif event.type == pygame.MOUSEMOTION:
                    self.handle_hover(event.pos)
                elif event.type == pygame.KEYDOWN:
                    self.handle_key(event.key)
                    # Text input for browser search
                    if self.state == 'card_browser' and not self.browser_show_detail:
                        if event.key == pygame.K_BACKSPACE:
                            self.browser_search = self.browser_search[:-1]
                        elif event.unicode and event.unicode.isprintable() and len(self.browser_search) < 30:
                            self.browser_search += event.unicode

            if self.message_timer > 0:
                self.message_timer -= dt
            if self.ai_display_timer > 0:
                self.ai_display_timer -= dt
                if self.ai_display_timer <= 0:
                    if self.state == 'duel_ai':
                        self.finish_duel_ai_turn()
                    elif self.state == 'hist_ai':
                        self.finish_hist_ai_turn()
                    else:
                        self.finish_ai_turn()

            self.render()
            pygame.display.flip()

        pygame.quit()
        sys.exit()

    # ── State Management ──────────────────────────────────────────────────────

    def start_new_game(self, target: float, max_rounds: int, difficulty: str):
        """Initialize a new game."""
        human_deck = DeckBuilder.auto_build_deck(self.card_pool, target_size=45)
        ai_deck = DeckBuilder.auto_build_deck(self.card_pool, target_size=45)
        valid, errors = DeckBuilder.validate_deck(human_deck)
        if not valid:
            while len(human_deck) < 40:
                human_deck.append(copy.deepcopy(random.choice(
                    [c for c in self.card_pool if c.rarity == 'C'])))

        self.human = Player("You", Deck(human_deck), is_ai=False)
        self.ai = Player("AI Bank", Deck(ai_deck), is_ai=True)
        self.game = ExchangeGame([self.human, self.ai], target_value=target, max_rounds=max_rounds)
        self.game.ai_difficulty = difficulty
        self.game.setup()
        self.state = 'playing'
        self.action_log = []
        self.challenged_this_turn = False
        self.selected_hand_idx = None
        self.selected_purse_idx = None
        self.log_msg(f"Game started! Target: ${target:.0f} | AI: {difficulty.capitalize()}")

    def log_msg(self, msg: str):
        self.action_log.append(msg)
        if len(self.action_log) > 50:
            self.action_log = self.action_log[-50:]

    def show_message(self, msg: str, duration: float = 2.0):
        self.message = msg
        self.message_timer = duration

    # ── Game Actions ──────────────────────────────────────────────────────────

    def play_selected_card(self):
        if self.selected_hand_idx is None:
            self.show_message("Select a card from your hand first!")
            return
        if self.selected_hand_idx >= len(self.human.hand):
            return
        card = self.human.hand[self.selected_hand_idx]
        if card.card_type == 'Event':
            result = self.game.play_event(self.human, card)
        else:
            result = self.game.play_card(self.human, card)
        self.action_log.append(result)
        self.selected_hand_idx = None
        self.check_game_over()

    def activate_selected_ability(self):
        activatable = [c for c in self.human.purse.cards
                       if AbilityResolver.can_activate(c, self.human, self.game)]
        if not activatable:
            self.show_message("No abilities available to activate!")
            return
        if self.selected_purse_idx is None or self.selected_purse_idx >= len(self.human.purse.cards):
            self.show_message("Select a card in your purse to activate!")
            return
        card = self.human.purse.cards[self.selected_purse_idx]
        if not AbilityResolver.can_activate(card, self.human, self.game):
            self.show_message("That ability cannot be activated!")
            return
        result = self.game.activate_ability(self.human, card)
        self.action_log.append(result)
        self.selected_purse_idx = None
        self.check_game_over()

    def do_challenge(self):
        if self.challenged_this_turn:
            self.show_message("Already challenged this turn!")
            return
        if self.human.challenge_cooldown > 0:
            self.show_message(f"Challenge on cooldown! Wait {self.human.challenge_cooldown} turn(s).")
            return
        result = self.game.challenge(self.human, self.ai)
        self.action_log.append(result)
        if "WON" in result or "LOST" in result:
            self.challenged_this_turn = True
        self.check_game_over()

    def do_discard(self):
        if self.selected_hand_idx is None or self.selected_hand_idx >= len(self.human.hand):
            self.show_message("Select a card from your hand to discard!")
            return
        card = self.human.hand[self.selected_hand_idx]
        self.human.discard_card(card)
        self.action_log.append(f"  Discarded {card.name}.")
        self.selected_hand_idx = None

    def do_make_change_start(self):
        if not self.human.purse.cards:
            self.show_message("No cards in purse to break!")
            return
        if not self.human.hand:
            self.show_message("No cards in hand to make change with!")
            return
        self.make_change_mode = True
        self.make_change_small = []
        self.make_change_large_idx = None
        self.show_message("Select a large card from your purse, then small cards from hand.")

    def do_make_change_confirm(self):
        if self.make_change_large_idx is None:
            self.show_message("Select a large card from your purse first!")
            return
        if not self.make_change_small:
            self.show_message("Select small cards from your hand!")
            return
        large = self.human.purse.cards[self.make_change_large_idx]
        small_cards = [self.human.hand[i] for i in self.make_change_small if i < len(self.human.hand)]
        result = self.game.make_change(self.human, large, small_cards)
        self.action_log.append(result)
        self.make_change_mode = False
        self.make_change_large_idx = None
        self.make_change_small = []
        self.check_game_over()

    def do_make_change_cancel(self):
        self.make_change_mode = False
        self.make_change_large_idx = None
        self.make_change_small = []

    def end_turn(self):
        self.game.end_turn(self.human)
        if self.check_game_over():
            return
        self.game.next_turn()
        self.challenged_this_turn = False
        self.selected_hand_idx = None
        self.selected_purse_idx = None
        # Start AI turn
        self.state = 'ai_thinking'
        ai_actions = self.game.ai_take_turn(self.ai)
        self.ai_action_display = ai_actions
        self.ai_display_timer = 2.5
        self.action_log.extend(ai_actions)

    def finish_ai_turn(self):
        if self.check_game_over():
            return
        self.game.next_turn()
        self.state = 'playing'
        self.ai_display_timer = 0

    def check_game_over(self) -> bool:
        if self.game.check_win_conditions():
            self.state = 'gameover'
            return True
        return False

    def do_save(self):
        name = f"gui_save_{len(list_saves())+1}"
        path = save_game(self.game, name)
        self.show_message(f"Game saved: {os.path.basename(path)}", 2.0)

    # ── Input Handling ────────────────────────────────────────────────────────

    def handle_key(self, key):
        if key == pygame.K_ESCAPE:
            if self.browser_show_detail:
                self.browser_show_detail = False
            elif self.make_change_mode:
                self.do_make_change_cancel()
            elif self.state == 'gameover':
                self.state = 'menu'
            elif self.state == 'playing':
                self.state = 'menu'
                self.show_message("Returned to menu (game preserved in memory)")
            elif self.state == 'card_browser':
                self.state = 'menu'
            elif self.state in ('hist_playing', 'hist_gameover', 'hist_setup'):
                self.state = 'menu'
            elif self.hist_attack_mode:
                self.hist_attack_mode = False
                self.hist_selected_board_idx = None
                self.hist_selected_target_idx = None
            elif self.hist_scandal_target_mode:
                self.hist_scandal_target_mode = False
                self.hist_selected_target_idx = None
        elif key == pygame.K_h and self.state == 'hist_playing':
            self.hist_show_help = not self.hist_show_help

    def handle_hover(self, pos):
        self.hovered_card = None
        # Will be set in render based on card rects

    def handle_click(self, pos):
        mx, my = pos

        if self.state == 'menu':
            self.handle_menu_click(mx, my)
        elif self.state == 'setup':
            self.handle_setup_click(mx, my)
        elif self.state == 'difficulty':
            self.handle_menu_click(mx, my)
        elif self.state == 'playing':
            self.handle_playing_click(mx, my)
        elif self.state == 'gameover':
            self.handle_gameover_click(mx, my)
        elif self.state == 'duel_setup':
            self.handle_menu_click(mx, my)
        elif self.state == 'duel':
            self.handle_duel_click(mx, my)
        elif self.state == 'duel_gameover':
            self.handle_menu_click(mx, my)
        elif self.state == 'duel_ai':
            pass  # wait for AI to finish
        elif self.state == 'card_browser':
            self.handle_browser_click(mx, my)
        elif self.state == 'hist_setup':
            self.handle_menu_click(mx, my)
        elif self.state == 'hist_playing':
            self.handle_hist_click(mx, my)
        elif self.state == 'hist_gameover':
            self.handle_gameover_click(mx, my)
        elif self.state == 'hist_ai':
            pass  # wait for AI to finish

    def handle_menu_click(self, mx, my):
        for btn in self.menu_buttons:
            if btn['rect'].collidepoint(mx, my):
                btn['action']()
                return

    def handle_setup_click(self, mx, my):
        # Setup buttons are stored in self.menu_buttons during setup
        for btn in self.menu_buttons:
            if btn['rect'].collidepoint(mx, my):
                btn['action']()
                return

    def handle_playing_click(self, mx, my):
        # Check action buttons (right panel)
        if self._handle_action_buttons(mx, my):
            return

        # Check hand cards
        hand_rects = self._get_hand_rects()
        for i, rect in enumerate(hand_rects):
            if rect.collidepoint(mx, my):
                if self.make_change_mode:
                    if i in self.make_change_small:
                        self.make_change_small.remove(i)
                    else:
                        self.make_change_small.append(i)
                else:
                    self.selected_hand_idx = i
                    self.selected_purse_idx = None
                return

        # Check purse cards
        purse_rects = self._get_purse_rects()
        for i, rect in enumerate(purse_rects):
            if rect.collidepoint(mx, my):
                if self.make_change_mode:
                    self.make_change_large_idx = i
                else:
                    self.selected_purse_idx = i
                    self.selected_hand_idx = None
                return

    def handle_gameover_click(self, mx, my):
        for btn in self.menu_buttons:
            if btn['rect'].collidepoint(mx, my):
                btn['action']()
                return

    def _handle_action_buttons(self, mx, my) -> bool:
        if not hasattr(self, '_action_button_rects'):
            return False
        for name, rect in self._action_button_rects.items():
            if rect.collidepoint(mx, my):
                if name == 'play':
                    self.play_selected_card()
                elif name == 'change':
                    if self.make_change_mode:
                        self.do_make_change_confirm()
                    else:
                        self.do_make_change_start()
                elif name == 'activate':
                    self.activate_selected_ability()
                elif name == 'challenge':
                    self.do_challenge()
                elif name == 'discard':
                    self.do_discard()
                elif name == 'save':
                    self.do_save()
                elif name == 'end':
                    self.end_turn()
                elif name == 'cancel_change':
                    self.do_make_change_cancel()
                return True
        return False

    def _get_hand_rects(self) -> List[pygame.Rect]:
        rects = []
        if not self.human:
            return rects
        y = SCREEN_H - CARD_H - 10
        total_w = len(self.human.hand) * (CARD_W + CARD_GAP) - CARD_GAP
        start_x = max(20, (SCREEN_W - 300 - total_w) // 2)
        for i in range(len(self.human.hand)):
            rects.append(pygame.Rect(start_x + i * (CARD_W + CARD_GAP), y, CARD_W, CARD_H))
        return rects

    def _get_purse_rects(self) -> List[pygame.Rect]:
        rects = []
        if not self.human:
            return rects
        y = SCREEN_H - CARD_H - SMALL_CARD_H - 30
        cards = self.human.purse.cards
        total_w = len(cards) * (SMALL_CARD_W + CARD_GAP) - CARD_GAP
        start_x = max(20, (SCREEN_W - 300 - total_w) // 2)
        for i in range(len(cards)):
            rects.append(pygame.Rect(start_x + i * (SMALL_CARD_W + CARD_GAP), y, SMALL_CARD_W, SMALL_CARD_H))
        return rects

    def _get_ai_purse_rects(self) -> List[pygame.Rect]:
        rects = []
        if not self.ai:
            return rects
        y = 60
        cards = self.ai.purse.cards
        total_w = len(cards) * (SMALL_CARD_W + CARD_GAP) - CARD_GAP
        start_x = max(20, (SCREEN_W - 300 - total_w) // 2)
        for i in range(len(cards)):
            rects.append(pygame.Rect(start_x + i * (SMALL_CARD_W + CARD_GAP), y, SMALL_CARD_W, SMALL_CARD_H))
        return rects

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render(self):
        self.screen.fill(BG_DARK)

        if self.state == 'menu':
            self.render_menu()
        elif self.state == 'setup':
            self.render_setup()
        elif self.state == 'difficulty':
            self.render_difficulty()
        elif self.state in ('playing', 'ai_thinking'):
            self.render_game()
        elif self.state == 'gameover':
            self.render_gameover()
        elif self.state == 'duel_setup':
            self.render_duel_setup()
        elif self.state in ('duel', 'duel_ai'):
            self.render_duel()
        elif self.state == 'duel_gameover':
            self.render_duel_gameover()
        elif self.state == 'card_browser':
            self.render_card_browser()
        elif self.state == 'hist_setup':
            self.render_hist_setup()
        elif self.state in ('hist_playing', 'hist_ai'):
            self.render_hist_game()
        elif self.state == 'hist_gameover':
            self.render_hist_gameover()

        # Message overlay
        if self.message_timer > 0 and self.message:
            alpha = min(255, int(self.message_timer * 200))
            msg_surf = self.font_header.render(self.message, True, TEXT_GOLD)
            msg_rect = msg_surf.get_rect(center=(SCREEN_W // 2, 30))
            bg_rect = msg_rect.inflate(20, 10)
            s = pygame.Surface(bg_rect.size, pygame.SRCALPHA)
            s.fill((0, 0, 0, min(180, alpha)))
            self.screen.blit(s, bg_rect)
            self.screen.blit(msg_surf, msg_rect)

    def render_menu(self):
        # Title
        draw_text(self.screen, "THE EXCHANGE", self.font_title, TEXT_GOLD,
                  SCREEN_W // 2, 80, center=True)
        draw_text(self.screen, "Historical U.S. Currency TCG", self.font_header, TEXT_CYAN,
                  SCREEN_W // 2, 120, center=True)
        draw_text(self.screen, f"Card Database: {len(self.card_pool)} unique cards",
                  self.font_body, TEXT_DIM, SCREEN_W // 2, 155, center=True)

        # Buttons
        self.menu_buttons = []
        btn_w, btn_h = 300, 45
        btn_x = (SCREEN_W - btn_w) // 2
        btn_y_start = 200
        gap = 52

        buttons = [
            ("New Game (Human vs AI)", lambda: self.goto_setup()),
            ("History Mode (Political Arena)", lambda: self.goto_hist_setup()),
            ("Exchange Duel (Trade Battle)", lambda: self.goto_duel_setup()),
            ("Card Collection (History)", lambda: self.goto_card_browser()),
            ("Load Game", lambda: self.goto_load()),
            ("AI Simulation (Quick)", lambda: self.run_quick_sim()),
            ("Quit", lambda: pygame.event.post(pygame.event.Event(pygame.QUIT))),
        ]

        mx, my = pygame.mouse.get_pos()
        for i, (label, action) in enumerate(buttons):
            y = btn_y_start + i * gap
            hovered = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my)
            rect = draw_button(self.screen, btn_x, y, btn_w, btn_h, label,
                               self.font_header, hovered=hovered)
            self.menu_buttons.append({'rect': rect, 'action': action})

    def render_setup(self):
        draw_text(self.screen, "NEW GAME SETUP", self.font_title, TEXT_GOLD,
                  SCREEN_W // 2, 40, center=True)

        # Game length
        draw_text(self.screen, "Game Length:", self.font_header, TEXT_YELLOW if False else (255, 200, 80),
                  SCREEN_W // 2 - 200, 110, center=True)

        self.menu_buttons = []
        mx, my = pygame.mouse.get_pos()
        btn_w, btn_h = 260, 40

        lengths = [
            ("Short ($500, 20 rounds)", 500, 20),
            ("Medium ($1000, 30 rounds)", 1000, 30),
            ("Long ($5000, 40 rounds)", 5000, 40),
            ("Epic ($10000, 50 rounds)", 10000, 50),
        ]

        for i, (label, target, rounds) in enumerate(lengths):
            y = 140 + i * 50
            hovered = pygame.Rect(SCREEN_W // 2 - btn_w // 2, y, btn_w, btn_h).collidepoint(mx, my)
            rect = draw_button(self.screen, SCREEN_W // 2 - btn_w // 2, y, btn_w, btn_h, label,
                               self.font_body, hovered=hovered)
            self.menu_buttons.append({
                'rect': rect,
                'action': lambda t=target, r=rounds: self.select_difficulty(t, r)
            })

        # Back button
        hovered = pygame.Rect(SCREEN_W // 2 - btn_w // 2, SCREEN_H - 80, btn_w, btn_h).collidepoint(mx, my)
        rect = draw_button(self.screen, SCREEN_W // 2 - btn_w // 2, SCREEN_H - 80, btn_w, btn_h,
                           "Back to Menu", self.font_body, hovered=hovered)
        self.menu_buttons.append({'rect': rect, 'action': lambda: self.goto_menu()})

    def select_difficulty(self, target, max_rounds):
        self._pending_target = target
        self._pending_rounds = max_rounds
        self.state = 'difficulty'

    # Difficulty selection screen
    def render_difficulty(self):
        draw_text(self.screen, "SELECT AI DIFFICULTY", self.font_title, TEXT_GOLD,
                  SCREEN_W // 2, 40, center=True)

        self.menu_buttons = []
        mx, my = pygame.mouse.get_pos()
        btn_w, btn_h = 260, 40

        diffs = [
            ("Easy (random play)", 'easy'),
            ("Medium (basic strategy)", 'medium'),
            ("Hard (optimal, aggressive)", 'hard'),
        ]

        for i, (label, diff) in enumerate(diffs):
            y = 140 + i * 50
            hovered = pygame.Rect(SCREEN_W // 2 - btn_w // 2, y, btn_w, btn_h).collidepoint(mx, my)
            rect = draw_button(self.screen, SCREEN_W // 2 - btn_w // 2, y, btn_w, btn_h, label,
                               self.font_body, hovered=hovered)
            self.menu_buttons.append({
                'rect': rect,
                'action': lambda d=diff: self.start_new_game(self._pending_target, self._pending_rounds, d)
            })

        hovered = pygame.Rect(SCREEN_W // 2 - btn_w // 2, SCREEN_H - 80, btn_w, btn_h).collidepoint(mx, my)
        rect = draw_button(self.screen, SCREEN_W // 2 - btn_w // 2, SCREEN_H - 80, btn_w, btn_h,
                           "Back", self.font_body, hovered=hovered)
        self.menu_buttons.append({'rect': rect, 'action': lambda: self.goto_setup()})

    def goto_menu(self):
        self.state = 'menu'

    def goto_setup(self):
        self.state = 'setup'

    def goto_load(self):
        saves = list_saves()
        if not saves:
            self.show_message("No save files found!", 2.0)
            return
        # Load most recent save
        saves.sort(reverse=True)
        game = load_game(saves[0].replace('.json', ''))
        if game:
            self.game = game
            self.human = game.players[0]
            self.ai = game.players[1]
            self.state = 'playing'
            self.action_log = [f"Loaded game from {saves[0]}"]
            self.challenged_this_turn = False

    def run_quick_sim(self):
        self.show_message("Running 5 AI simulations...", 3.0)
        from TCG import run_simulation
        results = run_simulation(num_games=5, target=1000, verbose=False)
        p1 = results['p1_wins']
        p2 = results['p2_wins']
        avg_r = sum(results['rounds']) / len(results['rounds']) if results['rounds'] else 0
        avg_p = sum(results['avg_purse']) / len(results['avg_purse']) if results['avg_purse'] else 0
        self.show_message(f"Alpha: {p1} wins, Beta: {p2} wins | Avg {avg_r:.0f} rounds, ${avg_p:.0f} purse", 5.0)

    def render_game(self):
        if not self.game or not self.human or not self.ai:
            return

        # ── Top bar: AI info ──
        ai_val = self.game.compute_purse_value(self.ai)
        my_val = self.game.compute_purse_value(self.human)

        # AI section background
        pygame.draw.rect(self.screen, BG_PANEL, (0, 0, SCREEN_W, 50))
        draw_text(self.screen, f"{self.ai.name}", self.font_header, TEXT_RED, 20, 15)
        draw_text(self.screen, f"Purse: ${ai_val:.2f} ({len(self.ai.purse.cards)} cards)",
                  self.font_body, TEXT_WHITE, 180, 18)
        draw_text(self.screen, f"Hand: {len(self.ai.hand)} | Deck: {self.ai.deck.remaining()}",
                  self.font_body, TEXT_DIM, 420, 18)
        draw_text(self.screen, f"Round {self.game.current_round}/{self.game.max_rounds}",
                  self.font_header, TEXT_CYAN, SCREEN_W - 300, 15)
        draw_text(self.screen, f"Target: ${self.game.target_value:.0f}",
                  self.font_body, TEXT_GOLD, SCREEN_W - 160, 18)

        # AI purse cards (small, top)
        ai_rects = self._get_ai_purse_rects()
        for i, rect in enumerate(ai_rects):
            card = self.ai.purse.cards[i]
            draw_card(self.screen, card, rect.x, rect.y, self.font_card_name,
                      self.font_card_val, self.font_card_desc, self.font_tiny, small=True)

        # ── Active events ──
        y_events = 195
        if self.game.active_events:
            events_str = " | ".join(f"{n} ({r}r)" for n, r in self.game.active_events)
            draw_text(self.screen, f"Active Events: {events_str}", self.font_body, TEXT_MAGENTA, 20, y_events)

        # ── Middle: Action log ──
        log_x = 20
        log_y = 220
        log_w = SCREEN_W - 300
        log_h = 100
        pygame.draw.rect(self.screen, BG_PANEL, (log_x, log_y, log_w, log_h), border_radius=5)
        pygame.draw.rect(self.screen, (60, 70, 90), (log_x, log_y, log_w, log_h), width=1, border_radius=5)
        draw_text(self.screen, "Action Log", self.font_small, TEXT_DIM, log_x + 8, log_y + 4)
        recent = self.action_log[-4:]
        for i, line in enumerate(recent):
            # Strip ANSI codes for display
            clean = line.replace('\033[0m', '').replace('\033[1m', '')
            for code in ['\033[91m', '\033[92m', '\033[93m', '\033[94m', '\033[95m', '\033[96m', '\033[97m', '\033[90m', '\033[2m']:
                clean = clean.replace(code, '')
            draw_text(self.screen, clean, self.font_small, TEXT_WHITE, log_x + 8, log_y + 22 + i * 18, max_width=log_w - 16)

        # ── Your purse section ──
        purse_y = SCREEN_H - CARD_H - SMALL_CARD_H - 50
        draw_text(self.screen, f"Your Purse: ${my_val:.2f} ({len(self.human.purse.cards)} cards)",
                  self.font_header, TEXT_CYAN, 20, purse_y - 20)
        draw_progress_bar(self.screen, 300, purse_y - 16, 200, 14, my_val, self.game.target_value, TEXT_GREEN)

        purse_rects = self._get_purse_rects()
        for i, rect in enumerate(purse_rects):
            card = self.human.purse.cards[i]
            selected = (i == self.selected_purse_idx) or (self.make_change_mode and i == self.make_change_large_idx)
            draw_card(self.screen, card, rect.x, rect.y, self.font_card_name,
                      self.font_card_val, self.font_card_desc, self.font_tiny,
                      selected=selected, small=True)

        # ── Hand section ──
        hand_y = SCREEN_H - CARD_H - 5
        draw_text(self.screen, f"Hand ({len(self.human.hand)})", self.font_header, TEXT_WHITE, 20, hand_y - 22)
        draw_text(self.screen, f"Deck: {self.human.deck.remaining()}", self.font_body, TEXT_DIM, 150, hand_y - 18)

        hand_rects = self._get_hand_rects()
        for i, rect in enumerate(hand_rects):
            card = self.human.hand[i]
            selected = (i == self.selected_hand_idx)
            if self.make_change_mode and i in self.make_change_small:
                selected = True
            draw_card(self.screen, card, rect.x, rect.y, self.font_card_name,
                      self.font_card_val, self.font_card_desc, self.font_tiny,
                      selected=selected)

        # ── Right panel: Action buttons ──
        self._render_action_panel()

        # ── AI thinking overlay ──
        if self.state == 'ai_thinking':
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 80))
            self.screen.blit(overlay, (0, 0))
            draw_text(self.screen, "AI is thinking...", self.font_title, TEXT_RED,
                      SCREEN_W // 2, SCREEN_H // 2 - 40, center=True)
            # Show AI actions
            for i, action in enumerate(self.ai_action_display[-4:]):
                clean = action.replace('\033[0m', '').replace('\033[1m', '')
                for code in ['\033[91m', '\033[92m', '\033[93m', '\033[94m', '\033[95m', '\033[96m', '\033[97m', '\033[90m', '\033[2m']:
                    clean = clean.replace(code, '')
                draw_text(self.screen, clean, self.font_body, TEXT_WHITE,
                          SCREEN_W // 2, SCREEN_H // 2 + i * 25, center=True, max_width=600)

    def _render_action_panel(self):
        panel_x = SCREEN_W - 280
        panel_y = 55
        panel_w = 260
        panel_h = SCREEN_H - 65

        pygame.draw.rect(self.screen, BG_PANEL, (panel_x, panel_y, panel_w, panel_h), border_radius=5)
        pygame.draw.rect(self.screen, (60, 70, 90), (panel_x, panel_y, panel_w, panel_h), width=1, border_radius=5)

        draw_text(self.screen, "ACTIONS", self.font_header, TEXT_GOLD, panel_x + 10, panel_y + 8)

        mx, my = pygame.mouse.get_pos()
        self._action_button_rects = {}

        btn_w = panel_w - 20
        btn_x = panel_x + 10
        btn_h = 36
        gap = 6
        y = panel_y + 38

        buttons = []
        if self.make_change_mode:
            buttons = [
                ("Confirm Make Change", 'change', False),
                ("Cancel", 'cancel_change', False),
            ]
        else:
            can_play = self.selected_hand_idx is not None and self.selected_hand_idx < len(self.human.hand)
            can_activate = self.selected_purse_idx is not None and self.selected_purse_idx < len(self.human.purse.cards)
            buttons = [
                ("Play Card", 'play', not can_play),
                ("Make Change", 'change', False),
                ("Activate Ability", 'activate', not can_activate),
                ("Challenge (Demand Exchange)", 'challenge', self.challenged_this_turn or self.human.challenge_cooldown > 0),
                ("Discard Card", 'discard', self.selected_hand_idx is None),
                ("Save Game", 'save', False),
                ("End Turn", 'end', False),
            ]

        for label, name, disabled in buttons:
            hovered = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my) and not disabled
            rect = draw_button(self.screen, btn_x, y, btn_w, btn_h, label,
                               self.font_body, hovered=hovered, disabled=disabled)
            self._action_button_rects[name] = rect
            y += btn_h + gap

        # Status info
        y += 10
        draw_text(self.screen, f"Your Purse: ${self.game.compute_purse_value(self.human):.2f}",
                  self.font_body, TEXT_GREEN, panel_x + 10, y)
        y += 22
        draw_text(self.screen, f"AI Purse: ${self.game.compute_purse_value(self.ai):.2f}",
                  self.font_body, TEXT_RED, panel_x + 10, y)
        y += 22
        draw_text(self.screen, f"Target: ${self.game.target_value:.0f}",
                  self.font_body, TEXT_GOLD, panel_x + 10, y)
        y += 28

        # Progress bars
        draw_text(self.screen, "Your Progress:", self.font_small, TEXT_DIM, panel_x + 10, y)
        y += 16
        my_v = self.game.compute_purse_value(self.human)
        draw_progress_bar(self.screen, panel_x + 10, y, btn_w, 12, my_v, self.game.target_value, TEXT_GREEN)
        y += 20
        draw_text(self.screen, "AI Progress:", self.font_small, TEXT_DIM, panel_x + 10, y)
        y += 16
        ai_v = self.game.compute_purse_value(self.ai)
        draw_progress_bar(self.screen, panel_x + 10, y, btn_w, 12, ai_v, self.game.target_value, TEXT_RED)
        y += 24

        # Cooldown / status
        if self.human.challenge_cooldown > 0:
            draw_text(self.screen, f"Challenge cooldown: {self.human.challenge_cooldown}",
                      self.font_small, TEXT_RED, panel_x + 10, y)
            y += 16
        if self.human.immune:
            draw_text(self.screen, "IMMUNE to challenges!", self.font_small, TEXT_GREEN, panel_x + 10, y)
            y += 16
        if self.ai.immune:
            draw_text(self.screen, "AI is IMMUNE!", self.font_small, TEXT_RED, panel_x + 10, y)
            y += 16

        # Selected card info
        y += 10
        if self.selected_hand_idx is not None and self.selected_hand_idx < len(self.human.hand):
            card = self.human.hand[self.selected_hand_idx]
            draw_text(self.screen, "Selected (Hand):", self.font_small, TEXT_CYAN, panel_x + 10, y)
            y += 16
            draw_text(self.screen, card.name, self.font_small, TEXT_WHITE, panel_x + 10, y, max_width=btn_w)
            y += 16
            draw_text(self.screen, f"${card.value:.2f} | {card.ability_desc}", self.font_tiny, TEXT_DIM, panel_x + 10, y, max_width=btn_w)
        elif self.selected_purse_idx is not None and self.selected_purse_idx < len(self.human.purse.cards):
            card = self.human.purse.cards[self.selected_purse_idx]
            draw_text(self.screen, "Selected (Purse):", self.font_small, TEXT_CYAN, panel_x + 10, y)
            y += 16
            draw_text(self.screen, card.name, self.font_small, TEXT_WHITE, panel_x + 10, y, max_width=btn_w)
            y += 16
            can_act = AbilityResolver.can_activate(card, self.human, self.game)
            act_color = TEXT_GREEN if can_act else TEXT_DIM
            draw_text(self.screen, f"${card.value:.2f} | {card.ability_desc}", self.font_tiny, TEXT_DIM, panel_x + 10, y, max_width=btn_w)
            y += 16
            draw_text(self.screen, f"Activatable: {'Yes' if can_act else 'No/Used'}",
                      self.font_tiny, act_color, panel_x + 10, y)

    def render_gameover(self):
        if not self.game:
            return

        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))

        winner = self.game.winner
        if winner == self.human:
            draw_text(self.screen, "YOU WIN!", self.font_title, TEXT_GREEN,
                      SCREEN_W // 2, 150, center=True)
        else:
            draw_text(self.screen, f"{winner.name} WINS!", self.font_title, TEXT_RED,
                      SCREEN_W // 2, 150, center=True)

        # Stats
        y = 210
        draw_text(self.screen, f"Rounds Played: {self.game.current_round}",
                  self.font_header, TEXT_WHITE, SCREEN_W // 2, y, center=True)
        y += 35
        for p in self.game.players:
            val = self.game.compute_purse_value(p)
            color = TEXT_GREEN if p == winner else TEXT_DIM
            draw_text(self.screen, f"{p.name}: ${val:.2f} ({len(p.purse.cards)} cards)",
                      self.font_body, color, SCREEN_W // 2, y, center=True)
            y += 25

        # Winner top cards
        y += 20
        draw_text(self.screen, "Winner's Top Cards:", self.font_header, TEXT_GOLD,
                  SCREEN_W // 2, y, center=True)
        y += 30
        top = sorted(winner.purse.cards, key=lambda c: c.value, reverse=True)[:3]
        for card in top:
            draw_text(self.screen, f"[{card.rarity}] {card.name} - ${card.value:.2f}",
                      self.font_body, RARITY_RGB.get(card.rarity, TEXT_WHITE),
                      SCREEN_W // 2, y, center=True)
            y += 22

        # Buttons
        self.menu_buttons = []
        mx, my = pygame.mouse.get_pos()
        btn_w, btn_h = 200, 45
        btns = [
            ("Play Again", lambda: self.goto_setup()),
            ("Main Menu", lambda: self.goto_menu()),
            ("Quit", lambda: pygame.event.post(pygame.event.Event(pygame.QUIT))),
        ]
        for i, (label, action) in enumerate(btns):
            x = SCREEN_W // 2 - btn_w // 2
            by = y + 30 + i * 55
            hovered = pygame.Rect(x, by, btn_w, btn_h).collidepoint(mx, my)
            rect = draw_button(self.screen, x, by, btn_w, btn_h, label,
                               self.font_header, hovered=hovered)
            self.menu_buttons.append({'rect': rect, 'action': action})

    # ── History Mode (Political Arena) ─────────────────────────────────────────

    def goto_hist_setup(self):
        self.state = 'hist_setup'

    def render_hist_setup(self):
        draw_text(self.screen, "POLITICAL ARENA", self.font_title, TEXT_GOLD,
                  SCREEN_W // 2, 60, center=True)
        draw_text(self.screen, "History Card Combat — Figures, Events, Conspiracies & Scandals",
                  self.font_header, TEXT_CYAN, SCREEN_W // 2, 100, center=True)

        draw_text(self.screen, "Select Difficulty:", self.font_header, (255, 200, 80),
                  SCREEN_W // 2, 160, center=True)

        self.menu_buttons = []
        mx, my = pygame.mouse.get_pos()
        btn_w, btn_h = 280, 45

        diffs = [
            ("Easy (30 life, 30 rounds)", 'easy', 30),
            ("Medium (30 life, 25 rounds)", 'medium', 25),
            ("Hard (30 life, 20 rounds)", 'hard', 20),
        ]
        for i, (label, diff, rounds) in enumerate(diffs):
            y = 200 + i * 55
            hovered = pygame.Rect(SCREEN_W // 2 - btn_w // 2, y, btn_w, btn_h).collidepoint(mx, my)
            rect = draw_button(self.screen, SCREEN_W // 2 - btn_w // 2, y, btn_w, btn_h, label,
                               self.font_body, hovered=hovered)
            self.menu_buttons.append({
                'rect': rect,
                'action': lambda d=diff, r=rounds: self.start_hist_game(d, r)
            })

        hovered = pygame.Rect(SCREEN_W // 2 - btn_w // 2, SCREEN_H - 80, btn_w, btn_h).collidepoint(mx, my)
        rect = draw_button(self.screen, SCREEN_W // 2 - btn_w // 2, SCREEN_H - 80, btn_w, btn_h,
                           "Back to Menu", self.font_body, hovered=hovered)
        self.menu_buttons.append({'rect': rect, 'action': lambda: self.goto_menu()})

        # Rules summary
        y = 380
        rules = [
            "POLITICAL ARENA — GRIND. STACK. DOMINATE.",
            "",
            "Make money. Live it up. Screw everyone else.",
            "Build your influence empire through history's most ruthless players.",
            "",
            "HOW IT WORKS:",
            "1. Each player has 30 life (influence) and a deck of 30 history cards",
            "2. Play Figures to your board (max 7), establish Organizations, enact Policies",
            "3. Events deal damage to opponent and heal you",
            "4. Conspiracies are face-down traps that counter direct attacks",
            "5. Scandals reduce an opponent figure's power and influence",
            "6. Attack phase: Figures attack with Power vs opponent's Influence (defense)",
            "7. If no defenders, attack opponent directly for damage",
            "8. Organization bonus: +1 PWR / +1 INF to same-org cards",
            "9. Policy bonus: Draw 2 cards per turn instead of 1",
            "10. SYNERGY BONUS: Cards with matching tags boost each other!",
            "    e.g. CIA + FBI + NSA = Intel Network (+PWR +INF)",
            "    e.g. Rothschild + Rockefeller + Banker = Old Money (+INF)",
            "11. TREASURY: Playing economic cards earns money ($)",
            "    Spend $5: +2 PWR to a figure for one turn",
            "    Spend $8: Heal 3 life. Grind. Stack. Dominate.",
            "    Sacrifice a hand card: +$3 to treasury",
            "    Spend $4: Draw a card from your deck",
            "    Spend $6: Reveal & neutralize an opponent conspiracy",
            "12. DISCARD: Up to 3 cards per turn — select a hand card, click Discard, draw a replacement",
            "13. First to reduce opponent to 0 life wins!",
            "",
            "Press H during the game for an in-depth help overlay!",
        ]
        for i, line in enumerate(rules):
            color = TEXT_GOLD if i == 0 else (TEXT_DIM if line == "" else TEXT_WHITE)
            draw_text(self.screen, line, self.font_small, color, SCREEN_W // 2 - 280, y + i * 20)

    def start_hist_game(self, difficulty: str, max_rounds: int):
        pool = self.history_cards
        deck1 = build_history_deck(pool, HISTORY_DECK_SIZE)
        deck2 = build_history_deck(pool, HISTORY_DECK_SIZE)
        self.hist_human = HistoryPlayer("You", deck1, is_ai=False)
        self.hist_ai = HistoryPlayer("AI Politician", deck2, is_ai=True)
        self.hist_game = HistoryGame(self.hist_human, self.hist_ai, max_rounds=max_rounds)
        self.hist_game.ai_difficulty = difficulty
        self.hist_game.setup()
        self.hist_game.start_turn()
        self.state = 'hist_playing'
        self.action_log = list(self.hist_game.log)
        self.hist_selected_hand_idx = None
        self.hist_selected_board_idx = None
        self.hist_selected_target_idx = None
        self.hist_attack_mode = False
        self.hist_scandal_target_mode = False
        self.hist_show_help = False
        self.show_message(f"Political Arena started! {difficulty} mode", 3.0)

    def _draw_hist_card(self, card: HistoryCard, x, y, selected=False, small=True,
                        show_stats=True, can_attack=False, exhausted=False, player=None):
        w = SMALL_CARD_W if small else CARD_W
        h = SMALL_CARD_H if small else CARD_H
        rect = pygame.Rect(x, y, w, h)

        type_color = CARD_TYPE_COLORS.get(card.card_type, (150, 150, 150))
        border_color = RARITY_BORDER.get(card.rarity, (100, 100, 100))
        bg = BG_CARD
        if selected:
            bg = BG_CARD_SEL
            border_color = (255, 255, 100)
        if exhausted:
            bg = (25, 28, 35)
            border_color = (60, 65, 75)

        pygame.draw.rect(self.screen, bg, rect, border_radius=6)
        pygame.draw.rect(self.screen, border_color, rect, width=2, border_radius=6)
        pygame.draw.rect(self.screen, type_color, (x, y, w, 4), border_radius=6)

        rarity_rgb = RARITY_RGB.get(card.rarity, (200, 200, 200))
        draw_text(self.screen, f"[{card.rarity}]", self.font_tiny, rarity_rgb, x + 3, y + 6)
        draw_text(self.screen, card.card_type, self.font_tiny, type_color, x + 3, y + 18)

        name = card.name
        max_len = 18 if small else 24
        if len(name) > max_len:
            name = name[:16 if small else 22] + '..'
        draw_text(self.screen, name, self.font_card_name, TEXT_WHITE, x + 3, y + 32, max_width=w - 6)
        draw_text(self.screen, card.year, self.font_tiny, TEXT_DIM, x + 3, y + 48)

        # Show effect text on large cards
        if not small and card.effect_desc and card.effect_desc != 'None':
            draw_text(self.screen, card.effect_desc, self.font_tiny, (180, 190, 210),
                      x + 3, y + 62, max_width=w - 6)

        # Show tags on large cards
        if not small and card.tags:
            tag_str = ' '.join(f"#{t}" for t in list(card.tags)[:3])
            draw_text(self.screen, tag_str, self.font_tiny, (80, 120, 160),
                      x + 3, y + h - 42, max_width=w - 6)

        if show_stats:
            stat_y = y + h - 28
            base_pwr = card.power
            base_inf = card.influence
            syn_pwr = 0
            syn_inf = 0
            if player and card in player.board:
                syn_pwr = player.get_synergy_power_bonus(card)
                syn_inf = player.get_synergy_influence_bonus(card)
                org_pwr = player.get_org_power_bonus(card)
                org_inf = player.get_org_influence_bonus(card)
                base_pwr = player.get_effective_power(card) + org_pwr
                base_inf = player.get_effective_influence(card) + org_inf

            pwr_color = TEXT_RED if not exhausted else TEXT_DIM
            inf_color = TEXT_CYAN if not exhausted else TEXT_DIM
            pwr_str = f"PWR {base_pwr}"
            inf_str = f"INF {base_inf}"
            if syn_pwr > 0:
                pwr_str += f" +{syn_pwr}"
                pwr_color = (255, 180, 80) if not exhausted else TEXT_DIM
            if syn_inf > 0:
                inf_str += f" +{syn_inf}"
                inf_color = (100, 255, 150) if not exhausted else TEXT_DIM
            elif syn_inf < 0:
                inf_str += f" {syn_inf}"
                inf_color = (255, 100, 100) if not exhausted else TEXT_DIM

            draw_text(self.screen, pwr_str, self.font_tiny, pwr_color, x + 3, stat_y)
            draw_text(self.screen, inf_str, self.font_tiny, inf_color, x + 45, stat_y)

            if card.organization != 'None':
                draw_text(self.screen, card.organization[:12], self.font_tiny, TEXT_GREEN, x + 3, stat_y + 12)

            if can_attack and not exhausted:
                pygame.draw.rect(self.screen, (200, 50, 50), (x + w - 8, y + h - 8, 6, 6))

        return rect

    def _hist_hand_rects(self) -> List[pygame.Rect]:
        rects = []
        if not self.hist_human:
            return rects
        y = SCREEN_H - CARD_H - 10
        total_w = len(self.hist_human.hand) * (CARD_W + CARD_GAP) - CARD_GAP
        start_x = max(20, (SCREEN_W - 280 - total_w) // 2)
        for i in range(len(self.hist_human.hand)):
            rects.append(pygame.Rect(start_x + i * (CARD_W + CARD_GAP), y, CARD_W, CARD_H))
        return rects

    def _hist_board_rects(self, player: HistoryPlayer) -> List[pygame.Rect]:
        rects = []
        y = SCREEN_H - CARD_H - SMALL_CARD_H - 40 if player == self.hist_human else 60
        total_w = len(player.board) * (SMALL_CARD_W + CARD_GAP) - CARD_GAP
        start_x = max(20, (SCREEN_W - 280 - total_w) // 2)
        for i in range(len(player.board)):
            rects.append(pygame.Rect(start_x + i * (SMALL_CARD_W + CARD_GAP), y, SMALL_CARD_W, SMALL_CARD_H))
        return rects

    def render_hist_game(self):
        if not self.hist_game:
            return
        g = self.hist_game
        human = self.hist_human
        ai = self.hist_ai
        mx, my = pygame.mouse.get_pos()

        panel_w = 280
        play_w = SCREEN_W - panel_w

        # ── Top: AI section ──
        ai_panel_h = 180
        pygame.draw.rect(self.screen, BG_PANEL, (0, 0, play_w, ai_panel_h))
        draw_text(self.screen, ai.name, self.font_header, TEXT_RED, 20, 10)
        draw_text(self.screen, f"Life: {ai.life}/{HISTORY_LIFE}", self.font_body, TEXT_WHITE, 180, 14)
        draw_progress_bar(self.screen, 380, 16, 200, 14, ai.life, HISTORY_LIFE, TEXT_RED)
        draw_text(self.screen, f"Hand: {len(ai.hand)} | Deck: {len(ai.deck)}",
                  self.font_body, TEXT_DIM, 600, 14)
        draw_text(self.screen, f"Round {g.current_round}/{g.max_rounds}",
                  self.font_header, TEXT_CYAN, play_w - 150, 10)

        # AI org/policy
        if ai.organization:
            draw_text(self.screen, f"Org: {ai.organization.name}", self.font_tiny, TEXT_GREEN, 20, 36)
        if ai.policy:
            draw_text(self.screen, f"Policy: {ai.policy.name}", self.font_tiny, (255, 220, 100), 250, 36)

        # AI board
        draw_text(self.screen, "AI Board:", self.font_small, TEXT_DIM, 20, 55)
        ai_board_rects = self._hist_board_rects(ai)
        for i, rect in enumerate(ai_board_rects):
            card = ai.board[i]
            sel = (self.hist_scandal_target_mode or self.hist_attack_mode) and i == self.hist_selected_target_idx
            self._draw_hist_card(card, rect.x, rect.y, selected=sel, small=True, show_stats=True, player=ai)

        # AI face-down
        if ai.face_down:
            fd_y = 55 + SMALL_CARD_H + 5
            draw_text(self.screen, f"Conspiracies: {len(ai.face_down)}", self.font_small, TEXT_MAGENTA, 20, fd_y - 15)
            for i in range(len(ai.face_down)):
                fx = 200 + i * (SMALL_CARD_W + CARD_GAP)
                rect_fd = pygame.Rect(fx, fd_y, SMALL_CARD_W, SMALL_CARD_H)
                pygame.draw.rect(self.screen, (30, 35, 50), rect_fd, border_radius=6)
                pygame.draw.rect(self.screen, (80, 90, 120), rect_fd, width=2, border_radius=6)
                draw_text(self.screen, "???", self.font_card_name, TEXT_DIM, fx + 4, fd_y + 20, max_width=SMALL_CARD_W - 8)
                draw_text(self.screen, "Conspiracy", self.font_tiny, TEXT_MAGENTA, fx + 4, fd_y + 40)

        # ── Middle: Action log ──
        mid_y = ai_panel_h + 5
        log_h = 100
        pygame.draw.rect(self.screen, BG_PANEL, (20, mid_y, play_w - 40, log_h), border_radius=5)
        pygame.draw.rect(self.screen, (60, 70, 90), (20, mid_y, play_w - 40, log_h), width=1, border_radius=5)
        draw_text(self.screen, "Action Log", self.font_small, TEXT_DIM, 30, mid_y + 5)
        recent = self.action_log[-5:]
        for i, line in enumerate(recent):
            draw_text(self.screen, line, self.font_small, TEXT_WHITE, 30, mid_y + 25 + i * 18,
                      max_width=play_w - 80)

        # ── Bottom: Human section ──
        human_y = mid_y + log_h + 5
        draw_text(self.screen, human.name, self.font_header, TEXT_CYAN, 20, human_y)
        draw_text(self.screen, f"Life: {human.life}/{HISTORY_LIFE}", self.font_body, TEXT_WHITE, 180, human_y + 4)
        draw_progress_bar(self.screen, 380, human_y + 6, 200, 14, human.life, HISTORY_LIFE, TEXT_GREEN)

        if human.organization:
            draw_text(self.screen, f"Org: {human.organization.name}", self.font_tiny, TEXT_GREEN, 20, human_y + 26)
        if human.policy:
            draw_text(self.screen, f"Policy: {human.policy.name}", self.font_tiny, (255, 220, 100), 250, human_y + 26)

        # Human board
        board_y = human_y + 45
        draw_text(self.screen, "Your Board:", self.font_small, TEXT_DIM, 20, board_y)
        board_rects = self._hist_board_rects(human)
        for i, rect in enumerate(board_rects):
            card = human.board[i]
            sel = i == self.hist_selected_board_idx
            exhausted = card.card_id in human.attacks_used or card.card_id in human.just_played
            can_attack = (g.phase == 'attack' and not exhausted and
                         card.card_id not in human.just_played)
            self._draw_hist_card(card, rect.x, rect.y, selected=sel, small=True, show_stats=True,
                                can_attack=can_attack, exhausted=exhausted, player=human)

        # Human face-down
        if human.face_down:
            fd_y = board_y + SMALL_CARD_H + 5
            draw_text(self.screen, f"Your Conspiracies: {len(human.face_down)}", self.font_small, TEXT_MAGENTA, 20, fd_y - 15)
            for i, card in enumerate(human.face_down):
                fx = 200 + i * (SMALL_CARD_W + CARD_GAP)
                self._draw_hist_card(card, fx, fd_y, small=True, show_stats=False)

        # Human hand
        hand_y = SCREEN_H - CARD_H - 10
        draw_text(self.screen, f"Hand ({len(human.hand)})", self.font_header, TEXT_WHITE, 20, hand_y - 24)
        hand_rects = self._hist_hand_rects()
        for i, rect in enumerate(hand_rects):
            card = human.hand[i]
            sel = i == self.hist_selected_hand_idx
            self._draw_hist_card(card, rect.x, rect.y, selected=sel, small=False, show_stats=True, player=human)

        # ── Right panel: Action buttons ──
        self._render_hist_actions(mx, my)

        # ── AI thinking overlay ──
        if self.state == 'hist_ai':
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 80))
            self.screen.blit(overlay, (0, 0))
            draw_text(self.screen, "AI is plotting...", self.font_title, TEXT_RED,
                      SCREEN_W // 2, SCREEN_H // 2 - 40, center=True)
            for i, action in enumerate(self.ai_action_display[-4:]):
                draw_text(self.screen, action, self.font_body, TEXT_WHITE,
                          SCREEN_W // 2, SCREEN_H // 2 + i * 25, center=True, max_width=600)

        # ── Compact objective banner (bottom-left) ──
        banner_y = SCREEN_H - CARD_H - 40
        draw_text(self.screen, "Reduce AI to 0 life | Press H for help | ESC to exit",
                  self.font_tiny, TEXT_DIM, 20, banner_y - 16)

        # ── Help overlay ──
        if self.hist_show_help:
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            self.screen.blit(overlay, (0, 0))
            cx = SCREEN_W // 2
            cy = SCREEN_H // 2
            help_lines = [
                ("POLITICAL ARENA — HOW TO PLAY", self.font_title, TEXT_GOLD),
                ("", None, None),
                ("OBJECTIVE: Reduce opponent's life to 0 before they reduce yours!", self.font_body, TEXT_CYAN),
                ("", None, None),
                ("PLAY PHASE:", self.font_header, (255, 200, 80)),
                ("  • Select a hand card, then click Play to deploy it", self.font_small, TEXT_WHITE),
                ("  • Figures go on your board (max 7) — they attack and defend", self.font_small, TEXT_WHITE),
                ("  • Events deal damage to opponent AND heal you", self.font_small, TEXT_WHITE),
                ("  • Conspiracies are face-down traps that counter direct attacks", self.font_small, TEXT_WHITE),
                ("  • Scandals target an opponent figure — reduce their PWR/INF", self.font_small, TEXT_WHITE),
                ("  • Organizations give +1 PWR/INF to same-org cards", self.font_small, TEXT_WHITE),
                ("  • Policies let you draw 2 cards per turn instead of 1", self.font_small, TEXT_WHITE),
                ("  • Discard up to 3 cards per turn (draws replacement) — select card then click Discard", self.font_small, TEXT_WHITE),
                ("", None, None),
                ("ATTACK PHASE:", self.font_header, (255, 200, 80)),
                ("  • Select your figure, then select an opponent figure to attack", self.font_small, TEXT_WHITE),
                ("  • Power (attacker) vs Influence (defender) — excess becomes damage", self.font_small, TEXT_WHITE),
                ("  • No defenders? Attack directly for full damage!", self.font_small, TEXT_WHITE),
                ("  • Figures played this turn can't attack (summoning sickness)", self.font_small, TEXT_WHITE),
                ("", None, None),
                ("TREASURY:", self.font_header, (255, 200, 80)),
                ("  • Playing economic cards earns $ — spend on bonuses", self.font_small, TEXT_WHITE),
                ("  • $5: +2 PWR to a figure | $8: Heal 3 life | $4: Draw a card", self.font_small, TEXT_WHITE),
                ("  • $6: Reveal an opponent conspiracy | Sacrifice card: +$3", self.font_small, TEXT_WHITE),
                ("", None, None),
                ("SYNERGY: Cards with matching tags boost each other's PWR & INF!", self.font_small, (100, 255, 150)),
                ("", None, None),
                ("Press H to close this help", self.font_body, TEXT_DIM),
            ]
            total_h = len(help_lines) * 24
            start_y = cy - total_h // 2
            for i, (line, font, color) in enumerate(help_lines):
                if font and color and line:
                    draw_text(self.screen, line, font, color, cx, start_y + i * 24, center=True, max_width=900)

    def _render_hist_actions(self, mx, my):
        panel_x = SCREEN_W - 280
        panel_y = 5
        panel_w = 260
        panel_h = SCREEN_H - 15

        pygame.draw.rect(self.screen, BG_PANEL, (panel_x, panel_y, panel_w, panel_h), border_radius=5)
        pygame.draw.rect(self.screen, (60, 70, 90), (panel_x, panel_y, panel_w, panel_h), width=1, border_radius=5)

        g = self.hist_game
        human = self.hist_human

        draw_text(self.screen, "ARENA ACTIONS", self.font_header, TEXT_GOLD, panel_x + 10, panel_y + 8)

        self._action_button_rects = {}
        btn_w = panel_w - 20
        btn_x = panel_x + 10
        btn_h = 34
        gap = 5
        y = panel_y + 38

        is_human_turn = g.current_player_idx == 0

        if is_human_turn and g.phase == 'play':
            has_hand_sel = self.hist_selected_hand_idx is not None
            sel_card = None
            if has_hand_sel and self.hist_selected_hand_idx < len(human.hand):
                sel_card = human.hand[self.hist_selected_hand_idx]

            can_play = False
            play_label = "Play Card"
            if sel_card:
                if sel_card.card_type == 'Figure':
                    can_play = len(human.board) < HISTORY_MAX_BOARD
                    play_label = "Play Figure to Board"
                elif sel_card.card_type == 'Event':
                    can_play = True
                    play_label = "Play Event (dmg + heal)"
                elif sel_card.card_type == 'Conspiracy':
                    can_play = True
                    play_label = "Place Conspiracy Trap"
                elif sel_card.card_type == 'Scandal':
                    can_play = self.hist_selected_target_idx is not None
                    play_label = "Play Scandal on Target"
                elif sel_card.card_type == 'Organization':
                    can_play = True
                    play_label = "Establish Organization"
                elif sel_card.card_type == 'Policy':
                    can_play = True
                    play_label = "Enact Policy"

            buttons = [
                (play_label, 'hist_play', not can_play),
                ("Start Attack Phase", 'hist_start_attack', False),
                ("End Turn", 'hist_end_turn', False),
            ]
        elif is_human_turn and g.phase == 'attack':
            has_board_sel = self.hist_selected_board_idx is not None
            has_target_sel = self.hist_selected_target_idx is not None
            ai = self.hist_ai
            can_attack_direct = has_board_sel and not ai.has_defense()
            can_attack_target = has_board_sel and has_target_sel

            attack_label = "Attack Directly"
            attack_disabled = not can_attack_direct
            if has_target_sel:
                attack_label = "Attack Selected Target"
                attack_disabled = not can_attack_target

            buttons = [
                (attack_label, 'hist_attack', attack_disabled),
                ("Back to Play Phase", 'hist_back_to_play', False),
                ("End Turn", 'hist_end_turn', False),
            ]
        else:
            buttons = []

        for label, name, disabled in buttons:
            hovered = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my) and not disabled
            rect = draw_button(self.screen, btn_x, y, btn_w, btn_h, label,
                               self.font_body, hovered=hovered, disabled=disabled)
            self._action_button_rects[name] = rect
            y += btn_h + gap

        # Status info
        y += 10
        draw_text(self.screen, f"Your Life: {human.life}/{HISTORY_LIFE}", self.font_body, TEXT_GREEN, panel_x + 10, y)
        y += 20
        draw_text(self.screen, f"AI Life: {self.hist_ai.life}/{HISTORY_LIFE}", self.font_body, TEXT_RED, panel_x + 10, y)
        y += 20
        draw_text(self.screen, f"Board: {len(human.board)}/{HISTORY_MAX_BOARD}", self.font_body, TEXT_WHITE, panel_x + 10, y)
        y += 20
        draw_text(self.screen, f"Total PWR: {human.get_total_power()}", self.font_body, TEXT_RED, panel_x + 10, y)
        y += 20
        draw_text(self.screen, f"Total INF: {human.get_total_influence()}", self.font_body, TEXT_CYAN, panel_x + 10, y)
        y += 25

        # Active synergies
        all_syn = set()
        for c in human.board:
            for sn in human.get_synergy_names(c):
                all_syn.add(sn)
        if all_syn:
            draw_text(self.screen, f"Synergies ({len(all_syn)}):", self.font_small, (100, 255, 150), panel_x + 10, y)
            y += 16
            for sn in sorted(all_syn)[:5]:
                draw_text(self.screen, f"  {sn}", self.font_tiny, (100, 255, 150), panel_x + 10, y)
                y += 12
            y += 5
        else:
            draw_text(self.screen, "No active synergies", self.font_tiny, TEXT_DIM, panel_x + 10, y)
            y += 20

        # Treasury (money/grind mechanic)
        y += 5
        draw_text(self.screen, f"TREASURY: ${human.treasury}", self.font_body, (255, 220, 80), panel_x + 10, y)
        y += 22
        # Buy buttons
        buy_disabled_pw = human.treasury < 5 or not human.board
        buy_hovered_pw = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my) and not buy_disabled_pw
        rect_pw = draw_button(self.screen, btn_x, y, btn_w, btn_h, "Buy +2 PWR ($5)",
                              self.font_small, hovered=buy_hovered_pw, disabled=buy_disabled_pw)
        self._action_button_rects['hist_buy_power'] = rect_pw
        y += btn_h + gap

        buy_disabled_heal = human.treasury < 8 or human.life >= HISTORY_LIFE
        buy_hovered_heal = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my) and not buy_disabled_heal
        rect_heal = draw_button(self.screen, btn_x, y, btn_w, btn_h, "Buy +3 Life ($8)",
                                self.font_small, hovered=buy_hovered_heal, disabled=buy_disabled_heal)
        self._action_button_rects['hist_buy_heal'] = rect_heal
        y += btn_h + gap

        # Sacrifice button (only in play phase, only if hand has cards)
        sac_disabled = len(human.hand) == 0 or g.phase != 'play'
        sac_hovered = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my) and not sac_disabled
        rect_sac = draw_button(self.screen, btn_x, y, btn_w, btn_h, "Sacrifice Card (+$3)",
                               self.font_small, hovered=sac_hovered, disabled=sac_disabled)
        self._action_button_rects['hist_sacrifice'] = rect_sac
        y += btn_h + gap

        # Buy card draw button
        buy_disabled_draw = human.treasury < 4 or len(human.deck) == 0 or g.phase != 'play'
        buy_hovered_draw = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my) and not buy_disabled_draw
        rect_draw = draw_button(self.screen, btn_x, y, btn_w, btn_h, "Buy Card Draw ($4)",
                                self.font_small, hovered=buy_hovered_draw, disabled=buy_disabled_draw)
        self._action_button_rects['hist_buy_card'] = rect_draw
        y += btn_h + gap

        # Reveal conspiracy button
        reveal_disabled = human.treasury < 6 or len(self.hist_ai.face_down) == 0 or g.phase != 'play'
        reveal_hovered = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my) and not reveal_disabled
        rect_reveal = draw_button(self.screen, btn_x, y, btn_w, btn_h, "Reveal Conspiracy ($6)",
                                  self.font_small, hovered=reveal_hovered, disabled=reveal_disabled)
        self._action_button_rects['hist_reveal_con'] = rect_reveal
        y += btn_h + gap

        # Discard card button (up to 3 per turn, draw replacement)
        disc_disabled = (len(human.hand) == 0 or g.phase != 'play'
                         or human.discards_used >= HISTORY_MAX_DISCARDS
                         or self.hist_selected_hand_idx is None)
        disc_label = f"Discard Card ({human.discards_used}/{HISTORY_MAX_DISCARDS})"
        disc_hovered = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my) and not disc_disabled
        rect_disc = draw_button(self.screen, btn_x, y, btn_w, btn_h, disc_label,
                                self.font_small, hovered=disc_hovered, disabled=disc_disabled)
        self._action_button_rects['hist_discard'] = rect_disc
        y += btn_h + gap

        # Phase indicator
        phase_text = "Play Phase" if g.phase == 'play' else "Attack Phase"
        color = TEXT_CYAN if g.phase == 'play' else TEXT_RED
        draw_text(self.screen, phase_text, self.font_small, color, panel_x + 10, y)
        y += 20

        # Mode indicators
        if self.hist_attack_mode:
            draw_text(self.screen, "ATTACK MODE: Select attacker", self.font_tiny, TEXT_GOLD, panel_x + 10, y)
            y += 14
            draw_text(self.screen, "then select target", self.font_tiny, TEXT_DIM, panel_x + 10, y)
            y += 14
        if self.hist_scandal_target_mode:
            draw_text(self.screen, "SCANDAL MODE: Select target", self.font_tiny, TEXT_GOLD, panel_x + 10, y)
            y += 14

        # Org/policy info
        y = panel_y + panel_h - 80
        if human.organization:
            draw_text(self.screen, f"Org: {human.organization.name[:20]}", self.font_tiny, TEXT_GREEN, panel_x + 10, y)
            y += 14
        if human.policy:
            draw_text(self.screen, f"Policy: {human.policy.name[:20]}", self.font_tiny, (255, 220, 100), panel_x + 10, y)
            y += 14
        if human.face_down:
            draw_text(self.screen, f"Traps: {len(human.face_down)}", self.font_tiny, TEXT_MAGENTA, panel_x + 10, y)

    def handle_hist_click(self, mx, my):
        g = self.hist_game
        human = self.hist_human
        ai = self.hist_ai

        # Check action buttons first
        if hasattr(self, '_action_button_rects'):
            for name, rect in self._action_button_rects.items():
                if rect.collidepoint(mx, my):
                    self._handle_hist_action(name)
                    return

        # Clicking hand cards
        hand_rects = self._hist_hand_rects()
        for i, rect in enumerate(hand_rects):
            if rect.collidepoint(mx, my):
                if g.phase == 'play':
                    self.hist_selected_hand_idx = i if self.hist_selected_hand_idx != i else None
                    self.hist_selected_board_idx = None
                    self.hist_selected_target_idx = None
                    # If scandal card selected, enter scandal target mode
                    if self.hist_selected_hand_idx is not None:
                        card = human.hand[i]
                        if card.card_type == 'Scandal':
                            self.hist_scandal_target_mode = True
                        else:
                            self.hist_scandal_target_mode = False
                return

        # Clicking own board (select attacker in attack phase)
        if g.phase == 'attack':
            board_rects = self._hist_board_rects(human)
            for i, rect in enumerate(board_rects):
                if rect.collidepoint(mx, my):
                    card = human.board[i]
                    if card.card_id not in human.attacks_used and card.card_id not in human.just_played:
                        self.hist_selected_board_idx = i if self.hist_selected_board_idx != i else None
                        self.hist_selected_target_idx = None
                    return

        # Clicking AI board (select target)
        ai_board_rects = self._hist_board_rects(ai)
        for i, rect in enumerate(ai_board_rects):
            if rect.collidepoint(mx, my):
                if self.hist_scandal_target_mode or g.phase == 'attack':
                    self.hist_selected_target_idx = i if self.hist_selected_target_idx != i else None
                return

    def _handle_hist_action(self, name):
        g = self.hist_game
        human = self.hist_human
        ai = self.hist_ai

        if name == 'hist_play':
            if self.hist_selected_hand_idx is None or self.hist_selected_hand_idx >= len(human.hand):
                self.show_message("Select a card from your hand first!")
                return
            card = human.hand[self.hist_selected_hand_idx]
            target = None
            if card.card_type == 'Scandal':
                if self.hist_selected_target_idx is None or self.hist_selected_target_idx >= len(ai.board):
                    self.show_message("Select an opponent figure to scandalize!")
                    return
                target = ai.board[self.hist_selected_target_idx]
            result = g.play_card(card, target=target)
            self.action_log.append(result)
            self.hist_selected_hand_idx = None
            self.hist_selected_target_idx = None
            self.hist_scandal_target_mode = False
            if g.check_win():
                self.state = 'hist_gameover'

        elif name == 'hist_start_attack':
            g.switch_to_attack_phase()
            self.action_log.append(f"You enter attack phase")
            self.hist_selected_board_idx = None
            self.hist_selected_target_idx = None

        elif name == 'hist_back_to_play':
            g.phase = 'play'
            self.hist_selected_board_idx = None
            self.hist_selected_target_idx = None

        elif name == 'hist_attack':
            if self.hist_selected_board_idx is None or self.hist_selected_board_idx >= len(human.board):
                self.show_message("Select one of your figures to attack with!")
                return
            attacker = human.board[self.hist_selected_board_idx]
            target = None
            if self.hist_selected_target_idx is not None and self.hist_selected_target_idx < len(ai.board):
                target = ai.board[self.hist_selected_target_idx]
            result = g.attack(attacker, target)
            self.action_log.append(result)
            self.hist_selected_board_idx = None
            self.hist_selected_target_idx = None
            if g.check_win():
                self.state = 'hist_gameover'

        elif name == 'hist_end_turn':
            self._hist_end_turn()

        elif name == 'hist_buy_power':
            g = self.hist_game
            human = self.hist_human
            if self.hist_selected_board_idx is not None and self.hist_selected_board_idx < len(human.board):
                card = human.board[self.hist_selected_board_idx]
                msg = g.buy_power(card)
                self.show_message(msg)
            else:
                self.show_message("Select a board figure first!")

        elif name == 'hist_buy_heal':
            g = self.hist_game
            msg = g.buy_heal()
            self.show_message(msg)
            if g.check_win():
                self.state = 'hist_gameover'

        elif name == 'hist_sacrifice':
            g = self.hist_game
            human = self.hist_human
            if self.hist_selected_hand_idx is not None and self.hist_selected_hand_idx < len(human.hand):
                card = human.hand[self.hist_selected_hand_idx]
                msg = g.sacrifice_card(card)
                self.show_message(msg)
                self.hist_selected_hand_idx = None
            else:
                self.show_message("Select a hand card to sacrifice!")

        elif name == 'hist_buy_card':
            g = self.hist_game
            msg = g.buy_card()
            self.show_message(msg)

        elif name == 'hist_reveal_con':
            g = self.hist_game
            msg = g.reveal_conspiracy()
            self.show_message(msg)

        elif name == 'hist_discard':
            g = self.hist_game
            human = self.hist_human
            if self.hist_selected_hand_idx is not None and self.hist_selected_hand_idx < len(human.hand):
                card = human.hand[self.hist_selected_hand_idx]
                msg = g.discard_card(card)
                self.show_message(msg)
                self.action_log.append(msg)
                self.hist_selected_hand_idx = None
            else:
                self.show_message("Select a hand card to discard!")

    def _hist_end_turn(self):
        g = self.hist_game
        human = self.hist_human
        ai = self.hist_ai
        human.end_turn_cleanup()
        self.hist_selected_hand_idx = None
        self.hist_selected_board_idx = None
        self.hist_selected_target_idx = None
        self.hist_attack_mode = False
        self.hist_scandal_target_mode = False
        g.end_turn()
        if g.check_win():
            self.state = 'hist_gameover'
            return
        # AI takes turn
        self.state = 'hist_ai'
        self.ai_action_display = g.ai_take_turn(ai)
        self.action_log.extend(self.ai_action_display)
        self.ai_display_timer = 2.5

    def finish_hist_ai_turn(self):
        g = self.hist_game
        if g.check_win():
            self.state = 'hist_gameover'
            return
        # Back to human
        self.hist_selected_hand_idx = None
        self.hist_selected_board_idx = None
        self.hist_selected_target_idx = None
        self.state = 'hist_playing'
        self.ai_display_timer = 0

    def render_hist_gameover(self):
        g = self.hist_game
        if not g:
            return

        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))

        winner = g.winner
        if winner == self.hist_human:
            draw_text(self.screen, "YOU WIN!", self.font_title, TEXT_GREEN,
                      SCREEN_W // 2, 150, center=True)
        else:
            draw_text(self.screen, f"{winner.name} WINS!", self.font_title, TEXT_RED,
                      SCREEN_W // 2, 150, center=True)

        y = 210
        draw_text(self.screen, f"Rounds: {g.current_round}", self.font_header, TEXT_WHITE,
                  SCREEN_W // 2, y, center=True)
        y += 35
        for p in g.players:
            color = TEXT_GREEN if p == winner else TEXT_DIM
            draw_text(self.screen, f"{p.name}: {p.life} life | {len(p.board)} figures on board",
                      self.font_body, color, SCREEN_W // 2, y, center=True)
            y += 25

        # Winner's top figures
        y += 20
        draw_text(self.screen, "Winner's Top Figures:", self.font_header, TEXT_GOLD,
                  SCREEN_W // 2, y, center=True)
        y += 30
        top = sorted(winner.board, key=lambda c: c.power, reverse=True)[:3]
        for card in top:
            draw_text(self.screen, f"[{card.rarity}] {card.name} - PWR {card.power} INF {card.influence}",
                      self.font_body, RARITY_RGB.get(card.rarity, TEXT_WHITE),
                      SCREEN_W // 2, y, center=True)
            y += 22

        # Buttons
        self.menu_buttons = []
        mx, my = pygame.mouse.get_pos()
        btn_w, btn_h = 200, 45
        btns = [
            ("Play Again", lambda: self.goto_hist_setup()),
            ("Main Menu", lambda: self.goto_menu()),
            ("Quit", lambda: pygame.event.post(pygame.event.Event(pygame.QUIT))),
        ]
        for i, (label, action) in enumerate(btns):
            x = SCREEN_W // 2 - btn_w // 2
            by = y + 30 + i * 55
            hovered = pygame.Rect(x, by, btn_w, btn_h).collidepoint(mx, my)
            rect = draw_button(self.screen, x, by, btn_w, btn_h, label,
                               self.font_header, hovered=hovered)
            self.menu_buttons.append({'rect': rect, 'action': action})

    # ── Card Browser (History Collection) ─────────────────────────────────────

    def goto_card_browser(self):
        self.state = 'card_browser'
        self.browser_scroll = 0
        self.browser_scroll_target = 0
        self.browser_selected_card = None
        self.browser_show_detail = False

    def _get_browser_filtered(self):
        cards = self.history_cards
        if self.browser_filter_type:
            cards = get_cards_by_type(cards, self.browser_filter_type)
        if self.browser_filter_org:
            cards = get_cards_by_org(cards, self.browser_filter_org)
        if self.browser_filter_rarity:
            cards = get_cards_by_rarity(cards, self.browser_filter_rarity)
        if self.browser_filter_region:
            cards = [c for c in cards if c.region == self.browser_filter_region]
        if self.browser_filter_tag:
            cards = [c for c in cards if self.browser_filter_tag in c.tags]
        if self.browser_search:
            cards = search_cards(cards, self.browser_search)
        # Sort
        if self.browser_sort == 'power':
            cards = sorted(cards, key=lambda c: c.power, reverse=True)
        elif self.browser_sort == 'influence':
            cards = sorted(cards, key=lambda c: c.influence, reverse=True)
        elif self.browser_sort == 'name':
            cards = sorted(cards, key=lambda c: c.name.lower())
        else:
            cards = sorted(cards, key=lambda c: c.card_id)
        return cards

    def render_card_browser(self):
        # Title
        draw_text(self.screen, "HISTORY CARD COLLECTION", self.font_title, TEXT_GOLD,
                  SCREEN_W // 2, 25, center=True)
        all_cards = self.history_cards
        filtered = self._get_browser_filtered()
        draw_text(self.screen, f"{len(filtered)} / {len(all_cards)} cards", self.font_body, TEXT_DIM,
                  SCREEN_W // 2, 55, center=True)

        # Left sidebar — filters
        sidebar_w = 220
        sidebar_x = 10
        sidebar_y = 80
        self.menu_buttons = []

        mx, my = pygame.mouse.get_pos()

        # Type filters
        draw_text(self.screen, "CARD TYPE", self.font_header, TEXT_CYAN, sidebar_x, sidebar_y)
        y = sidebar_y + 22
        type_filters = [('All', None)] + [(t, t) for t in CARD_TYPES]
        for label, val in type_filters:
            active = self.browser_filter_type == val or (val is None and self.browser_filter_type is None)
            hovered = pygame.Rect(sidebar_x, y, sidebar_w - 10, 22).collidepoint(mx, my)
            rect = draw_button(self.screen, sidebar_x, y, sidebar_w - 10, 22, label,
                               self.font_small, hovered=hovered, disabled=False)
            if active:
                pygame.draw.rect(self.screen, TEXT_GOLD, rect, width=2, border_radius=4)
            self.menu_buttons.append({'rect': rect, 'action': lambda v=val: self._set_browser_filter('type', v)})
            y += 24

        # Rarity filters
        y += 8
        draw_text(self.screen, "RARITY", self.font_header, TEXT_CYAN, sidebar_x, y)
        y += 22
        rarities = [('All', None), ('Common', 'C'), ('Uncommon', 'U'), ('Rare', 'R'),
                    ('Ultra-Rare', 'UR'), ('Legendary', 'L'), ('Secret Rare', 'SR')]
        for label, val in rarities:
            active = self.browser_filter_rarity == val or (val is None and self.browser_filter_rarity is None)
            hovered = pygame.Rect(sidebar_x, y, sidebar_w - 10, 20).collidepoint(mx, my)
            rect = draw_button(self.screen, sidebar_x, y, sidebar_w - 10, 20, label,
                               self.font_tiny, hovered=hovered, disabled=False)
            if active:
                pygame.draw.rect(self.screen, TEXT_GOLD, rect, width=2, border_radius=4)
            self.menu_buttons.append({'rect': rect, 'action': lambda v=val: self._set_browser_filter('rarity', v)})
            y += 22

        # Sort
        y += 8
        draw_text(self.screen, "SORT BY", self.font_header, TEXT_CYAN, sidebar_x, y)
        y += 22
        sorts = [('ID', 'id'), ('Power', 'power'), ('Influence', 'influence'), ('Name', 'name')]
        for label, val in sorts:
            active = self.browser_sort == val
            hovered = pygame.Rect(sidebar_x, y, sidebar_w - 10, 20).collidepoint(mx, my)
            rect = draw_button(self.screen, sidebar_x, y, sidebar_w - 10, 20, label,
                               self.font_tiny, hovered=hovered, disabled=False)
            if active:
                pygame.draw.rect(self.screen, TEXT_GOLD, rect, width=2, border_radius=4)
            self.menu_buttons.append({'rect': rect, 'action': lambda v=val: self._set_browser_filter('sort', v)})
            y += 22

        # Region filters (top regions by card count)
        y += 8
        draw_text(self.screen, "REGION", self.font_header, TEXT_CYAN, sidebar_x, y)
        y += 22
        from collections import Counter
        region_counts = Counter(c.region for c in all_cards)
        top_regions = [r for r, _ in region_counts.most_common(12)]
        region_filters = [('All', None)] + [(f"{r} ({region_counts[r]})", r) for r in top_regions]
        for label, val in region_filters:
            active = self.browser_filter_region == val or (val is None and self.browser_filter_region is None)
            hovered = pygame.Rect(sidebar_x, y, sidebar_w - 10, 18).collidepoint(mx, my)
            rect = draw_button(self.screen, sidebar_x, y, sidebar_w - 10, 18, label,
                               self.font_tiny, hovered=hovered, disabled=False)
            if active:
                pygame.draw.rect(self.screen, TEXT_GOLD, rect, width=2, border_radius=4)
            self.menu_buttons.append({'rect': rect, 'action': lambda v=val: self._set_browser_filter('region', v)})
            y += 20

        # Stats summary at bottom
        y += 8
        draw_text(self.screen, "STATS", self.font_header, TEXT_CYAN, sidebar_x, y)
        y += 20
        type_counts = Counter(c.card_type for c in filtered)
        for t in CARD_TYPES:
            cnt = type_counts.get(t, 0)
            if cnt > 0:
                draw_text(self.screen, f"  {t}: {cnt}", self.font_tiny, TEXT_DIM, sidebar_x, y)
                y += 14

        # Back button
        back_y = SCREEN_H - 50
        hovered = pygame.Rect(sidebar_x, back_y, sidebar_w - 10, 36).collidepoint(mx, my)
        rect = draw_button(self.screen, sidebar_x, back_y, sidebar_w - 10, 36, "Back to Menu",
                           self.font_body, hovered=hovered)
        self.menu_buttons.append({'rect': rect, 'action': lambda: self.goto_menu()})

        # Card grid area
        grid_x = sidebar_w + 20
        grid_y = 80
        grid_w = SCREEN_W - grid_x - 20
        grid_h = SCREEN_H - grid_y - 20

        # Search bar
        search_rect = pygame.Rect(grid_x, grid_y - 20, grid_w - 20, 24)
        pygame.draw.rect(self.screen, BG_PANEL, search_rect, border_radius=4)
        pygame.draw.rect(self.screen, (80, 90, 110), search_rect, width=1, border_radius=4)
        search_label = f"Search: {self.browser_search}|" if self.browser_search else "Search: (click to type, ESC to clear)"
        search_color = TEXT_WHITE if self.browser_search else TEXT_DIM
        draw_text(self.screen, search_label, self.font_small, search_color, grid_x + 6, grid_y - 16)
        self._browser_search_rect = search_rect

        # Smooth scroll
        self.browser_scroll += (self.browser_scroll_target - self.browser_scroll) * 0.2

        # Card layout
        card_w = SMALL_CARD_W
        card_h = SMALL_CARD_H
        gap = CARD_GAP
        cols = max(1, grid_w // (card_w + gap))
        row_h = card_h + gap + 16  # extra for name text below

        # Clip area
        clip_rect = pygame.Rect(grid_x, grid_y, grid_w, grid_h)
        prev_clip = self.screen.get_clip()
        self.screen.set_clip(clip_rect)

        for i, card in enumerate(filtered):
            col = i % cols
            row = i // cols
            cx = grid_x + col * (card_w + gap)
            cy = grid_y + row * row_h - int(self.browser_scroll)
            if cy + row_h < grid_y or cy > grid_y + grid_h:
                continue
            self._draw_history_card(card, cx, cy, small=True)

        self.screen.set_clip(prev_clip)

        # Scroll bar
        total_h = (len(filtered) + cols - 1) // cols * row_h
        if total_h > grid_h:
            bar_h = max(30, int(grid_h * grid_h / total_h))
            bar_y = grid_y + int((grid_h - bar_h) * self.browser_scroll / max(1, total_h - grid_h))
            pygame.draw.rect(self.screen, (60, 70, 90), (SCREEN_W - 12, grid_y, 6, grid_h), border_radius=3)
            pygame.draw.rect(self.screen, TEXT_DIM, (SCREEN_W - 12, bar_y, 6, bar_h), border_radius=3)

        # Detail panel
        if self.browser_show_detail and self.browser_selected_card:
            self._render_card_detail(self.browser_selected_card)

    def _set_browser_filter(self, kind, val):
        if kind == 'type':
            self.browser_filter_type = val
        elif kind == 'org':
            self.browser_filter_org = val
        elif kind == 'rarity':
            self.browser_filter_rarity = val
        elif kind == 'region':
            self.browser_filter_region = val
        elif kind == 'tag':
            self.browser_filter_tag = val
        elif kind == 'sort':
            self.browser_sort = val
        self.browser_scroll = 0
        self.browser_scroll_target = 0

    def _draw_history_card(self, card: HistoryCard, x, y, small=True):
        w = SMALL_CARD_W if small else CARD_W
        h = SMALL_CARD_H if small else CARD_H
        rect = pygame.Rect(x, y, w, h)

        type_color = CARD_TYPE_COLORS.get(card.card_type, (150, 150, 150))
        border_color = RARITY_BORDER.get(card.rarity, (100, 100, 100))
        bg = BG_CARD
        if self.browser_selected_card and card.card_id == self.browser_selected_card.card_id:
            bg = BG_CARD_SEL
            border_color = (255, 255, 100)

        pygame.draw.rect(self.screen, bg, rect, border_radius=6)
        pygame.draw.rect(self.screen, border_color, rect, width=2, border_radius=6)

        # Type color bar
        pygame.draw.rect(self.screen, type_color, (x, y, w, 4), border_radius=6)

        # Rarity tag
        rarity_rgb = RARITY_RGB.get(card.rarity, (200, 200, 200))
        draw_text(self.screen, f"[{card.rarity}]", self.font_tiny, rarity_rgb, x + 3, y + 6)

        # Type tag
        draw_text(self.screen, card.card_type, self.font_tiny, type_color, x + 3, y + 18)

        # Name
        name = card.name
        max_len = 18 if small else 24
        if len(name) > max_len:
            name = name[:16 if small else 22] + '..'
        draw_text(self.screen, name, self.font_card_name, TEXT_WHITE, x + 3, y + 32, max_width=w - 6)

        # Year
        draw_text(self.screen, card.year, self.font_tiny, TEXT_DIM, x + 3, y + 48)

        # Stats
        stat_y = y + h - 28
        draw_text(self.screen, f"PWR {card.power}", self.font_tiny, TEXT_RED, x + 3, stat_y)
        draw_text(self.screen, f"INF {card.influence}", self.font_tiny, TEXT_CYAN, x + 45, stat_y)

        # Org
        if card.organization != 'None':
            draw_text(self.screen, card.organization[:12], self.font_tiny, TEXT_GREEN, x + 3, stat_y + 12)

    def _render_card_detail(self, card: HistoryCard):
        # Overlay
        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 200))
        self.screen.blit(overlay, (0, 0))

        # Detail card — wider to fit synergy info
        dw, dh = 560, 680
        dx = SCREEN_W // 2 - dw // 2
        dy = 30
        pygame.draw.rect(self.screen, BG_PANEL, (dx, dy, dw, dh), border_radius=10)
        type_color = CARD_TYPE_COLORS.get(card.card_type, (150, 150, 150))
        border_color = RARITY_BORDER.get(card.rarity, (100, 100, 100))
        pygame.draw.rect(self.screen, border_color, (dx, dy, dw, dh), width=3, border_radius=10)
        pygame.draw.rect(self.screen, type_color, (dx, dy, dw, 6), border_radius=10)

        y = dy + 16
        rarity_rgb = RARITY_RGB.get(card.rarity, (200, 200, 200))
        draw_text(self.screen, f"[{card.rarity}] {card.card_type}", self.font_header, rarity_rgb, dx + 20, y)
        y += 28
        draw_text(self.screen, card.name, self.font_title, TEXT_WHITE, dx + 20, y)
        y += 36
        draw_text(self.screen, f"Year: {card.year}  |  Region: {card.region}  |  Org: {card.organization}",
                  self.font_body, TEXT_DIM, dx + 20, y)
        y += 28

        # Stats bars
        bar_w = 200
        draw_text(self.screen, f"Power: {card.power}/10", self.font_header, TEXT_RED, dx + 20, y)
        pygame.draw.rect(self.screen, (60, 60, 60), (dx + 160, y + 4, bar_w, 16), border_radius=3)
        pygame.draw.rect(self.screen, TEXT_RED, (dx + 160, y + 4, int(bar_w * card.power / 10), 16), border_radius=3)
        y += 28
        draw_text(self.screen, f"Influence: {card.influence}/10", self.font_header, TEXT_CYAN, dx + 20, y)
        pygame.draw.rect(self.screen, (60, 60, 60), (dx + 160, y + 4, bar_w, 16), border_radius=3)
        pygame.draw.rect(self.screen, TEXT_CYAN, (dx + 160, y + 4, int(bar_w * card.influence / 10), 16), border_radius=3)
        y += 32

        # Effect
        draw_text(self.screen, "EFFECT:", self.font_header, TEXT_GOLD, dx + 20, y)
        y += 22
        draw_text(self.screen, card.effect, self.font_body, TEXT_WHITE, dx + 20, y, max_width=dw - 40)
        y += 36

        # Description
        draw_text(self.screen, "DESCRIPTION:", self.font_header, TEXT_GOLD, dx + 20, y)
        y += 22
        draw_text(self.screen, card.effect_desc, self.font_body, TEXT_DIM, dx + 20, y, max_width=dw - 40)
        y += 36

        # Flavor
        draw_text(self.screen, "HISTORICAL CONTEXT:", self.font_header, TEXT_GOLD, dx + 20, y)
        y += 22
        draw_text(self.screen, card.flavor, self.font_body, TEXT_CYAN, dx + 20, y, max_width=dw - 40)
        y += 32

        # Tags
        if card.tags:
            draw_text(self.screen, "Tags: " + ", ".join(card.tags), self.font_small, TEXT_MAGENTA, dx + 20, y, max_width=dw - 40)
        y += 24

        # Synergy connections
        draw_text(self.screen, "SYNERGY GROUPS:", self.font_header, (100, 255, 150), dx + 20, y)
        y += 22
        syn_groups = []
        for group in SYNERGY_GROUPS:
            gname = group['name']
            tags = group['tags']
            if any(t in card.tags for t in tags):
                syn_groups.append((gname, tags))
        if syn_groups:
            for gname, tags in syn_groups:
                matching = [t for t in tags if t in card.tags]
                draw_text(self.screen, f"  {gname} — tags: {', '.join(matching)}", self.font_small, (100, 255, 150), dx + 20, y)
                y += 18
                # Find related cards that share these synergy tags
                related = [c for c in self.history_cards
                           if c.card_id != card.card_id and any(t in c.tags for t in tags)]
                if related:
                    related_names = [c.name for c in sorted(related, key=lambda c: c.card_id)[:5]]
                    draw_text(self.screen, f"    Related: {', '.join(related_names)}", self.font_tiny, TEXT_DIM, dx + 20, y, max_width=dw - 40)
                    y += 16
        else:
            draw_text(self.screen, "  No synergy groups for this card", self.font_small, TEXT_DIM, dx + 20, y)
        y += 12

        # Related cards by shared tags (non-synergy)
        shared_tag_cards = [c for c in self.history_cards
                            if c.card_id != card.card_id and c.tags and len(set(c.tags) & set(card.tags)) > 0]
        if shared_tag_cards and y < dy + dh - 60:
            draw_text(self.screen, f"SHARED TAG CARDS ({len(shared_tag_cards)} total):", self.font_header, TEXT_CYAN, dx + 20, y)
            y += 20
            # Show top 6 by most shared tags
            shared_tag_cards.sort(key=lambda c: len(set(c.tags) & set(card.tags)), reverse=True)
            for c in shared_tag_cards[:6]:
                shared = set(c.tags) & set(card.tags)
                draw_text(self.screen, f"  {c.name} [{c.card_type}] — {', '.join(shared)}", self.font_tiny, TEXT_DIM, dx + 20, y, max_width=dw - 40)
                y += 14

        # Close button
        mx, my = pygame.mouse.get_pos()
        close_rect = pygame.Rect(dx + dw - 50, dy + 10, 36, 36)
        hovered = close_rect.collidepoint(mx, my)
        draw_button(self.screen, close_rect.x, close_rect.y, close_rect.w, close_rect.h, "X",
                    self.font_header, hovered=hovered)
        self.menu_buttons.append({'rect': close_rect, 'action': lambda: self._close_browser_detail()})

    def _close_browser_detail(self):
        self.browser_show_detail = False

    def handle_browser_click(self, mx, my):
        # Check menu buttons first (filters, back, close)
        for btn in self.menu_buttons:
            if btn['rect'].collidepoint(mx, my):
                btn['action']()
                return

        if self.browser_show_detail:
            return  # only close button works

        # Check search bar click
        if hasattr(self, '_browser_search_rect') and self._browser_search_rect.collidepoint(mx, my):
            self.browser_search = ''
            return

        # Check card grid clicks
        sidebar_w = 220
        grid_x = sidebar_w + 20
        grid_y = 80
        grid_w = SCREEN_W - grid_x - 20
        grid_h = SCREEN_H - grid_y - 20
        card_w = SMALL_CARD_W
        card_h = SMALL_CARD_H
        gap = CARD_GAP
        cols = max(1, grid_w // (card_w + gap))
        row_h = card_h + gap + 16

        filtered = self._get_browser_filtered()
        for i, card in enumerate(filtered):
            col = i % cols
            row = i // cols
            cx = grid_x + col * (card_w + gap)
            cy = grid_y + row * row_h - int(self.browser_scroll)
            if cy + row_h < grid_y or cy > grid_y + grid_h:
                continue
            if pygame.Rect(cx, cy, card_w, card_h).collidepoint(mx, my):
                self.browser_selected_card = card
                self.browser_show_detail = True
                return

    # ── Duel Mode ─────────────────────────────────────────────────────────────

    def goto_duel_setup(self):
        self.state = 'duel_setup'

    def render_duel_setup(self):
        draw_text(self.screen, "EXCHANGE DUEL", self.font_title, TEXT_GOLD,
                  SCREEN_W // 2, 60, center=True)
        draw_text(self.screen, "Trade, scalp, and profit in a business battleground",
                  self.font_header, TEXT_CYAN, SCREEN_W // 2, 100, center=True)

        draw_text(self.screen, "Select Difficulty:", self.font_header, (255, 200, 80),
                  SCREEN_W // 2, 160, center=True)

        self.menu_buttons = []
        mx, my = pygame.mouse.get_pos()
        btn_w, btn_h = 280, 45

        diffs = [
            ("Easy (casual trading)", 'easy', 50),
            ("Medium (balanced)", 'medium', 100),
            ("Hard (cutthroat)", 'hard', 200),
        ]
        for i, (label, diff, target) in enumerate(diffs):
            y = 200 + i * 55
            hovered = pygame.Rect(SCREEN_W // 2 - btn_w // 2, y, btn_w, btn_h).collidepoint(mx, my)
            rect = draw_button(self.screen, SCREEN_W // 2 - btn_w // 2, y, btn_w, btn_h, label,
                               self.font_body, hovered=hovered)
            self.menu_buttons.append({
                'rect': rect,
                'action': lambda d=diff, t=target: self.start_duel(d, t)
            })

        hovered = pygame.Rect(SCREEN_W // 2 - btn_w // 2, SCREEN_H - 80, btn_w, btn_h).collidepoint(mx, my)
        rect = draw_button(self.screen, SCREEN_W // 2 - btn_w // 2, SCREEN_H - 80, btn_w, btn_h,
                           "Back to Menu", self.font_body, hovered=hovered)
        self.menu_buttons.append({'rect': rect, 'action': lambda: self.goto_menu()})

        # Rules summary
        y = 380
        rules = [
            "HOW IT WORKS:",
            "1. Each player has a portfolio of currency cards on the board",
            "2. Take turns playing cards, using abilities, and making trade offers",
            "3. Trade: offer your cards for opponent's cards. Profit = their value - your value",
            "4. Opponent can accept or decline your offer",
            "5. First to reach the profit target wins!",
            "",
            "Card abilities are UTILITY-based (peek, force trades, lock cards, etc.)",
            "Rarer cards have stronger utility abilities, not value multipliers",
        ]
        for i, line in enumerate(rules):
            color = TEXT_GOLD if i == 0 else (TEXT_DIM if line == "" else TEXT_WHITE)
            draw_text(self.screen, line, self.font_small, color, SCREEN_W // 2 - 250, y + i * 20)

    def start_duel(self, difficulty: str, target_profit: float):
        """Start a new exchange duel."""
        deck1 = generate_duel_deck(self.card_pool, deck_size=20)
        deck2 = generate_duel_deck(self.card_pool, deck_size=20)
        self.duel_human = DuelPlayer("You", deck1, is_ai=False)
        self.duel_ai = DuelPlayer("AI Trader", deck2, is_ai=True)
        self.duel = ExchangeDuel(self.duel_human, self.duel_ai,
                                 target_profit=target_profit, max_rounds=15)
        self.duel.ai_difficulty = difficulty
        self.duel.setup()
        self.state = 'duel'
        self.action_log = list(self.duel.log)
        self.duel_offer_mode = False
        self.duel_offer_offered = []
        self.duel_offer_offered_from_hand = []
        self.duel_offer_requested = []
        self.duel_selected_hand_idx = None
        self.duel_selected_portfolio_idx = None
        # Human draws at start of their first turn
        self.duel_human.draw(2)
        self.show_message(f"Duel started! Target: ${target_profit:.0f} profit", 3.0)

    def _duel_card_rects(self, cards, start_x, y, small=True) -> List[pygame.Rect]:
        """Get rects for a row of cards."""
        w = SMALL_CARD_W if small else CARD_W
        h = SMALL_CARD_H if small else CARD_H
        rects = []
        total_w = len(cards) * (w + CARD_GAP) - CARD_GAP
        x = max(20, start_x - total_w // 2)
        for i in range(len(cards)):
            rects.append(pygame.Rect(x + i * (w + CARD_GAP), y, w, h))
        return rects

    def _draw_duel_card(self, card: DuelCard, x, y, selected=False, face_down=False, small=True):
        """Draw a duel card."""
        w = SMALL_CARD_W if small else CARD_W
        h = SMALL_CARD_H if small else CARD_H

        if face_down:
            # Draw card back
            rect = pygame.Rect(x, y, w, h)
            pygame.draw.rect(self.screen, (30, 35, 50), rect, border_radius=6)
            pygame.draw.rect(self.screen, (80, 90, 120), rect, width=2, border_radius=6)
            draw_text(self.screen, "???", self.font_card_name, TEXT_DIM, x + 4, y + 20, max_width=w - 8)
            draw_text(self.screen, "Face Down", self.font_tiny, TEXT_DIM, x + 4, y + 40)
            draw_text(self.screen, f"[{card.rarity}]", self.font_tiny, RARITY_RGB.get(card.rarity, TEXT_DIM), x + 4, y + 6)
            return rect

        border_color = RARITY_BORDER.get(card.rarity, (100, 100, 100))
        bg_color = BG_CARD
        if selected:
            bg_color = BG_CARD_SEL
            border_color = (255, 255, 100)
        if card.protected:
            border_color = (100, 200, 255)

        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(self.screen, bg_color, rect, border_radius=6)
        pygame.draw.rect(self.screen, border_color, rect, width=2, border_radius=6)

        rarity_rgb = RARITY_RGB.get(card.rarity, (200, 200, 200))
        pygame.draw.rect(self.screen, rarity_rgb, (x, y, w, 4), border_radius=6)

        type_str = f"[{card.rarity}]"
        draw_text(self.screen, type_str, self.font_small, rarity_rgb, x + 4, y + 6)

        name = card.name
        max_len = 22 if small else 28
        if len(name) > max_len:
            name = name[:20 if small else 26] + '..'
        draw_text(self.screen, name, self.font_card_name, TEXT_WHITE, x + 4, y + 20, max_width=w - 8)

        val_color = TEXT_GOLD if card.display_value >= 1 else TEXT_DIM
        draw_text(self.screen, f"${card.display_value:.2f}", self.font_card_val, val_color, x + 4, y + 38 if small else 42)

        if card.ability != 'none':
            ab_color = TEXT_MAGENTA if card.ability_type == 'active' else TEXT_CYAN
            ab_text = card.ability_desc
            if card.ability_used:
                ab_text = "(Used) " + ab_text
                ab_color = TEXT_DIM
            draw_text(self.screen, ab_text, self.font_card_desc, ab_color, x + 4, y + 72 if small else 82, max_width=w - 8)

        if card.shorted_by is not None:
            draw_text(self.screen, "SHORTED", self.font_tiny, TEXT_RED, x + 4, y + h - 28)
        if card.protected:
            draw_text(self.screen, "LOCKED", self.font_tiny, (100, 200, 255), x + 4, y + h - 16)

        return rect

    def render_duel(self):
        if not self.duel:
            return

        d = self.duel
        human = self.duel_human
        ai = self.duel_ai
        mx, my = pygame.mouse.get_pos()

        # ── Top: AI section ──
        pygame.draw.rect(self.screen, BG_PANEL, (0, 0, SCREEN_W, 200))
        draw_text(self.screen, f"{ai.name}", self.font_header, TEXT_RED, 20, 10)
        draw_text(self.screen, f"Profit: ${ai.profit:.2f} / ${d.target_profit:.0f}",
                  self.font_body, TEXT_WHITE, 180, 14)
        draw_progress_bar(self.screen, 380, 16, 200, 14, ai.profit, d.target_profit, TEXT_RED)
        draw_text(self.screen, f"Hand: {len(ai.hand)} | Deck: {len(ai.deck)}",
                  self.font_body, TEXT_DIM, 600, 14)
        draw_text(self.screen, f"Round {d.current_round}/{d.max_rounds}",
                  self.font_header, TEXT_CYAN, SCREEN_W - 300, 10)

        # AI portfolio
        draw_text(self.screen, "AI Portfolio:", self.font_small, TEXT_DIM, 20, 40)
        ai_port_rects = self._duel_card_rects(ai.portfolio, 350, 55, small=True)
        for i, rect in enumerate(ai_port_rects):
            sel = ai.portfolio[i] in self.duel_offer_requested
            self._draw_duel_card(ai.portfolio[i], rect.x, rect.y, selected=sel, small=True)

        # AI face-down
        if ai.face_down:
            fd_y = 55 + SMALL_CARD_H + 5
            draw_text(self.screen, "Face Down:", self.font_small, TEXT_DIM, 20, fd_y - 15)
            fd_rects = self._duel_card_rects(ai.face_down, 350, fd_y, small=True)
            for i, rect in enumerate(fd_rects):
                reveal = d.dutch_auction_active or (0 in d.peeked_cards and i in d.peeked_cards[0])
                sel = ai.face_down[i] in self.duel_offer_requested
                if reveal:
                    self._draw_duel_card(ai.face_down[i], rect.x, rect.y, selected=sel, small=True)
                else:
                    self._draw_duel_card(ai.face_down[i], rect.x, rect.y, selected=sel, face_down=True, small=True)

        # ── Middle: Trade floor / action log ──
        mid_y = 210
        pygame.draw.rect(self.screen, BG_PANEL, (20, mid_y, SCREEN_W - 300, 120), border_radius=5)
        pygame.draw.rect(self.screen, (60, 70, 90), (20, mid_y, SCREEN_W - 300, 120), width=1, border_radius=5)

        # Current offer display
        if d.current_offer:
            offer = d.current_offer
            draw_text(self.screen, "TRADE OFFER PENDING", self.font_header, TEXT_GOLD, 30, mid_y + 5)
            offered_names = ', '.join(c.name for c in offer.offered_cards)
            requested_names = ', '.join(c.name for c in offer.requested_cards)
            margin_color = TEXT_GREEN if offer.margin >= 0 else TEXT_RED
            draw_text(self.screen, f"Offering: {offered_names} (${offer.offered_value:.2f})",
                      self.font_small, TEXT_WHITE, 30, mid_y + 30, max_width=SCREEN_W - 360)
            draw_text(self.screen, f"Requesting: {requested_names} (${offer.requested_value:.2f})",
                      self.font_small, TEXT_WHITE, 30, mid_y + 50, max_width=SCREEN_W - 360)
            draw_text(self.screen, f"Margin (offerer profit): ${offer.margin:.2f}",
                      self.font_body, margin_color, 30, mid_y + 72)

            if d.phase == 'respond' and d.current_player_idx == 1:
                # AI made the offer, human (index 0) must respond
                draw_text(self.screen, ">>> ACCEPT or DECLINE this trade! <<<", self.font_header, TEXT_GOLD,
                          30, mid_y + 95)
        else:
            draw_text(self.screen, "Action Log", self.font_small, TEXT_DIM, 30, mid_y + 5)
            recent = self.action_log[-5:]
            for i, line in enumerate(recent):
                clean = line
                draw_text(self.screen, clean, self.font_small, TEXT_WHITE, 30, mid_y + 25 + i * 18,
                          max_width=SCREEN_W - 360)

        # ── Bottom: Human section ──
        human_y = 340
        draw_text(self.screen, f"{human.name}", self.font_header, TEXT_CYAN, 20, human_y)
        draw_text(self.screen, f"Profit: ${human.profit:.2f} / ${d.target_profit:.0f}",
                  self.font_body, TEXT_WHITE, 180, human_y + 4)
        draw_progress_bar(self.screen, 380, human_y + 6, 200, 14, human.profit, d.target_profit, TEXT_GREEN)

        # Human portfolio
        port_y = human_y + 30
        draw_text(self.screen, "Your Portfolio:", self.font_small, TEXT_DIM, 20, port_y)
        port_rects = self._duel_card_rects(human.portfolio, 350, port_y + 15, small=True)
        for i, rect in enumerate(port_rects):
            card = human.portfolio[i]
            sel = card in self.duel_offer_offered
            if not self.duel_offer_mode and i == self.duel_selected_portfolio_idx:
                sel = True
            self._draw_duel_card(card, rect.x, rect.y, selected=sel, small=True)

        # Human face-down
        if human.face_down:
            fd_y = port_y + 15 + SMALL_CARD_H + 5
            draw_text(self.screen, "Your Face-Down:", self.font_small, TEXT_DIM, 20, fd_y - 15)
            fd_rects = self._duel_card_rects(human.face_down, 350, fd_y, small=True)
            for i, rect in enumerate(fd_rects):
                self._draw_duel_card(human.face_down[i], rect.x, rect.y, small=True)

        # Human hand
        hand_y = SCREEN_H - CARD_H - 10
        draw_text(self.screen, f"Hand ({len(human.hand)})", self.font_header, TEXT_WHITE, 20, hand_y - 24)
        hand_rects = self._duel_card_rects(human.hand, 350, hand_y, small=False)
        for i, rect in enumerate(hand_rects):
            card = human.hand[i]
            sel = card in self.duel_offer_offered
            if not self.duel_offer_mode and i == self.duel_selected_hand_idx:
                sel = True
            self._draw_duel_card(card, rect.x, rect.y, selected=sel, small=False)

        # ── Right panel: Action buttons ──
        self._render_duel_actions(mx, my)

        # ── AI thinking overlay ──
        if self.state == 'duel_ai':
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 80))
            self.screen.blit(overlay, (0, 0))
            draw_text(self.screen, "AI is trading...", self.font_title, TEXT_RED,
                      SCREEN_W // 2, SCREEN_H // 2 - 40, center=True)
            for i, action in enumerate(self.ai_action_display[-4:]):
                draw_text(self.screen, action, self.font_body, TEXT_WHITE,
                          SCREEN_W // 2, SCREEN_H // 2 + i * 25, center=True, max_width=600)

    def _render_duel_actions(self, mx, my):
        panel_x = SCREEN_W - 280
        panel_y = 5
        panel_w = 260
        panel_h = SCREEN_H - 15

        pygame.draw.rect(self.screen, BG_PANEL, (panel_x, panel_y, panel_w, panel_h), border_radius=5)
        pygame.draw.rect(self.screen, (60, 70, 90), (panel_x, panel_y, panel_w, panel_h), width=1, border_radius=5)

        d = self.duel
        human = self.duel_human
        ai = self.duel_ai

        draw_text(self.screen, "DUEL ACTIONS", self.font_header, TEXT_GOLD, panel_x + 10, panel_y + 8)

        self._action_button_rects = {}
        btn_w = panel_w - 20
        btn_x = panel_x + 10
        btn_h = 34
        gap = 5
        y = panel_y + 38

        # Check whose turn it is
        is_human_turn = d.current_player_idx == 0 and d.phase != 'respond'
        is_responding = d.phase == 'respond' and d.current_player_idx == 1

        if is_responding:
            # Respond to AI's offer
            buttons = [
                ("Accept Trade", 'duel_accept', False),
                ("Decline Trade", 'duel_decline', False),
            ]
        elif is_human_turn:
            if self.duel_offer_mode:
                buttons = [
                    ("Submit Offer", 'duel_submit_offer', len(self.duel_offer_offered) == 0 or len(self.duel_offer_requested) == 0),
                    ("Cancel Offer", 'duel_cancel_offer', False),
                ]
            else:
                has_hand_sel = self.duel_selected_hand_idx is not None
                has_port_sel = self.duel_selected_portfolio_idx is not None
                # Check if selected card has an activatable ability
                can_use_ability = False
                if has_port_sel and self.duel_selected_portfolio_idx < len(human.portfolio):
                    card = human.portfolio[self.duel_selected_portfolio_idx]
                    can_use_ability = card.can_use_ability()
                elif has_hand_sel and self.duel_selected_hand_idx < len(human.hand):
                    card = human.hand[self.duel_selected_hand_idx]
                    can_use_ability = card.can_use_ability()
                buttons = [
                    ("Play Card to Board", 'duel_play_card', not has_hand_sel),
                    ("Play Face-Down", 'duel_play_facedown', not has_hand_sel),
                    ("Start Trade Offer", 'duel_start_offer', len(human.portfolio) == 0),
                    ("Use Ability", 'duel_use_ability', not can_use_ability),
                    ("End Turn", 'duel_end_turn', False),
                    ("Forfeit", 'duel_forfeit', False),
                ]
        else:
            buttons = []

        for label, name, disabled in buttons:
            hovered = pygame.Rect(btn_x, y, btn_w, btn_h).collidepoint(mx, my) and not disabled
            rect = draw_button(self.screen, btn_x, y, btn_w, btn_h, label,
                               self.font_body, hovered=hovered, disabled=disabled)
            self._action_button_rects[name] = rect
            y += btn_h + gap

        # Status info
        y += 10
        draw_text(self.screen, f"Your Profit: ${human.profit:.2f}", self.font_body, TEXT_GREEN, panel_x + 10, y)
        y += 20
        draw_text(self.screen, f"AI Profit: ${ai.profit:.2f}", self.font_body, TEXT_RED, panel_x + 10, y)
        y += 20
        draw_text(self.screen, f"Target: ${d.target_profit:.0f}", self.font_body, TEXT_GOLD, panel_x + 10, y)
        y += 25

        # Progress bars
        draw_progress_bar(self.screen, panel_x + 10, y, btn_w, 12, human.profit, d.target_profit, TEXT_GREEN)
        y += 18
        draw_progress_bar(self.screen, panel_x + 10, y, btn_w, 12, ai.profit, d.target_profit, TEXT_RED)
        y += 25

        # Phase indicator
        phase_text = {
            'play': "Your Turn - Play & Trade",
            'respond': "Respond to Offer!",
            'game_over': "Game Over",
        }.get(d.phase, d.phase)
        color = TEXT_GOLD if d.phase == 'respond' else TEXT_CYAN
        draw_text(self.screen, phase_text, self.font_small, color, panel_x + 10, y)
        y += 20

        # Offer mode info
        if self.duel_offer_mode:
            draw_text(self.screen, "OFFER MODE:", self.font_small, TEXT_GOLD, panel_x + 10, y)
            y += 16
            draw_text(self.screen, "Click your cards to offer", self.font_tiny, TEXT_DIM, panel_x + 10, y)
            y += 14
            draw_text(self.screen, "Click AI cards to request", self.font_tiny, TEXT_DIM, panel_x + 10, y)
            y += 18
            off_val = sum(c.display_value for c in self.duel_offer_offered)
            req_val = sum(c.display_value for c in self.duel_offer_requested)
            margin = req_val - off_val
            draw_text(self.screen, f"Offering: ${off_val:.2f}", self.font_small, TEXT_WHITE, panel_x + 10, y)
            y += 16
            draw_text(self.screen, f"Requesting: ${req_val:.2f}", self.font_small, TEXT_WHITE, panel_x + 10, y)
            y += 16
            mc = TEXT_GREEN if margin >= 0 else TEXT_RED
            draw_text(self.screen, f"Margin: ${margin:.2f}", self.font_body, mc, panel_x + 10, y)

        # Active effects
        y = panel_y + panel_h - 120
        if human.force_accept:
            draw_text(self.screen, "HOSTILE TAKEOVER active!", self.font_tiny, TEXT_GOLD, panel_x + 10, y)
            y += 14
        if human.leveraged_buyout_active:
            draw_text(self.screen, "LEVERAGED BUYOUT ready!", self.font_tiny, TEXT_GOLD, panel_x + 10, y)
            y += 14
        if human.margin_call:
            draw_text(self.screen, "MARGIN CALL: offer highest!", self.font_tiny, TEXT_RED, panel_x + 10, y)
            y += 14
        if d.dutch_auction_active:
            draw_text(self.screen, "DUTCH AUCTION: cards revealed!", self.font_tiny, TEXT_GOLD, panel_x + 10, y)
            y += 14
        if d.market_crash_target == 0:
            draw_text(self.screen, "MARKET CRASH on you!", self.font_tiny, TEXT_RED, panel_x + 10, y)
            y += 14

    def handle_duel_click(self, mx, my):
        d = self.duel
        human = self.duel_human
        ai = self.duel_ai

        # Check action buttons first
        if hasattr(self, '_action_button_rects'):
            for name, rect in self._action_button_rects.items():
                if rect.collidepoint(mx, my):
                    self._handle_duel_action(name)
                    return

        # Clicking cards
        if d.phase == 'respond' and d.current_player_idx == 1:
            return  # Can only accept/decline when responding

        # Hand cards
        hand_rects = self._duel_card_rects(human.hand, 350, SCREEN_H - CARD_H - 10, small=False)
        for i, rect in enumerate(hand_rects):
            if rect.collidepoint(mx, my):
                card = human.hand[i]
                if self.duel_offer_mode:
                    if card in self.duel_offer_offered:
                        idx = self.duel_offer_offered.index(card)
                        self.duel_offer_offered.pop(idx)
                        self.duel_offer_offered_from_hand.pop(idx)
                    else:
                        self.duel_offer_offered.append(card)
                        self.duel_offer_offered_from_hand.append(True)
                else:
                    self.duel_selected_hand_idx = i if self.duel_selected_hand_idx != i else None
                    self.duel_selected_portfolio_idx = None
                return

        # Portfolio cards
        port_rects = self._duel_card_rects(human.portfolio, 350, 370, small=True)
        for i, rect in enumerate(port_rects):
            if rect.collidepoint(mx, my):
                card = human.portfolio[i]
                if self.duel_offer_mode:
                    if card in self.duel_offer_offered:
                        idx = self.duel_offer_offered.index(card)
                        self.duel_offer_offered.pop(idx)
                        self.duel_offer_offered_from_hand.pop(idx)
                    else:
                        self.duel_offer_offered.append(card)
                        self.duel_offer_offered_from_hand.append(False)
                else:
                    self.duel_selected_portfolio_idx = i if self.duel_selected_portfolio_idx != i else None
                    self.duel_selected_hand_idx = None
                return

        # AI portfolio cards (for requesting)
        ai_port_rects = self._duel_card_rects(ai.portfolio, 350, 55, small=True)
        for i, rect in enumerate(ai_port_rects):
            if rect.collidepoint(mx, my) and self.duel_offer_mode:
                card = ai.portfolio[i]
                if card in self.duel_offer_requested:
                    self.duel_offer_requested.remove(card)
                else:
                    self.duel_offer_requested.append(card)
                return

        # AI face-down cards
        if ai.face_down:
            fd_y = 55 + SMALL_CARD_H + 5
            fd_rects = self._duel_card_rects(ai.face_down, 350, fd_y, small=True)
            for i, rect in enumerate(fd_rects):
                if rect.collidepoint(mx, my) and self.duel_offer_mode:
                    card = ai.face_down[i]
                    if card in self.duel_offer_requested:
                        self.duel_offer_requested.remove(card)
                    else:
                        self.duel_offer_requested.append(card)
                    return

    def _handle_duel_action(self, name):
        d = self.duel
        human = self.duel_human
        ai = self.duel_ai

        if name == 'duel_play_card':
            if self.duel_selected_hand_idx is not None and self.duel_selected_hand_idx < len(human.hand):
                card = human.hand[self.duel_selected_hand_idx]
                result = d.play_card_to_board(card, face_down=False)
                self.action_log.append(result)
                self.duel_selected_hand_idx = None

        elif name == 'duel_play_facedown':
            if self.duel_selected_hand_idx is not None and self.duel_selected_hand_idx < len(human.hand):
                card = human.hand[self.duel_selected_hand_idx]
                result = d.play_card_to_board(card, face_down=True)
                self.action_log.append(result)
                self.duel_selected_hand_idx = None

        elif name == 'duel_start_offer':
            self.duel_offer_mode = True
            self.duel_offer_offered = []
            self.duel_offer_offered_from_hand = []
            self.duel_offer_requested = []
            self.duel_selected_hand_idx = None
            self.duel_selected_portfolio_idx = None
            self.show_message("Offer mode: click your cards to offer, AI cards to request", 3.0)

        elif name == 'duel_cancel_offer':
            self.duel_offer_mode = False
            self.duel_offer_offered = []
            self.duel_offer_offered_from_hand = []
            self.duel_offer_requested = []

        elif name == 'duel_submit_offer':
            offered_cards = self.duel_offer_offered[:]
            requested_cards = self.duel_offer_requested[:]

            if not offered_cards or not requested_cards:
                self.show_message("Need at least 1 offered and 1 requested card!")
                return

            result = d.make_offer(offered_cards, requested_cards)
            self.action_log.append(result)
            self.duel_offer_mode = False
            self.duel_offer_offered = []
            self.duel_offer_offered_from_hand = []
            self.duel_offer_requested = []

            # Human made offer to AI — AI auto-decides
            if d.current_offer and d.phase == 'respond':
                offer = d.current_offer
                opp_margin = -offer.margin  # profit for AI (negative = loss)
                if d.ai_difficulty == 'easy':
                    accept = random.random() < 0.7
                elif d.ai_difficulty == 'medium':
                    accept = opp_margin >= -10.0
                else:
                    accept = opp_margin >= -5.0
                if accept:
                    result = d.accept_offer()
                    self.action_log.append(f"AI: {result}")
                else:
                    result = d.decline_offer()
                    self.action_log.append(f"AI: {result}")
                # After AI responds, end the human's turn
                if not self._check_duel_over():
                    self._start_ai_turn()

        elif name == 'duel_accept':
            result = d.accept_offer()
            self.action_log.append(f"You: {result}")
            if not self._check_duel_over():
                # Human responded to AI's offer — end AI's turn, go to human's turn
                self._end_ai_turn_to_human()

        elif name == 'duel_decline':
            result = d.decline_offer()
            self.action_log.append(f"You: {result}")
            # Human responded to AI's offer — end AI's turn, go to human's turn
            self._end_ai_turn_to_human()

        elif name == 'duel_use_ability':
            card = None
            if self.duel_selected_portfolio_idx is not None and self.duel_selected_portfolio_idx < len(human.portfolio):
                card = human.portfolio[self.duel_selected_portfolio_idx]
            elif self.duel_selected_hand_idx is not None and self.duel_selected_hand_idx < len(human.hand):
                card = human.hand[self.duel_selected_hand_idx]
            if card and card.can_use_ability():
                result = d.use_ability(card)
                self.action_log.append(result)
            else:
                self.show_message("Select a card with an active ability first!")

        elif name == 'duel_end_turn':
            self._start_ai_turn()

        elif name == 'duel_forfeit':
            d.game_over = True
            d.winner = ai
            d.phase = 'game_over'
            d.log.append(f"{human.name} forfeited! {ai.name} wins!")
            self.action_log.append(f"You forfeited! {ai.name} wins!")
            self._check_duel_over()

    def _end_ai_turn_to_human(self):
        """End AI's turn and give control back to human."""
        d = self.duel
        self.duel_selected_hand_idx = None
        self.duel_selected_portfolio_idx = None
        self.duel_offer_offered = []
        self.duel_offer_offered_from_hand = []
        self.duel_offer_requested = []
        self.duel_offer_mode = False
        # End AI's turn
        d.end_turn()
        if self._check_duel_over():
            return
        # Human's turn — draw a card
        self.duel_human.draw(1)
        self.state = 'duel'
        self.ai_display_timer = 0

    def _start_ai_turn(self):
        """End human's turn and start AI's turn."""
        d = self.duel
        human = self.duel_human
        ai = self.duel_ai
        # Clear selection
        self.duel_selected_hand_idx = None
        self.duel_selected_portfolio_idx = None
        self.duel_offer_offered = []
        self.duel_offer_offered_from_hand = []
        self.duel_offer_requested = []
        self.duel_offer_mode = False
        # Only end turn if we're in play phase (not responding to AI's offer)
        if d.phase != 'respond':
            d.end_turn()
        if self._check_duel_over():
            return
        # AI takes turn
        self.state = 'duel_ai'
        self.ai_action_display = d.ai_take_turn(ai)
        self.action_log.extend(self.ai_action_display)
        self.ai_display_timer = 2.5

    def finish_duel_ai_turn(self):
        """Called when AI thinking timer expires."""
        d = self.duel
        if self._check_duel_over():
            return
        # Check if AI made an offer to human and is waiting for response
        if d.current_offer and d.phase == 'respond':
            # Switch to duel state so human can accept/decline
            self.state = 'duel'
            self.ai_display_timer = 0
            self.show_message("AI made you a trade offer!", 2.0)
            return
        # AI already ended its turn in ai_take_turn — just switch to human
        # Don't call end_turn again!
        self.duel_selected_hand_idx = None
        self.duel_selected_portfolio_idx = None
        self.duel_offer_offered = []
        self.duel_offer_offered_from_hand = []
        self.duel_offer_requested = []
        self.duel_offer_mode = False
        # Human's turn — draw a card (only if game not over)
        if not d.game_over:
            self.duel_human.draw(1)
        self.state = 'duel'
        self.ai_display_timer = 0

    def _check_duel_over(self) -> bool:
        if self.duel.game_over:
            self.state = 'duel_gameover'
            return True
        return False

    def render_duel_gameover(self):
        d = self.duel
        if not d:
            return

        overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))

        winner = d.winner
        if winner == self.duel_human:
            draw_text(self.screen, "YOU WIN!", self.font_title, TEXT_GREEN,
                      SCREEN_W // 2, 150, center=True)
        else:
            draw_text(self.screen, f"{winner.name} WINS!", self.font_title, TEXT_RED,
                      SCREEN_W // 2, 150, center=True)

        y = 210
        draw_text(self.screen, f"Rounds: {d.current_round}", self.font_header, TEXT_WHITE,
                  SCREEN_W // 2, y, center=True)
        y += 35
        for p in d.players:
            color = TEXT_GREEN if p == winner else TEXT_DIM
            draw_text(self.screen, f"{p.name}: ${p.profit:.2f} profit",
                      self.font_body, color, SCREEN_W // 2, y, center=True)
            y += 25

        # Winner's portfolio
        y += 20
        draw_text(self.screen, "Winner's Final Portfolio:", self.font_header, TEXT_GOLD,
                  SCREEN_W // 2, y, center=True)
        y += 30
        for card in sorted(winner.portfolio, key=lambda c: c.display_value, reverse=True)[:5]:
            draw_text(self.screen, f"[{card.rarity}] {card.name} - ${card.display_value:.2f}",
                      self.font_body, RARITY_RGB.get(card.rarity, TEXT_WHITE),
                      SCREEN_W // 2, y, center=True)
            y += 22

        # Buttons
        self.menu_buttons = []
        mx, my = pygame.mouse.get_pos()
        btn_w, btn_h = 200, 45
        btns = [
            ("Duel Again", lambda: self.goto_duel_setup()),
            ("Main Menu", lambda: self.goto_menu()),
            ("Quit", lambda: pygame.event.post(pygame.event.Event(pygame.QUIT))),
        ]
        for i, (label, action) in enumerate(btns):
            x = SCREEN_W // 2 - btn_w // 2
            by = y + 30 + i * 55
            hovered = pygame.Rect(x, by, btn_w, btn_h).collidepoint(mx, my)
            rect = draw_button(self.screen, x, by, btn_w, btn_h, label,
                               self.font_header, hovered=hovered)
            self.menu_buttons.append({'rect': rect, 'action': action})


# ==============================================================================
# SECTION: ENTRY POINT
# ==============================================================================

def launch_gui():
    """Launch the pygame graphical client directly."""
    try:
        gui = GameGUI()
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