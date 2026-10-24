#!/usr/bin/env python3
"""掉线看门狗:盯着桥和游戏连接,异常时弹 macOS 通知。

用法(开个终端跑着,或加 & 放后台):
    python3 agent-bridge/tools/watchdog.py
    python3 agent-bridge/tools/watchdog.py --relaunch   # 客户端没了自动重启它

状态机:
    ok          桥可达且游戏已连接
    game_down   桥可达,但游戏服务器断开(客户端活着,点它重连/重新登录)
    bridge_down 桥不可达(客户端退出或崩溃了)
只在状态**变化**时通知,不刷屏;恢复上线也会通知一声。
--relaunch 仅在 bridge_down 时执行 open 客户端,一集掉线只拉起一次;
不自动做任何游戏内操作(角色是否继续玩由用户决定)。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pylib'))

from batbridge.client import BridgeClient, BridgeConnectionError

CLIENT_APP = '/Users/mindu/batmud.app'
OK, GAME_DOWN, BRIDGE_DOWN = 'ok', 'game_down', 'bridge_down'


def notify(title, message):
    """macOS 通知中心;AppleScript 字符串做最小转义。"""
    escaped = message.replace('\\', '\\\\').replace('"', '\\"')
    t = title.replace('"', '\\"')
    try:
        subprocess.run(['osascript', '-e',
                        'display notification "%s" with title "%s"' % (escaped, t)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    except Exception:
        pass  # 通知失败不影响看门狗


def check(client):
    """探测当前状态。"""
    try:
        st = client.status()
    except (BridgeConnectionError, OSError):
        return BRIDGE_DOWN
    return OK if st.get('connected') else GAME_DOWN


MESSAGES = {
    BRIDGE_DOWN: ('BatMUD 看门狗', '桥不可达:客户端退出或崩溃了。'
                  + ('正在自动重启客户端…' if False else '可重启客户端后自动恢复。')),
    GAME_DOWN: ('BatMUD 看门狗', '游戏服务器连接断了(客户端还开着)。'
                '去客户端里重新连接/登录。'),
    OK: ('BatMUD 看门狗', '恢复正常,游戏已连接。'),
}


def run_watch(check_fn, notifier=notify, relaunch=False, interval=5.0,
              sleep=time.sleep, stop=None, launcher=None):
    """主循环;全部依赖可注入。返回状态转移历史(测试用)。"""
    launcher = launcher or (lambda: subprocess.run(['open', CLIENT_APP],
                                                   stdout=subprocess.DEVNULL))
    state = None
    relaunched_this_episode = False
    history = []
    while stop is None or not stop():
        new = check_fn()
        if new != state:
            history.append((new, relaunch and new == BRIDGE_DOWN))
            title, msg = MESSAGES[new]
            if relaunch and new == BRIDGE_DOWN and not relaunched_this_episode:
                msg += ' 正在自动重启客户端…'
                launcher()
                relaunched_this_episode = True
            if new != BRIDGE_DOWN:
                relaunched_this_episode = False
            notifier(title, msg)
            sys.stderr.write('[%s] %s: %s\n' % (time.strftime('%H:%M:%S'), new, msg))
            state = new
        sleep(interval)
    return history


def main():
    ap = argparse.ArgumentParser(description='BatMUD 掉线看门狗')
    ap.add_argument('--relaunch', action='store_true',
                    help='桥不可达时自动 open 客户端(默认只通知)')
    ap.add_argument('--interval', type=float, default=5.0, help='探测间隔秒(默认 5)')
    a = ap.parse_args()
    client = BridgeClient()
    print('看门狗已启动(每 %.0f 秒探测;Ctrl-C 退出)%s'
          % (a.interval, ';bridge_down 时自动拉起客户端' if a.relaunch else ''))
    try:
        run_watch(lambda: check(client), relaunch=a.relaunch, interval=a.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
