# 短期记忆(会话状态)

> 用法:接班先跑 `python3 agent-bridge/agent/refresh.py` 刷新"实时快照";
> 离开前更新"当前目标/待办"与"上次会话"。本文件可以高频改动,保持真实。

## 实时快照(由 refresh.py 维护,人工不要手改这一节)

<!-- snapshot:start -->

- 刷新时间:2026-10-24 19:46:09
- 桥接:版本 0.4.0,session `7400b8e0-06b0-4db7-a275-a27177460c17`,连接正常,latest_seq 262,commands_sent 10,落盘关,限速 突发3/每3000ms回1。
- 最近画面(最多 8 行,已做行整理):
  - [text] Farliss (wanted): barso = cacca, orc = roc
  - [text] (wanted): Zidane puffs up his chest proudly.
  - [text] Farliss (wanted): nepu = suffelianyways
  - [text] Valkrist (wanted): ogre= master race
  - [text] Morkzar [wanted]: leiffi = bisnismias
  - [text] Arnoldi (wanted): mudari= runkkari
  - [text] Arnoldi (wanted): and now all wankers are quiet :)
  - [text] Eronk (wanted): siggy in game

<!-- snapshot:end -->

## 当前目标 / 待办

- [进行中] 辅助玩家开始正常游玩:用户刚确立"副驾驶"玩法,
  下一步动作等用户指定(候选:story 任务 / 出南门练级 / 逛地图)。
- [待办] Rules 101 已完成,系统提示"通过测试可以升到 21 级"
  (seq 74)——升级与否等用户决定;升级命令待查(先 `help advance`
  或 `help level` 取证再提议)。
- [待办] knowledge/ 的新手攻略尚未中文化;边玩边翻。

## 上次会话做了什么(2026-10-24)

- 实测了限速(连发 6 条:3 过 3 拒;+1.5s 探测 429 retry=1481ms;
  3.1s 间隔稳态全过),确认是精确连续令牌桶。
- 登录取证游戏自动化政策(help robot/flooding/spamming/rules),
  存档 sources/in-game-help/2026-10-24-automation-policy.md,
  提炼 knowledge/automation-policy.md。
- 与用户确认辅助玩法:副驾驶模式(人同意才发命令),
  明确"AI 开小号陪玩"有封号风险,不做。
- 建立本套件(agent/ 目录:fingerprint、记忆、加载说明、refresh)。

## 备注

- 10 条已发命令全部是 help/观察类,无实际游戏后果,审计日志可查
  (~/batclient/agent-bridge/command-log.jsonl)。
