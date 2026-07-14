# The Exchange — Project Overview

## What Is This?

A digital Trading Card Game featuring real historical U.S. coins and banknotes (Classic TCG), a trade-battle duel mode, and a deep Political Arena history mode with 935+ historical figure/event/conspiracy cards spanning centuries of geopolitics.

## Tech Stack

- **Language**: Python 3.10+
- **GUI**: pygame 2.6+
- **Resolution**: Fullscreen (auto-detected from monitor, dynamically scaled UI)
- **No external assets** — all rendering is code-based (shapes, text, colors)

## Project Structure

```
TCG/
├── TCG.py            # Single standalone file: all engines, GUI, card data (8990 lines)
├── test_sim.py       # Headless AI vs AI duel simulation
├── test_hist.py      # History mode tests (card counts, synergies, treasury, AI vs AI)
├── Projectgoal.md    # Full design document & historical card reference
├── README.md         # Setup & gameplay instructions
├── saves/            # Saved game files
└── ReferenceCode/    # Reference snippets
```

## Game Modes

### 1. History Mode (Political Arena)
| Aspect | Detail |
|--------|--------|
| Objective | Reduce opponent's life (influence) to 0 |
| Life | 30 per player |
| Deck | 30 history cards per player (balanced card type mix) |
| Hand | 7 cards, draw 1-2 per turn |
| Board | Max 7 Figures on board |
| Discard | Up to 3 cards per turn (draws replacement) |
| Card Types | Figure (attack/defend), Event (damage+heal), Conspiracy (trap), Scandal (debuff), Organization (passive bonus), Policy (draw bonus) |
| Core loop | Play cards → attack phase → end turn |
| Combat | Power vs Influence — destroy defenders or attack directly |
| Synergies | Cards with matching tags boost each other's PWR & INF |
| Treasury | Playing economic cards earns $ — spend on bonuses ($5 +2 PWR, $8 heal 3, $4 draw card, $6 reveal conspiracy, sacrifice card +$3) |
| AI | Easy (30 rounds) / Medium (25) / Hard (20) — discards weakest cards, plays strategically |
| Help | Press H during gameplay for in-depth help overlay |

### 2. Classic TCG
| Aspect | Detail |
|--------|--------|
| Objective | Reach target purse value before opponent |
| Deck | 45 cards per player |
| Hand | 5 cards, draw 2 per turn |
| Core loop | Play cards → activate abilities → challenge opponent → end turn |
| AI | Easy / Medium / Hard |
| Persistence | Save/load to disk |

### 3. Exchange Duel
| Aspect | Detail |
|--------|--------|
| Objective | Reach profit target before opponent |
| Deck | 20 cards per player (balanced rarities) |
| Board | Portfolio (face-up) + face-down cards |
| Core loop | Play cards → use abilities → make trade offers → end turn |
| Profit | Earned by trading high-value opponent cards for your lower-value cards |
| AI | Easy ($50 target) / Medium ($100) / Hard ($200) |

## History Mode Card System (935+ cards)

### Card Types
| Type | Count | Role |
|------|-------|------|
| Figure | ~340 | Deploy to board — attack with Power, defend with Influence |
| Event | ~176 | One-shot — deal damage to opponent, heal yourself |
| Conspiracy | ~138 | Face-down traps — counter direct attacks |
| Scandal | ~115 | Target an opponent figure — reduce their PWR/INF |
| Organization | ~80 | Passive bonus: +1 PWR/INF to same-org cards |
| Policy | ~86 | Passive bonus: draw 2 cards per turn instead of 1 |

### Rarities (6 tiers)
| Tier | Code | Examples |
|------|------|----------|
| Common | C | Lesser-known figures, minor events |
| Uncommon | U | Notable figures, regional events |
| Rare | R | Major historical figures, significant events |
| Ultra-Rare | UR | Game-changing figures, pivotal events |
| Legendary | L | World-altering figures and events |
| Secret Rare | SR | Special variant cards |

### Synergy System
Cards with matching tags form synergy groups that boost each other's Power and Influence. Examples:
- CIA + FBI + NSA = Intel Network (+PWR +INF)
- Rothschild + Rockefeller + Banker = Old Money (+INF)
- 80+ synergy groups covering intelligence, finance, military, media, energy, and more

## Classic TCG Card System

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

### History Mode AI
- Plays cards strategically based on board state and available resources
- Discards weakest cards when hand is large (keeps best 5)
- Uses treasury to buy power, heal, draw cards, and reveal conspiracies
- Places conspiracy traps, targets with scandals, attacks with figures

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
hist_setup → hist_playing ↔ hist_ai → hist_gameover
  ↓
duel_setup → duel ↔ duel_ai → duel_gameover
```

## Running

```bash
pip install pygame
python TCG.py        # Launch GUI (all 3 game modes, fullscreen)
python test_sim.py   # Run duel AI simulation
python test_hist.py  # Run history mode tests
```
