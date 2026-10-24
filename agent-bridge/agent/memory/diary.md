# 游玩日记

> 由 tools/diary.py 生成,同一天重跑会覆盖当天小节。

## 2026-10-24

- 发出命令 25 条(去重 8 种):look、help policy、help rules、help robot、n、help flooding、help cheating、help spamming
- 学单词 1 个:portcullis
- 地图:共 0 个房间、0 条走过的边
- 工程进展(32 个提交):
  - 89bcce9 Fix room-title misdetection across read-batch boundaries
  - 5388dc7 Docs: sync README and 使用说明 with 12 MCP tools and runtime six-pack
  - cf55d67 Add kit_sync: auto-commit and push memories at session end
  - c4eea66 MCP server: add vocab/map/state/diary/find_word tools (now 12 tools)
  - 8a3d9e7 Translate window: token savings, glossary injection, usage tracking
  - 14f7f5e Add shared game state tracking (hp/sp/ep/cash/exp + current room)
  - 393cb25 Add batbridge.vocab: shared three-layer vocabulary writer + glossary
  - 228ae0a Rewrite README as a comprehensive bilingual (中文/English) project overview
  - d1a50b4 Revert "translate_window: Chinese-only output with blank line separators"
  - 42e9dce Ignore macOS .DS_Store
  - 6f27e2e translate_window: Chinese-only output with blank line separators
  - 05c5d65 Switch translation to deepseek-flash and harden HTTPS CAs
  - b06a0fb Fix diary test expectation: appending an older date is correct order
  - f0a9292 Add daily diary: one-command session digest
  - cbcf9f2 Add disconnect watchdog with macOS notifications
  - 1c83b23 Add room mapper with pathfinding for "take me to room X"
  - 86ab1e0 Add bilingual follow window powered by DeepSeek API
  - 4583073 Add words.txt: bare English word list as third vocabulary artifact
  - 5226e44 Add English-only vocabulary.txt companion to the word book
  - 57b2214 Add vocabulary notebook feature to the co-pilot kit
  - b3cec7a Add portable co-pilot agent kit (fingerprint + memories + loader)
  - 54e837a Add in-game automation/speed policy research (help robot/flooding/spamming)
  - 931c147 Add opt-in event persistence (0.4.0), default off
  - 1c91c39 Register batmud MCP server at workspace scope (auto-connects in this project)
  - a61ec26 Add MCP stdio server exposing bridge and knowledge base as agent tools
  - e5cc3e4 Add BridgeClient Python library for the bridge HTTP API
  - afa0599 Add knowledge note search (batbridge.kb) with guarded read CLI
  - 1dc156e Add Python line reassembly and noise filtering layer (batbridge.lines)
  - 84ad41a Add command rate limiting and audit log (0.3.0)
  - 5879493 Revert "Fix skill name spelling in merchant guide: lumberjacking -> lumber jacking"
  - be097c8 Fix skill name spelling in merchant guide: lumberjacking -> lumber jacking
  - ead8123 Upgrade AgentBridge to 0.2.0: concurrent connections, long-poll, batched reads