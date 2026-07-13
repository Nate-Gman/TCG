# The Exchange — Project Overview

## What Is This?

A digital Trading Card Game where every card is a real historical U.S. coin or banknote. Two distinct game modes: a classic purse-building TCG and a trade-battle duel mode.

## Tech Stack

- **Language**: Python 3.10+
- **GUI**: pygame 2.6+
- **Resolution**: 1280x820
- **No external assets** — all rendering is code-based (shapes, text, colors)

## Project Structure

```
TCG/
├── TCG.py            # Core engine: 200+ cards, decks, abilities, AI, save/load
├── TCG_GUI.py        # Pygame GUI for both modes
├── ExchangeDuel.py   # Duel engine: trade offers, profit tracking, utility abilities
├── test_sim.py       # Headless AI vs AI duel simulation
├── Projectgoal.md    # Full design document & historical card reference
├── README.md         # Setup & gameplay instructions
├── saves/            # Saved game files
└── ReferenceCode/    # Reference snippets
```

## Game Modes

### 1. Classic TCG
| Aspect | Detail |
|--------|--------|
| Objective | Reach target purse value before opponent |
| Deck | 45 cards per player |
| Hand | 5 cards, draw 2 per turn |
| Core loop | Play cards → activate abilities → challenge opponent → end turn |
| AI | Easy / Medium / Hard |
| Persistence | Save/load to disk |

### 2. Exchange Duel
| Aspect | Detail |
|--------|--------|
| Objective | Reach profit target before opponent |
| Deck | 20 cards per player (balanced rarities) |
| Board | Portfolio (face-up) + face-down cards |
| Core loop | Play cards → use abilities → make trade offers → end turn |
| Profit | Earned by trading high-value opponent cards for your lower-value cards |
| AI | Easy ($50 target) / Medium ($100) / Hard ($200) |

## Card System

### Rarities (6 tiers)
| Tier | Code | Print % | Value Range |
|------|------|---------|-------------|
| Common | C | 55% | <$0.25 |
| Uncommon | U | 28% | $0.25-$1 |
| Rare | R | 12% | $1-$10 |
| Ultra-Rare | UR | 3.5% | $20-$100 |
| Legendary | L | 1% | $500+ |
| Secret Rare | SR | 0.5% | Special variants |

### Classic TCG Abilities
Value-based multipliers and passive bonuses tied to historical context (e.g., Fort Knox ×1.5 purse, Gold Standard bonuses, inflation resistance).

### Duel Abilities (Utility-Based)
| Category | Abilities |
|----------|-----------|
| Information | Insider Info (peek), Dutch Auction (reveal all) |
| Force | Hostile Takeover (auto-accept), Margin Call (force offer) |
| Protection | Market Lock (protect card), Blue Chip (value locked) |
| Manipulation | Pump & Dump (inflate value), Market Crash (devalue opponent) |
| Profit | Short Sell (bet against), Leveraged Buyout (+$5 bonus), Golden Parachute ($5 on loss) |
| Disruption | Poison Pill (opponent loses $3), Junk Bond (volatile value) |
| Utility | Insider Trade (swap with deck) |

## AI Architecture

### Classic TCG AI
- **Easy**: Random plays, rarely challenges
- **Medium**: Plays high-value cards, challenges when ahead
- **Hard**: Evaluates cards, makes change, challenges aggressively, uses events strategically

### Duel AI
- Generates fair-value trade offers within opponent's acceptance threshold
- Accepts trades based on margin tolerance (Easy: 70% random, Medium: -$10, Hard: -$5)
- Uses abilities based on difficulty level
- Waits for human response when offering (doesn't auto-end turn)

## GUI States

```
menu → setup → playing → gameover
  ↓
duel_setup → duel ↔ duel_ai → duel_gameover
```

## Running

```bash
pip install pygame
python TCG.py        # Launch GUI
python test_sim.py   # Run duel AI simulation
```
