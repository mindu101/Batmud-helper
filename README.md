# BatMUD AgentBridge

**把 BatMUD 官方客户端变成可编程的本地接口:实时读游戏画面、安全地代发命令,并为 AI 副驾驶提供一整套记忆与工具。**

[English version below](#english)

---

## 中文说明

BatMUD AgentBridge 是一个"人 + AI 副驾驶"共同玩 BatMUD 的完整工具链:一个植入官方客户端的 Java 插件把游戏画面与命令通道暴露为本机 HTTP 接口;Python 工具链与 MCP 服务让任何 AI agent(或脚本、或你自己的终端)以受控、可审计的方式接入;副驾驶套件让任何一个 agent 都能带着同样的记忆与行为规范无缝接班。

### 架构

```
BatMUD 官方客户端(闭源)
 └─ AgentBridge 插件(Java,进程内 HTTP 服务,仅监听 127.0.0.1:18765,令牌鉴权)
     │ HTTP + Bearer Token(支持长轮询、分批、游标)
 ┌───┴────────────────────┬──────────────────┬─────────────┐
 bridge_cli.py 命令行    batbridge Python 库  MCP server    运行时四件套
 (status/read/send/      (client/lines/kb)   (6 个工具,     (翻译窗/地图/
  follow)                                    桌面 agent     看门狗/日记)
                                             直连)
                                                    ↓
                                  agent-bridge/agent/ 副驾驶套件
                                  (指纹 fingerprint、长期/短期记忆、
                                   单词本三层文件、加载说明 AGENTS.md)
```

### 核心功能

**插件(Java,当前 0.4.0)** —— 见 `agent-bridge/src/local/batbridge/AgentBridge.java`
- 事件流:`GET /events?after=&limit=&wait_ms=` 游标式读取游戏输出;长轮询(事件到达立即唤醒)、分批返回(`more` 标记)、2000 条环形缓冲;每事件含纯文本 `text` 与原始 `raw`
- 命令派发:`POST /command` 单行 UTF-8 命令,经客户端解析器(别名/脚本仍生效)
- 限速:令牌桶突发 3 条、每 3 秒回充 1 条;超限 429 并给出 `retry_after_ms`(命令未发出,可安全重试——与 504"结果未知勿重试"严格区分)
- 审计:每条实际派发的命令追加写入 `command-log.jsonl`(时间/命令/游标),被拒绝的不写
- 事件落盘:默认关闭;在 `agent-bridge/` 目录创建 `persist.txt` 空文件即开启(逐行 flush,8MB 轮转)
- 安全:仅回环监听、随机令牌恒定时间比对、拒绝浏览器 Origin、不读任何凭据

**Python 库(`agent-bridge/pylib/batbridge/`)**
- `client.py`:零依赖 HTTP 客户端,异常模型固化桥接契约(429 带 `retry_after_ms`,连接错误给人话提示)
- `lines.py`:行重组与降噪——跨事件碎片拼行、剥离 ANSI/BatClient 热键标记、空行过滤、重复行折叠(保留次数)、行分类(`exits`/`chat`/`room_title?`/`prompt`)
- `kb.py`:对 `knowledge/`、`sources/`、`research/` 笔记做零依赖检索(标题加权),`read` 带路径守卫

**MCP server(`mcp_server.py`)**
- 零依赖手写 MCP stdio(JSON-RPC),Python 3.8 可跑
- 六个工具:`batmud_status` / `batmud_read`(默认输出干净逻辑行)/ `batmud_send`(429/504 语义透传)/ `kb_search` / `kb_read` / `kb_list`
- 已在 `.zcode/config.json` 注册工作区作用域,会话自动连接

**副驾驶套件(`agent-bridge/agent/`)** —— 任何 agent 可加载
- `fingerprint.md` 行为指纹:十条不可协商原则(人同意先于行动、绝不无人值守、不碰公共频道、token 永不外泄……)
- `memory/` 长期记忆(角色/环境/规则/踩坑/黑话词典)、短期记忆(`refresh.py` 一键刷新实时快照)、单词本三层(`vocabulary.md` 完整词条 / `vocabulary.txt` 纯英文释义 / `words.txt` 纯单词列表)
- 仓库根 `AGENTS.md` 是入口:任何 agent 打开仓库即被引导完成接班

**运行时四件套(`agent-bridge/tools/`)**
- `translate_window.py` 双语跟随窗:DeepSeek API 批量翻译游戏画面,状态条本地中文化零成本,行级缓存省 token,API 故障不挡画面
- `mapper.py` 地图:被动记录房间与"走过的边",BFS 寻路支持"带我去某房间"
- `watchdog.py` 看门狗:客户端崩溃/掉线弹 macOS 通知,可选自动拉起客户端
- `diary.py` 每日小结:经验变化、命令统计、新学单词、地图现状、工程提交

### 快速开始

```bash
# 1. 构建插件(需要 JDK;build.sh 自动探测,产物为 Java 8 字节码)
cd agent-bridge && ./build.sh

# 2. 安装:把 agent-bridge.jar 复制到客户端 plugins 目录,重启客户端
#    (macOS 本机路径 ~/batclient/plugins/;令牌自动生成于
#     ~/batclient/agent-bridge/token.txt)

# 3. 命令行
python3 bridge_cli.py status
python3 bridge_cli.py read --after 0 --limit 100
python3 bridge_cli.py send look --wait 3
python3 bridge_cli.py follow

# 4. 测试(harness 在 18766 端口,游戏客户端开着也能跑)
python3 tests/test_bridge.py     # 插件集成(Java harness)
python3 tests/test_lines.py      # 行重组
python3 tests/test_kb.py         # 知识库检索
python3 tests/test_client.py     # Python 客户端
python3 tests/test_mcp_server.py # MCP 全链路
python3 tests/test_translate.py tests/test_mapper.py tests/test_watchdog.py tests/test_diary.py
```

### 安全与游戏政策

- 所有接口仅本机回环,端口不要映射公网
- BatMUD 官方政策(游戏内取证,见 `knowledge/automation-policy.md`):机器人代玩被禁止;本项目定位是"人握方向盘的副驾驶"——每条游戏命令须经人同意,不做无人值守自动化
- 内置限速远低于任何刷屏水平;审计日志让 agent 的每个动作可回放

### 仓库结构

```
agent-bridge/            插件源码、构建、CLI、测试
  ├─ src/…/AgentBridge.java   插件(0.4.0)
  ├─ pylib/batbridge/         Python 库(lines/kb/client/mcp_server)
  ├─ tools/                   运行时四件套(翻译窗/地图/看门狗/日记)
  ├─ agent/                   副驾驶套件(指纹/记忆/单词本/AGENTS.md)
  └─ tests/                   全部测试
knowledge/               精炼游戏知识(中文/英文笔记)
sources/in-game-help/    游戏内 help 原始捕获(带日期)
research/                研究记录
AGENTS.md                agent 接班入口
```

---

## English

**Turn the official BatMUD client into a programmable local interface: read live game output, dispatch commands safely, and give AI co-pilots a full memory and toolbox.**

BatMUD AgentBridge is a complete toolchain for playing BatMUD with a "human + AI co-pilot": a Java plugin embedded in the official client exposes the game stream and command channel over localhost HTTP; a Python toolkit and an MCP server let any AI agent (or script, or your terminal) connect in a controlled, auditable way; and a portable co-pilot kit lets any agent take over seamlessly with the same memories and rules of conduct.

### Architecture

```
BatMUD official client (closed-source)
 └─ AgentBridge plugin (Java, in-process HTTP server, 127.0.0.1:18765 only, token auth)
     │ HTTP + Bearer token (long-poll, batching, cursors)
 ┌───┴────────────────────┬──────────────────┬─────────────┐
 bridge_cli.py           batbridge Python    MCP server    Runtime tools
 (status/read/send/      library             (6 tools,     (translate window/
  follow)                (client/lines/kb)   desktop-      mapper/watchdog/
                                             agent ready)  diary)
                                                    ↓
                              agent-bridge/agent/ co-pilot kit
                              (fingerprint, long/short-term memory,
                               3-layer vocabulary, AGENTS.md loader)
```

### Features

**Plugin (Java, v0.4.0)** — `agent-bridge/src/local/batbridge/AgentBridge.java`
- Event stream: `GET /events?after=&limit=&wait_ms=` cursor-based reads with long-polling (wakes on arrival), batched responses (`more` flag), 2000-event ring buffer; each event carries clean `text` and raw `raw`
- Command dispatch: `POST /command`, single-line UTF-8, through the client parser (aliases/scripts still apply)
- Rate limiting: token bucket — burst 3, then 1 per 3 s; 429 carries `retry_after_ms` (command NOT sent, safe to retry — strictly distinct from 504 "outcome unknown, never retry blindly")
- Audit log: every dispatched command appended to `command-log.jsonl`; rejected ones never logged
- Optional persistence: off by default; create an empty `persist.txt` in the `agent-bridge/` dir to enable (line-flushed JSONL, rotates at 8 MB)
- Security: loopback-only bind, random token with constant-time compare, browser-Origin rejected, no credentials read

**Python library** — `agent-bridge/pylib/batbridge/`
- `client.py`: dependency-free HTTP client whose error model encodes the bridge contract (429 exposes `retry_after_ms`; connection failures get human-readable hints)
- `lines.py`: reassembly & noise filtering — joins cross-event fragments, strips ANSI/BatClient hotkey markup, drops empty lines, collapses repeats (keeping counts), classifies lines (`exits` / `chat` / `room_title?` / `prompt`)
- `kb.py`: dependency-free search over `knowledge/`, `sources/`, `research/` notes (title boost) with path-guarded `read`

**MCP server** — `mcp_server.py`
- Hand-written MCP stdio (JSON-RPC) with zero dependencies; runs on Python 3.8
- Six tools: `batmud_status` / `batmud_read` (clean logical lines by default) / `batmud_send` (429/504 semantics preserved) / `kb_search` / `kb_read` / `kb_list`
- Registered at workspace scope in `.zcode/config.json`; auto-connects in sessions

**Co-pilot kit** — `agent-bridge/agent/` (loadable by any agent)
- `fingerprint.md`: behavioral fingerprint with ten non-negotiable rules (human approval before action, never unattended, never touch public channels, tokens never leave the machine, …)
- `memory/`: long-term memory (character, environment, rules, pitfalls, jargon glossary), short-term memory (`refresh.py` snapshots live state), and a 3-layer vocabulary notebook (`vocabulary.md` full entries / `vocabulary.txt` English-only definitions / `words.txt` bare word list)
- Repo-root `AGENTS.md` is the entry point that onboards any agent

**Runtime tools** — `agent-bridge/tools/`
- `translate_window.py`: bilingual follow window — batch translation via the DeepSeek API, status bar localized for free, per-line cache to save tokens, API outages never block the view
- `mapper.py`: passively records rooms and traversed edges; BFS routing for "take me to room X"
- `watchdog.py`: macOS notifications when the client crashes or the game link drops; optional auto-relaunch
- `diary.py`: daily digest — XP delta, command stats, new words, map size, commits

### Quick start

```bash
# 1. Build the plugin (needs a JDK; build.sh auto-detects, emits Java-8 bytecode)
cd agent-bridge && ./build.sh

# 2. Install: copy agent-bridge.jar into the client's plugins dir and restart it
#    (macOS: ~/batclient/plugins/; token auto-generated at
#     ~/batclient/agent-bridge/token.txt)

# 3. CLI
python3 bridge_cli.py status
python3 bridge_cli.py read --after 0 --limit 100
python3 bridge_cli.py send look --wait 3
python3 bridge_cli.py follow

# 4. Tests (harness runs on port 18766 — safe while the game client is open)
python3 tests/test_bridge.py     # plugin integration (Java harness)
python3 tests/test_lines.py      # line reassembly
python3 tests/test_kb.py         # knowledge search
python3 tests/test_client.py     # Python client
python3 tests/test_mcp_server.py # MCP end-to-end
python3 tests/test_translate.py tests/test_mapper.py tests/test_watchdog.py tests/test_diary.py
```

### Safety & game policy

- Everything binds to loopback only; never expose the port
- BatMUD's in-game policy (captured from `help robot`/`flooding`/`spamming`, see `knowledge/automation-policy.md`) forbids robot-play. This project is a hands-on-the-wheel co-pilot: every game command requires human approval; no unattended automation
- Built-in rate limits sit far below flooding thresholds; the audit log makes every agent action replayable

### Repository layout

```
agent-bridge/            plugin source, build, CLI, tests
  ├─ src/…/AgentBridge.java   the plugin (v0.4.0)
  ├─ pylib/batbridge/         Python library (lines/kb/client/mcp_server)
  ├─ tools/                   runtime tools (translate/mapper/watchdog/diary)
  ├─ agent/                   co-pilot kit (fingerprint/memories/vocab/AGENTS.md)
  └─ tests/                   all tests
knowledge/               curated game knowledge notes
sources/in-game-help/    dated raw captures from the in-game help system
research/                research log
AGENTS.md                agent onboarding entry point
```
