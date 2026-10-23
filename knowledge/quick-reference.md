# Quick Reference

Concise context for common questions. These are starting points; consult the linked evidence or game help for exact details.

## Read-only character and room checks

- `look`: inspect current room; `exits`: list exits; `map`: inspect available map.
- `score` / `sc`: character summary; `exp`: experience; `i`: inventory; `eq`: equipment and protection display.
- `help <topic>`: read a help entry; `hfind <word>`: search help entries; `help topics`: browse topic names.
- `quests`, `tasks`, `who`, `mudwho`, `finger`: help-listed information commands; query details with `help <command>`.

## Movement and inventory syntax

- Movement directions include `n`, `s`, `e`, `w`, `u`, `d`; `help movement` describes longer movement forms. Movement changes location.
- `get`, `drop`, `put`, `give`, `wear`, and `wield` can change inventory or equipment. Inspect syntax with `help handling`, `help wear`, or `help wield` before use.
- Item numbers can depend on inventory order; `eqnumber` displays indices. Do not use index-based item actions without inspecting current inventory.

## Evidence-backed notes

- **Armour protection:** `eq` shows protection that reduces damage; racial protection, armour slots and item effectiveness, protection spells, Combat Sense, and incoming damage type affect it. Help documentation only; not combat-tested. Source: [armours help](../sources/in-game-help/2026-10-22-armours.md).
- **Help index:** the visible command list capture ends at `house`; the full alphabetical list is incomplete. Source: [help index](../sources/in-game-help/2026-10-22-help.md).
- **Current character:** inspect `knowledge/character-profile.md`; it is intentionally not assumed current unless dated as verified.
- **Merchant career:** see [merchant-guide.md](merchant-guide.md). Current character has Cha 100, which benefits Bargain, Shopkeeping, and Exchange Money. MiP converts all carried money into experience, so it spends money rather than earning it.
- **Reincarnation goal:** level 17 Orc wants a non-Orc merchant reset. `help recreate` says under 40 levels and under 10 in-game days qualifies for no money/experience tax; current `very young` age makes this plausible, not certain. No merchant skills are trained yet. See [race comparison](../research/race-comparison.md) and [reincarnation notes](../sources/in-game-help/2026-10-22-reincarnation.md).

## Find or fetch detail

Use this page as the compact context entry point. If the notes do not answer a specific question, query the matching in-game `help <topic>` and then update this page and the detailed knowledge file with a concise, sourced result.
