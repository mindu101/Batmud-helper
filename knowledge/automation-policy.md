# BatMUD automation & speed policy (for agent operation)

Verified 2026-10-24 in game (help robot / flooding / spamming / rules;
raw captures: `sources/in-game-help/2026-10-24-automation-policy.md`).

## Hard rules (character can be zapped/deleted/banished)

1. **Robots are forbidden for playing.** "You may not let your character
   on to perform actions when you are not directly involved." Any script
   that reacts to game events, or acts on a schedule, is illegal — that
   is exactly what an unsupervised agent loop would be.
2. **Flooding/spamming is forbidden** — repeated lines on public channels
   or to players, "using triggers, client features, commands". No numeric
   command-rate limit is documented; enforcement is at archwizard whim
   ("on case by case basis"), which is worse than a hard cap.
3. Grey areas: "one arch can allow it and another won't. So maybe better
   not do it."

## Explicitly allowed (from help robot)

- eat/drink maintenance triggers
- hp/sp/tick reporting
- triggers that merely prevent idle-logout
- communication that only *initiates* (party hit reports, answering asks)

## What this means for AgentBridge use

- Every dispatch must be **human-approved or human-driven**: the bridge is
  a hands-on-the-wheel instrument, not an autopilot. No unattended loops,
  no reaction-to-game-event automation, no scheduled in-game actions.
- The bridge's own limiter (burst 3, then 1/3s ≈ 20 commands/min max) sits
  far below any level the game could consider flooding; keep it enabled.
- Never send to public channels from automation. Never repeat commands
  blindly (see `使用说明.txt`: 504 = outcome unknown, do not retry).
- Reading help, looking at rooms, checking score — observation commands —
  are how the agent assists; they were used for this research and drew no
  game-side complaints at bridge-limited rates.
