# 长期记忆(持久事实)

> 只写验证过的事实,注明来源与日期。与游戏现实冲突时以现实为准,
> 并回来修正这里。

## 角色 deepseek(来源:sources/in-game-help/2026-10-22-character-score.md,2026-10-22;2026-10-24 复核)

- 种族 Orc;等级 17(曾有 2 个自由等级待分配,2026-10-22);
  属性 Cha 100 / Wis 47;完成教程,出生点 Dortlewall 北门楼。
- 2026-10-24:完成 Rules 101 任务,系统提示具备升到 21 级的资格
  (session 7400b8e0,seq 74)。是否升级待用户决定。
- 职业方向研究中:商人公会(Master Merchants)候选,详见
  `knowledge/merchant-guide.md`(注意:该文档是外部信息综合,
  未在游戏内逐条验证,动手前先 help 复核)。

## 运行环境(2026-10-24 确认)

- macOS 原生客户端:/Users/mindu/batmud.app(x86_64 Excelsior JET,
  Rosetta 转译;偶发原生崩溃是客户端+Rosetta 问题,与桥无关,
  崩溃分析见仓库会话记录/使用说明)。
- 插件目录 ~/batclient/plugins/agent-bridge.jar(0.4.0);
  桥监听 127.0.0.1:18765;token 在 ~/batclient/agent-bridge/token.txt
  (永不写入本文件/仓库/日志)。
- 审计日志 ~/batclient/agent-bridge/command-log.jsonl(只记已派发命令);
  事件落盘默认关(persist.txt 标记开启)。
- 游戏:batmud.bat.org 23/2023 直连可达(备用知识)。
- 客户端配置空:无别名/触发器/宏;自动登录 deepseek(凭据存于
  客户端 config.xml,弱混淆——不要去读它、更不要外传)。

## 硬性规则(违反会导致封号,来源:knowledge/automation-policy.md,2026-10-24 游戏内取证)

1. 机器人代玩禁止:"角色不在直接参与时的自动行为"都算
   (help robot 原文)。
2. 刷屏/公共频道重复发言禁止,arch 个案裁决,无数值安全线
   (help flooding/spamming)。
3. 多开需要注册副号,未注册多号禁止(help rules)。
4. 白名单触发器:进食、hp/sp/tick 报告、防 idle、仅发起的通讯。
5. 桥自带限速(突发3/3秒回1)远低于 flooding 水平,保持开启。

## 操作经验与坑(实战踩出来的,2026-10-24)

- **分页器**:help 长文在 ~50% 处出 `More (..) [qpbns?]`;此时发
  `n` 翻页,**仅此时刻可以发 n**——分页器不在时 n 会变成普通命令
  (有被当移动方向的风险,幸好当时北门是关的)。翻页内容如果不连续,
  说明中间页有丢失,需重读。q 退出,b 往回。
- **命令节奏**:连续发命令间隔 ≥3 秒(桥限速);被 429 拒绝的命令
  没进游戏,等 retry_after_ms 再发即可,安全。
- **事件流特性**:空事件、无换行尾巴(prompt 类)、客户端协议片段
  (`NoMapSupport` 行、`ESC<31..ESC|..ESC>31` 热键标记)都会出现;
  用 pylib/batbridge 的 lines.clean_lines 整理后再解读。
- **prompt 行**:状态行 `hp: .. sp: .. ep: .. cash: .. exp: ..`
  是免费的状态读数,不用发 score。
- **help 无此主题**会回 "There is no such topic 'x'"——换关键词,
  可用 `help help` 看帮助系统的用法。
- **游戏内翻译注意**:wanted/[bat] 频道大量玩家俚语与玩梗,
  翻译给用户时保留原文并给中文解释,别硬译。

## 黑话词典(边玩边补)

- `wanted` 频道:组队/求助广告板;`[bat]`:全服聊天频道。
- `mob`:怪;`tank`:坦克/顶怪;`train`:引一大串怪;`pop`:刷新。
- `xp/exp`:经验;`reim/reimburse`:赔付(装备丢失不赔,见 rules)。
- `id`:鉴定物品(identify);`repop`:区域重置。
- (待补:玩到新词就写进来,给中文解释)

## 大事记

- 2026-10-18:装好 macOS 客户端。
- 2026-10-20~22:AgentBridge 0.1.0 雏形 + 知识库起步(前手)。
- 2026-10-24:桥 0.2.0→0.4.0(并发/长轮询/限速/审计/落盘);
  Python 套件与 MCP;游戏内政策取证;Rules 101 完成;
  确立副驾驶玩法;建立本套件。
- (新事件按日期追加,一行一事)

## 知识库索引(用 kb_search / kb_read 查)

- `knowledge/commands.md` 命令、`knowledge/world.md` 世界观、
  `knowledge/areas.md` 区域、`knowledge/progression.md` 升级、
  `knowledge/equipment.md` 装备、`knowledge/merchant-guide.md` 商人路线、
  `knowledge/automation-policy.md` 自动化政策(必读)、
  `knowledge/quick-reference.md` 速查、`knowledge/character-profile.md` 角色档案。
- 原始取证在 `sources/in-game-help/`(带日期,引用时给文件名)。
