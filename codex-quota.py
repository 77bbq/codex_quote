#!/usr/bin/env python3
"""Show ChatGPT Codex rate-limit snapshots using the local Codex app server."""
import argparse
import datetime
import json
import math
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time


class QuotaError(Exception):
    pass


def fetch_limits(command, timeout, cancel_event=None):
    """Perform the documented JSON-RPC handshake and read a fresh snapshot."""
    try:
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                errors='replace', bufsize=1, start_new_session=True)
    except FileNotFoundError:
        raise QuotaError('找不到 codex；请确认已安装并在 PATH 中，或使用 --codex 指定路径。')
    except OSError as exc:
        raise QuotaError('无法启动 codex：{}'.format(exc))

    lines = queue.Queue()

    def reader():
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            # Only this thread closes the stream: another thread may otherwise
            # block forever acquiring its read lock while a descendant has it open.
            proc.stdout.close()
            lines.put(None)

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()
    deadline = time.monotonic() + timeout

    def send(message):
        try:
            proc.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            proc.stdin.flush()
        except (OSError, BrokenPipeError):
            raise QuotaError('Codex app-server 提前退出；请检查 Codex 版本。')

    def receive(request_id):
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise QuotaError('查询已取消。')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise QuotaError('请求超时；请检查网络、登录状态，或增大 --timeout。')
            try:
                line = lines.get(timeout=min(remaining, 0.2) if cancel_event is not None else remaining)
            except queue.Empty:
                if cancel_event is not None:
                    continue
                raise QuotaError('请求超时；请检查网络、登录状态，或增大 --timeout。')
            if line is None:
                raise QuotaError('Codex app-server 提前退出；请检查 Codex 版本和登录状态。')
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict) or message.get('id') != request_id:
                continue
            if 'error' in message:
                error = message['error']
                detail = error.get('message', str(error)) if isinstance(error, dict) else str(error)
                raise QuotaError('Codex 返回错误：{}。请确认使用 ChatGPT 账号登录且 Codex 版本支持用量查询。'.format(detail))
            if not isinstance(message.get('result'), dict):
                raise QuotaError('Codex 返回了无法识别的结果，请检查 Codex 版本。')
            return message['result']

    try:
        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {
            'name': 'codex_quota', 'title': 'Codex Quota', 'version': '1.0.0'}}})
        receive(1)
        send({'method': 'initialized'})
        send({'id': 2, 'method': 'account/rateLimits/read'})
        return receive(2)
    finally:
        # Codex can be a launcher which spawns a native app-server. Its children
        # inherit our pipes, so cleaning only the launcher can hang the reader.
        # The new session gives this query an exclusive process group to own.
        def signal_group(signum):
            try:
                os.killpg(proc.pid, signum)
                return True
            except ProcessLookupError:
                return False

        signal_group(signal.SIGTERM)
        cleanup_deadline = time.monotonic() + 2
        while time.monotonic() < cleanup_deadline:
            proc.poll()  # Reap an exited group leader before checking the group.
            if not signal_group(0):
                break
            time.sleep(.02)
        # Run even if the launcher exited: native descendants may ignore TERM.
        signal_group(signal.SIGKILL)
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        proc.stdin.close()
        reader_thread.join(timeout=1)


def snapshots(result):
    buckets = result.get('rateLimitsByLimitId')
    if isinstance(buckets, dict) and buckets:
        return [(str(k), v) for k, v in sorted(buckets.items()) if isinstance(v, dict)]
    legacy = result.get('rateLimits')
    if isinstance(legacy, dict):
        return [(str(legacy.get('limitId') or 'codex'), legacy)]
    return []


def remaining(window):
    used = finite_number(window.get('usedPercent'))
    if used is None:
        return None
    return max(0.0, min(100.0, 100.0 - used))


def finite_number(value):
    """Accept JSON numbers only, excluding booleans and float overflow."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def display_timestamp(value):
    value = finite_number(value)
    if value is not None:
        try:
            datetime.datetime.fromtimestamp(value, datetime.timezone.utc).astimezone()
            return value
        except (ValueError, OverflowError, OSError):
            pass
    return None


def json_snapshot(result):
    """Build the versioned display-only contract, with unknown values as null."""
    buckets = []
    known = []
    for key, bucket in snapshots(result):
        windows = []
        for window_id in ('primary', 'secondary'):
            window = bucket.get(window_id)
            if not isinstance(window, dict):
                continue
            amount = remaining(window)
            if amount is not None:
                known.append(amount)
            duration = finite_number(window.get('windowDurationMins'))
            windows.append({'id': window_id, 'remaining': amount,
                            'durationMins': duration if duration is not None and duration > 0 else None,
                            'resetsAt': display_timestamp(window.get('resetsAt'))})
        credits = bucket.get('credits')
        if isinstance(credits, dict):
            balance = credits.get('balance')
            credits = {
                'balance': balance if isinstance(balance, str) else finite_number(balance),
                'hasCredits': credits.get('hasCredits') if isinstance(credits.get('hasCredits'), bool) else None,
                'unlimited': credits.get('unlimited') if isinstance(credits.get('unlimited'), bool) else None,
            }
        else:
            credits = None
        name = bucket.get('limitName')
        buckets.append({'id': key, 'name': name if isinstance(name, str) and name else key,
                        'windows': windows, 'credits': credits})
    if not buckets:
        raise QuotaError('服务没有返回可显示的额度数据。')
    reset = result.get('rateLimitResetCredits')
    reset = finite_number(reset.get('availableCount')) if isinstance(reset, dict) else None
    return {'schemaVersion': 1,
            'updatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'summaryRemaining': min(known) if known else None,
            'buckets': buckets,
            'resetCredits': reset if reset is not None and reset >= 0 else None}


def run_json(args):
    """Cancel cooperatively so fetch_limits reaps app-server before we exit."""
    cancel_event = threading.Event()
    previous_handlers = {}

    def cancel(signum, frame):
        cancel_event.set()

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, cancel)
        result = fetch_limits([args.codex, 'app-server'], args.timeout, cancel_event=cancel_event)
        if cancel_event.is_set():
            raise QuotaError('查询已取消。')
        document = json.dumps(json_snapshot(result), ensure_ascii=False, allow_nan=False)
        print(document, flush=True)
        return 0
    except QuotaError as exc:
        print('查询失败：{}'.format(exc), file=sys.stderr, flush=True)
        return 1
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def percent(number):
    return '{:g}%'.format(number)


def format_limits(result):
    buckets = snapshots(result)
    if not buckets:
        raise QuotaError('服务没有返回可显示的额度数据。')
    lines = ['Codex 订阅用量（以服务返回为准）']
    for key, bucket in buckets:
        label = bucket.get('limitName') or key
        lines.append('\n[{}]'.format(label))
        found_window = False
        for name, cn in [('primary', '窗口 1'), ('secondary', '窗口 2')]:
            window = bucket.get(name)
            if not isinstance(window, dict):
                continue
            found_window = True
            amount = remaining(window)
            duration = window.get('windowDurationMins')
            span = '{} 分钟'.format(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else '时长未知'
            resets = window.get('resetsAt')
            reset = '未知'
            if isinstance(resets, (int, float)) and not isinstance(resets, bool):
                try:
                    reset = datetime.datetime.fromtimestamp(resets).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
                except (ValueError, OverflowError, OSError):
                    pass
            lines.append('  {}（{}）：剩余 {}，重置时间 {}'.format(cn, span, percent(amount) if amount is not None else '未知', reset))
        if not found_window:
            lines.append('  暂无窗口数据')
        credits = bucket.get('credits')
        if isinstance(credits, dict):
            # Preserve the server's reported value; no currency or unit is assumed.
            lines.append('  Credits 余额（服务原值）：{}'.format(credits.get('balance') if credits.get('balance') is not None else '未知'))
            if credits.get('unlimited') is True:
                lines.append('  Credits：服务标记为无限')
            if isinstance(credits.get('hasCredits'), bool):
                lines.append('  Credits 可用：{}'.format('是' if credits['hasCredits'] else '否'))
    resets = result.get('rateLimitResetCredits')
    if isinstance(resets, dict) and resets.get('availableCount') is not None:
        lines.append('\n可用的额度重置次数：{}'.format(resets['availableCount']))
    return '\n'.join(lines)


def low_windows(result, threshold):
    low = []
    for key, bucket in snapshots(result):
        for name in ('primary', 'secondary'):
            window = bucket.get(name)
            if isinstance(window, dict):
                amount = remaining(window)
                if amount is not None and amount <= threshold:
                    low.append((key, name, amount))
    return low


def positive_float(value):
    try:
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            raise ValueError()
        return number
    except ValueError:
        raise argparse.ArgumentTypeError('请输入大于 0 的数字')


def threshold_value(value):
    try:
        number = float(value)
        if not math.isfinite(number) or not 0 <= number <= 100:
            raise ValueError()
        return number
    except ValueError:
        raise argparse.ArgumentTypeError('请输入 0 到 100 之间的数字')


def main():
    parser = argparse.ArgumentParser(description='显示 ChatGPT 登录的 Codex 额度；不显示 API 美元余额。')
    parser.add_argument('--codex', default='codex', help='codex 可执行文件路径（默认使用 PATH）')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--watch', type=positive_float, metavar='秒', help='按指定秒数持续刷新，例如 --watch 60')
    mode.add_argument('--json', action='store_true', help='单次查询并输出严格 JSON，供顶部栏扩展使用')
    parser.add_argument('--timeout', type=positive_float, default=20, metavar='秒', help='单次查询超时（默认 20 秒）')
    parser.add_argument('--notify', action='store_true', help='低于阈值时调用 notify-send（需桌面会话）')
    parser.add_argument('--threshold', type=threshold_value, default=20, metavar='百分比', help='通知阈值，剩余小于或等于此值时提醒（默认 20）')
    args = parser.parse_args()
    if args.json:
        return run_json(args)
    if args.notify and shutil.which('notify-send') is None:
        print('提示：找不到 notify-send，桌面通知不可用；终端显示仍会继续。', file=sys.stderr)
    notified = set()
    try:
        while True:
            try:
                result = fetch_limits([args.codex, 'app-server'], args.timeout)
                print('\n查询时间：{}'.format(datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')))
                print(format_limits(result), flush=True)
                low = low_windows(result, args.threshold)
                current = {(key, name) for key, name, _ in low}
                fresh = [(key, name, amount) for key, name, amount in low if (key, name) not in notified]
                if args.notify and fresh and shutil.which('notify-send'):
                    summary = '；'.join('{} {} 剩余 {}'.format(key, name, percent(amount)) for key, name, amount in fresh)
                    try:
                        proc = subprocess.run(['notify-send', 'Codex 额度提醒', summary], timeout=3, check=False)
                        if proc.returncode != 0:
                            print('提示：桌面通知发送失败，请检查桌面会话。', file=sys.stderr)
                    except (OSError, subprocess.TimeoutExpired):
                        print('提示：桌面通知发送失败，请检查桌面会话。', file=sys.stderr)
                notified = current
            except QuotaError as exc:
                print('查询失败：{}'.format(exc), file=sys.stderr, flush=True)
                if not args.watch:
                    return 1
            if not args.watch:
                return 0
            time.sleep(args.watch)
    except KeyboardInterrupt:
        print('\n已停止。')
        return 0


if __name__ == '__main__':
    sys.exit(main())
