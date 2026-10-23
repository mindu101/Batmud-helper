# Batmud-helper

This is the working directory for the BatMUD AgentBridge and its growing game knowledge base.

## Layout

- `agent-bridge/`: bridge source, packaged plugin, CLI, and tests.
- `knowledge/`: curated reference notes for commands, world, areas, equipment, progression, and tactics.
- `sources/in-game-help/`: dated captures taken from the live game's own help system.
- `research/`: exploration log, open questions, and future research plans.

## Evidence rules

- **Verified in game** means the game returned the result in the current or a recorded session.
- **Help-listed** means a topic or command appeared in the in-game help index; it does not prove every detail of behavior.
- **Observed** means seen in a room, item, character sheet, or event, with the date and context recorded.
- **Unverified** means a hypothesis or external claim that still needs checking in game.

Keep raw output and its session/event cursor in `sources/`. Put concise explanations and links to evidence in `knowledge/`. Mark stale character or balance details with the date they were checked.

## Research order

1. Finish the help topic and command indexes; read `getting started`, `quickstart`, parser, movement, handling, combat, and equipment help.
2. Record the character's race, guilds, skills, spells, stats, equipment, and current goals.
3. Build a map and travel notes from room descriptions and exits, without guessing unseen connections.
4. Document equipment and progression from inspected items, score/experience output, and training help.
5. Turn repeatable, tested routes and combat methods into guides with prerequisites, risks, and evidence.

## Current boundary

The bridge can read client output and submit commands. A successful dispatch only means the client accepted a command; verify the resulting game output. Treat movement, combat, trades, money, inventory changes, and public messages as real game actions. Do not issue those during research unless the user requested that action or the step has been explicitly agreed.
