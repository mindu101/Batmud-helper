# Commands and Help

Source: live BatMUD client, help session `f88aa5bf-ff43-4050-a587-2c9dbe15b227`; raw capture: [2026-10-22 help output](../sources/in-game-help/2026-10-22-help.md).

## Confirmed command groups

The base `help` output listed:

- Movement: `n`, `s`, `e`, `w`, `u`, `d`, `exits`, `peer`, `look`, `blook`, `map`.
- Information: `help`, `score`, `sc`, `exp`, `i`, `eq`, `show`, `summary`, `scan`, `exa`, `quests`, `tasks`, `who`, `mudwho`, `finger`, `inform`, `idle`, `robot`.
- Character: `title`, `surname`, `desc`, `password`, `email`, `start`.
- Communication: `say`, `tell`, `whisper`, `shout`, `ignore`, `lite`, `channels`, `report`.
- Feelings: `emote`, `emoteto`, `smile`, `hug`, `bounce`, and others; see `help feelings`.
- Handling: `eat`, `put`, `give`, `get`, `drop`, `keep`, `search`; see `help handling`.
- Combat: `wear`, `wield`, `kill`, `stop`, `parry`, `wimpy`; also `party help`.

**Verified by execution:** `chat hello world` produced `Deepseek [chat]: hello world` in the game output. This confirms that syntax for that message worked in that session; it is a public chat action.

## Help topics observed

The topic index included: abilities, armor, ac, backgrounds, books, boons and banes, caravans, chat channel, city map, continent quests, continents, death, exploring, feelings, ferries, free levels, guild, handling, healing, history, houses, inns, item conditions, levels, magic, money, movement, player cities, quests, quickstart, races, racial guilds, rebirth, reincarnation, rooms, rules, saving items, skills, societies, spells, stats, training, training points, weapons, and more. See the raw capture for the visible list.

## Command directory status

`help topics` began listing commands alphabetically, from `achievements` through `house`, then paused at a pager prompt. The complete command list has **not** been captured yet. Continue with the game's pager or query individual `help <topic>` entries; do not present this excerpt as exhaustive.

The quickstart file documents `hfind <keyword>` as a help-file search (its example is `hfind armours`), `advance cost` as a cost preview, and `advance level` as the level-up action. These syntaxes are help-listed only; `advance level` changes character progression and has not been run during research. The quickstart also describes `touch post` as teleporting to a portal room; it has not been run.

## Syntax and movement

- `help syntax` says object references may take an index number and that `eqnumber` shows inventory indices. Indices depend on internal item order.
- `help movement` documents direction words and abbreviations, multi-room movement with a count up to 20, and `travel` while on roads. Movement commands change location; use `exits` and inspect the destination/context first.
- `help handling` documents shared item selectors for `get`/`take`, `drop`, `put`, and `give`, including `all`, `kept`, `unkept`, item types, numbers, and `except`. These operations can alter inventory; its examples are help text, not actions performed in this session.

Sources: [syntax and movement help](../sources/in-game-help/2026-10-22-movement.md), [handling help](../sources/in-game-help/2026-10-22-handling.md).

## Next help queries

Start with read-only references: `help getting started`, `help syntax`, `help movement`, `help handling`, `help armours`, `help weapons`, `help item conditions`, `help saving items`, `help levels`, and `help training points`. Use `hfind <keyword>` to discover relevant help files. Capture each response before summarizing it.
