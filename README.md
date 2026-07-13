# The Exchange — Currency Trading Card Game

A digital TCG where every card is a real historical U.S. coin or banknote. Build purses, make change, challenge opponents, and trade your way to fortune.

## Quick Start

```bash
python TCG.py
```

Requires Python 3.10+ and pygame:

```bash
pip install pygame
```

## Game Modes

### Classic TCG (Exchange Mode)
- Build a purse of currency cards through math-based exchanges
- Play cards, activate abilities, challenge opponents
- First to reach target value wins
- AI opponent with Easy / Medium / Hard difficulty
- Save/Load game support

### Exchange Duel (Trade Battle)
- Business battleground: scalp, trade, and profit from margins
- Each player has a portfolio of currency cards on the board
- Make trade offers: offer your cards for opponent's cards
- Profit = their card value - your card value
- Face-down cards add risk/reward (trade blind or reveal with abilities)
- First to reach profit target wins ($50 Easy / $100 Medium / $200 Hard)
- Utility-based card abilities (peek, force trades, protect cards, etc.)

## Files

| File | Description |
|------|-------------|
| `TCG.py` | Core game engine: cards, decks, players, abilities, AI logic |
| `TCG_GUI.py` | Pygame GUI client (1280x820) for both Classic and Duel modes |
| `ExchangeDuel.py` | Duel mode engine: trade offers, profit tracking, utility abilities |
| `test_sim.py` | Headless AI vs AI simulation for duel mode testing |
| `Projectgoal.md` | Game design document and historical card reference |

## Classic TCG — How to Play

### Setup
- Each player gets a 45-card deck built from the card pool
- Start with a starter purse and 5-card hand
- Target value determines game length ($50 short, $500 medium, $1000+ long)

### Turn Structure
1. **Draw** 2 cards
2. **Play cards** to your purse (add their values)
3. **Play events** for disruptive effects
4. **Activate abilities** on purse cards (once per game each)
5. **Challenge** opponent (compare purse values; winner steals a card)
6. **End turn**

### Win Conditions
- First to reach target purse value
- Highest value at end of max rounds
- Bankrupt opponent (purse < $1)

### Card Rarities
| Rarity | Print % | Examples |
|--------|---------|----------|
| Common (C) | 55% | Pennies, nickels, dimes, modern quarters |
| Uncommon (U) | 28% | Half dollars, $1 notes |
| Rare (R) | 12% | Gold coins ($1-$10), silver dollars |
| Ultra-Rare (UR) | 3.5% | $20-$100 notes, key errors |
| Legendary (L) | 1% | $500+, ultra-historic pieces |
| Secret Rare (SR) | 0.5% | Error patterns, proof finishes |

## Exchange Duel — How to Play

### Setup
- Each player gets a 20-card deck with balanced rarities (8C/5U/3R/2UR/1L/1SR)
- Card values scaled by rarity multiplier for meaningful trade margins
- Start with 3 face-down cards and 2 face-up portfolio cards
- Draw 2 cards on first turn, 1 card each subsequent turn

### Turn Structure
1. **Draw** 1 card
2. **Play cards** from hand to portfolio (face-up) or face-down
3. **Use abilities** on cards with active abilities
4. **Make a trade offer**: select your cards to offer + opponent cards to request
   - Opponent accepts or declines based on trade margin
   - Margin = requested value - offered value (positive = good for offerer)
5. **End turn** (or wait for opponent to respond to your offer)

### Duel Card Abilities (Utility-Based)

| Ability | Type | Effect |
|---------|------|--------|
| Insider Info | Active | Peek at 2 of opponent's face-down cards |
| Hostile Takeover | Active | Force opponent to accept your next offer |
| Market Lock | Active | Protect one of your cards from trades this round |
| Margin Call | Active | Opponent must offer their highest card next turn |
| Pump & Dump | Active | Inflate a card's displayed value 50% this round |
| Short Sell | Active | Bet against opponent's card; 30% bonus if it gets traded |
| Insider Trade | Active | Swap a card with the top of your deck |
| Market Crash | Active | Reduce all opponent card values 20% for 1 round |
| Leveraged Buyout | Active | Next accepted trade gains +$5 bonus profit |
| Dutch Auction | Active | Reveal all opponent face-down cards for 1 round |
| Golden Parachute | Passive | Gain $5 compensation on losing trades |
| Poison Pill | Passive | Opponent loses $3 if they trade for this card |
| Blue Chip | Passive | Value locked, immune to Market Crash |
| Junk Bond | Passive | Value fluctuates +/-30% each round |

### Duel AI Behavior
- **Easy**: Accepts most trades, plays randomly, rarely uses abilities
- **Medium**: Accepts trades up to $10 loss, plays mid-value cards, sometimes uses abilities
- **Hard**: Only accepts trades up to $5 loss, plays low cards to trade up, frequently uses abilities

## GUI Controls

- **Click cards** to select them (hand cards for playing, portfolio cards for abilities)
- **Click action buttons** on the right panel to play cards, start offers, use abilities, end turn
- **Offer mode**: Click your cards to offer, click opponent cards to request, then submit
- **Respond mode**: When AI makes you an offer, click Accept or Decline
- **Forfeit** button available during duel play

## Testing

Run the duel AI simulation headlessly:

```bash
python test_sim.py
```

This runs an AI vs AI match and prints round-by-round profits, trade results, and the winner.
