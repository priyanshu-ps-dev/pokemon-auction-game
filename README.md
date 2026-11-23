# Pokémon Pokédex Data Import & Real-Time Multiplayer Auction Arena

A complete Pokémon database, competitive power ranking engine, and **real-time multiplayer auction/bidding game** for up to 8 players per room.

---

## 🎮 Multiplayer Game Overview

Players compete in real-time to purchase randomly selected Pokémon using a fixed virtual purse ($100,000$ default credits). Each player must assemble a team of **exactly 6 Pokémon**. Once all players complete their teams, the system calculates team strength and declares the tournament winner!

> **This is an auction/draft strategy game, not a Pokémon battle simulator.**

---

## ⚙️ Multiplayer Architecture & Rules

### 1. Multiplayer Rooms
- **Capacity:** Up to 8 players per room (min 2 players to start).
- **Room Codes:** Unique alphanumeric room codes (e.g. `PKMN-8F42`).
- **Player Profiles:** 12 selectable trainer avatars (Red, Blue, Leaf, Ash, Cynthia, Steven, Brendan, May, Ethan, Dawn, Leon, Lyra).
- **Lobby Synchronization:** Real-time player list, Ready status toggles, Host badge.
- **Session Reconnection:** Persistent `session_id` in `localStorage` allows players to reconnect and retain their purse and acquired roster if disconnected.
- **Authoritative Server:** WebSockets on `ws://127.0.0.1:5050/ws` with unified HTTP serving on port `5050`.

### 2. Starting Balance & Bidding Rules
- **Starting Purse:** Configurable by host ($50\text{k}, 100\text{k}, 150\text{k}, 200\text{k}$ credits; default $100,000$).
- **Opening Bid:** $1,000$ credits.
- **Bid Increment:** $500$ credits minimum.
- **Quick Bids:** $+500$, $+1,000$, $+2,000$, $+5,000$.
- **Custom Bid Input:** Enter any valid custom bid.
- **Anti-Self-Bidding:** Players cannot bid against themselves when already holding the highest bid.

### 3. Reserve Budget Rule (Team Completion Protection)
To ensure players never spend their entire purse on early picks and get stranded unable to draft a complete 6-Pokémon team:
$$\text{Max Allowed Bid} = \text{Current Purse} - [(\text{Remaining Empty Slots} - 1) \times \text{Min Bid}]$$
*Example:* A player with $100,000$ credits needing 6 Pokémon ($5$ future slots to reserve after this pick) must retain at least $5 \times 1,000 = 5,000$ credits. Their maximum allowable bid is strictly capped at $95,000$ credits.

### 4. Server-Authoritative 15-Second Timer
- Every Pokémon auction starts with a **15-second countdown**.
- **Anti-Snipe:** Every valid new bid immediately resets the countdown to **15 seconds**.
- Invalid bids never reset the countdown.
- When the timer reaches 0:
  - If bids exist: Highest bidder wins, credits deducted, Pokémon assigned to roster.
  - If no bids exist: Marked **UNSOLD** and removed from the match. Unsold Pokémon never reappear in that room.
- Next Pokémon is automatically selected and broadcast after a 3-second showcase interval.

### 5. Random Pokémon Selection
- Selected server-side and authoritative from the complete 1,351 Pokémon dataset (`data/pokemon_database.json`).
- True random selection without bias; no Pokémon can appear twice in the same room.

### 6. Team Power & Tie-Breaking Rules
Once all players have 6 Pokémon:
$$\text{Team Power} = \sum_{i=1}^6 \text{Power Rating}_i$$
**Tie-Breaking Priority:**
1. Higher Combined Base Stat Total (BST).
2. Higher Highest Individual Pokémon Power Rating.
3. Higher Remaining Purse balance.
4. Declared Tie.

---

## 🚀 Running the System

### 1. Launch Server
```bash
python server.py 5050
```
Open [http://127.0.0.1:5050/](http://127.0.0.1:5050/) in your browser. Open multiple browser tabs/windows or different devices on the local network to play together in real-time!

### 2. Run Automated Multiplayer Integration Tests
```bash
python -u tests/test_multiplayer.py
```
Tests room creation, player joining, ready sync, game start, bidding collisions, reserve budget rule, and timer resets.

### 3. Run Full Match Simulation Test (12 Rounds)
```bash
python -u tests/test_full_match.py
```
Simulates an entire match until both players draft 6 Pokémon, verifies purse deduction, roster limits, team power calculations, tie-breakers, and final victory screen.
