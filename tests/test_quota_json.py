"""JSON helper integration tests using a local fake executable, never an account."""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'codex-quota.py'


class JsonQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.codex = self.directory / 'fake codex'
        self.pid_file = self.directory / 'server.pid'

    def fake_codex(self, result=None, mode='ok'):
        # The fake validates the same handshake as app-server, without credentials.
        source = '''#!{python}
import json, os, pathlib, sys, time
assert sys.argv[1:] == ['app-server']
pathlib.Path({pid!r}).write_text(str(os.getpid()))
if {mode!r} == 'hang':
    time.sleep(30)
    sys.exit(0)
init = json.loads(sys.stdin.readline())
assert init['id'] == 1 and init['method'] == 'initialize'
print(json.dumps({{'id': 1, 'result': {{}}}}), flush=True)
ready = json.loads(sys.stdin.readline())
assert ready['method'] == 'initialized' and 'id' not in ready
read = json.loads(sys.stdin.readline())
assert read['id'] == 2 and read['method'] == 'account/rateLimits/read'
if {mode!r} == 'error':
    response = {{'id': 2, 'error': {{'message': 'fake authentication error'}}}}
else:
    response = {{'id': 2, 'result': json.loads({payload!r})}}
print(json.dumps(response), flush=True)
'''.format(python=sys.executable, pid=str(self.pid_file), mode=mode,
           payload=json.dumps(result if result is not None else {}))
        self.codex.write_text(source, encoding='utf-8')
        self.codex.chmod(0o755)

    def run_cli(self, *arguments):
        return subprocess.run([sys.executable, str(HELPER), '--codex', str(self.codex),
                               '--timeout', '3'] + list(arguments),
                              capture_output=True, text=True, timeout=8)

    def read_snapshot(self, result):
        self.fake_codex(result)
        process = self.run_cli('--json')
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual('', process.stderr)
        def invalid_constant(value):
            self.fail('Nonstandard JSON constant: ' + value)
        return json.loads(process.stdout, parse_constant=invalid_constant)

    def test_multiple_buckets_report_lowest_known_window_and_schema(self):
        data = self.read_snapshot({'rateLimitsByLimitId': {
            'extra': {'limitName': 'Extra', 'secondary': {
                'usedPercent': 58, 'windowDurationMins': 10080, 'resetsAt': 1893456000}},
            'codex': {'primary': {'usedPercent': 25, 'windowDurationMins': 120},
                      'secondary': {'usedPercent': None}}
        }, 'rateLimitResetCredits': {'availableCount': 2}})
        self.assertEqual({'schemaVersion', 'updatedAt', 'summaryRemaining', 'buckets',
                          'resetCredits'}, set(data))
        self.assertEqual(1, data['schemaVersion'])
        self.assertIsNotNone(datetime.datetime.fromisoformat(data['updatedAt']).tzinfo)
        self.assertEqual(42, data['summaryRemaining'])
        self.assertEqual(2, data['resetCredits'])
        self.assertEqual([
            {'id': 'codex', 'name': 'codex', 'windows': [
                {'id': 'primary', 'remaining': 75, 'durationMins': 120, 'resetsAt': None},
                {'id': 'secondary', 'remaining': None, 'durationMins': None, 'resetsAt': None}],
             'credits': None},
            {'id': 'extra', 'name': 'Extra', 'windows': [
                {'id': 'secondary', 'remaining': 42, 'durationMins': 10080,
                 'resetsAt': 1893456000}], 'credits': None}
        ], data['buckets'])

    def test_zero_and_out_of_range_remaining_are_clamped(self):
        for used, expected in [(100, 0), (120, 0), (-5, 100), (0, 100)]:
            with self.subTest(used=used):
                data = self.read_snapshot({'rateLimits': {'primary': {'usedPercent': used}}})
                self.assertEqual(expected, data['summaryRemaining'])
                self.assertEqual(expected, data['buckets'][0]['windows'][0]['remaining'])

    def test_invalid_numbers_are_unknown_and_output_is_strict_json(self):
        for value in (None, True, '12', float('nan'), float('inf'), -float('inf'), 10 ** 400):
            with self.subTest(value=str(value)):
                data = self.read_snapshot({'rateLimits': {
                    'limitName': ['invalid name'],
                    'primary': {'usedPercent': value, 'windowDurationMins': value,
                                'resetsAt': value}},
                    'rateLimitResetCredits': {'availableCount': value}})
                self.assertIsNone(data['summaryRemaining'])
                window = data['buckets'][0]['windows'][0]
                self.assertIsNone(window['remaining'])
                self.assertIsNone(window['durationMins'])
                self.assertIsNone(window['resetsAt'])
                self.assertIsNone(data['resetCredits'])
                self.assertEqual('codex', data['buckets'][0]['name'])

    def test_duration_requires_positive_value_and_timestamp_must_be_displayable(self):
        for duration, timestamp in [(0, 1e20), (-1, -1e20)]:
            with self.subTest(duration=duration):
                data = self.read_snapshot({'rateLimits': {'primary': {
                    'usedPercent': 10, 'windowDurationMins': duration, 'resetsAt': timestamp}}})
                self.assertIsNone(data['buckets'][0]['windows'][0]['durationMins'])
                self.assertIsNone(data['buckets'][0]['windows'][0]['resetsAt'])

    def test_missing_windows_remain_empty_and_unknown(self):
        data = self.read_snapshot({'rateLimits': {'limitId': 'only-credits',
            'primary': None, 'secondary': 'bad', 'credits': {'balance': '3.50',
                'hasCredits': True, 'unlimited': False, 'secret': 'must not leak'}}})
        self.assertIsNone(data['summaryRemaining'])
        self.assertEqual([], data['buckets'][0]['windows'])
        self.assertEqual({'balance': '3.50', 'hasCredits': True, 'unlimited': False},
                         data['buckets'][0]['credits'])

    def test_credits_values_are_normalized_without_leaking_extra_fields(self):
        for balance in (float('nan'), float('inf'), True, {'nested': 'value'}, 10 ** 400):
            with self.subTest(balance=str(balance)):
                data = self.read_snapshot({'rateLimits': {'credits': {
                    'balance': balance, 'hasCredits': 1, 'unlimited': 'yes', 'other': 'hidden'}},
                    'rateLimitResetCredits': {'availableCount': -1}})
                self.assertEqual({'balance': None, 'hasCredits': None, 'unlimited': None},
                                 data['buckets'][0]['credits'])
                self.assertIsNone(data['resetCredits'])

    def test_text_cli_retains_existing_output(self):
        self.fake_codex({'rateLimits': {'primary': {
            'usedPercent': 25, 'windowDurationMins': 120}}})
        process = self.run_cli()
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertEqual('', process.stderr)
        self.assertIn('查询时间：', process.stdout)
        self.assertIn('Codex 订阅用量', process.stdout)
        self.assertIn('120 分钟', process.stdout)
        self.assertIn('剩余 75%', process.stdout)

    def test_json_watch_combination_is_rejected_before_starting_server(self):
        self.fake_codex()
        process = self.run_cli('--json', '--watch', '1')
        self.assertEqual(2, process.returncode)
        self.assertEqual('', process.stdout)
        self.assertIn('--watch', process.stderr)
        self.assertNotIn('unrecognized arguments', process.stderr)
        self.assertFalse(self.pid_file.exists())

    def test_server_errors_and_empty_results_only_write_stderr(self):
        for mode in ('error', 'ok'):
            with self.subTest(mode=mode):
                self.fake_codex(mode=mode)
                process = self.run_cli('--json')
                self.assertEqual(1, process.returncode)
                self.assertEqual('', process.stdout)
                self.assertIn('查询失败', process.stderr)
                if mode == 'error':
                    self.assertIn('fake authentication error', process.stderr)

    def test_timeout_only_writes_stderr_and_reaps_server(self):
        self.fake_codex(mode='hang')
        process = self.run_cli('--json', '--timeout', '.2')
        self.assertEqual(1, process.returncode)
        self.assertEqual('', process.stdout)
        self.assertIn('超时', process.stderr)
        self.assert_process_gone(int(self.pid_file.read_text()))

    def assert_process_gone(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_termination_signals_reap_app_server_before_helper_exits(self):
        for termination_signal in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=termination_signal):
                self.pid_file.unlink(missing_ok=True)
                self.fake_codex(mode='hang')
                helper = subprocess.Popen([sys.executable, str(HELPER), '--json', '--codex',
                                           str(self.codex), '--timeout', '20'],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                server_pid = None
                try:
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline and not self.pid_file.exists() and helper.poll() is None:
                        time.sleep(.01)
                    self.assertTrue(self.pid_file.exists(), 'helper did not start fake app-server')
                    server_pid = int(self.pid_file.read_text())
                    helper.send_signal(termination_signal)
                    stdout, stderr = helper.communicate(timeout=4)
                    self.assertNotEqual(0, helper.returncode)
                    self.assertEqual('', stdout)
                    self.assertIn('取消', stderr)
                    self.assert_process_gone(server_pid)
                finally:
                    if helper.poll() is None:
                        helper.kill()
                    helper.communicate()
                    if server_pid is not None:
                        try:
                            os.kill(server_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_launcher_descendants_cannot_keep_helper_alive_during_cleanup(self):
        # Mutations caught: signal only the launcher, skip cleanup when it has
        # already exited, or close stdout while its reader still owns the lock.
        for scenario, launcher_exits in [('success', False), ('timeout', False),
                                          ('cancel', False), ('cancel', True),
                                          ('success', True)]:
            with self.subTest(scenario=scenario, launcher_exits=launcher_exits):
                native_pid_file = self.directory / 'native.pid'
                native_pid_file.unlink(missing_ok=True)
                self.pid_file.unlink(missing_ok=True)
                self.fake_codex({'rateLimits': {'primary': {'usedPercent': 25}}})
                native = self.directory / 'native.py'
                body = self.codex.read_text().split('\n', 1)[1]
                prelude = '''import signal
signal.signal(signal.SIGTERM, signal.SIG_IGN)
signal.signal(signal.SIGINT, signal.SIG_IGN)
'''
                body = body.replace(str(self.pid_file), str(native_pid_file))
                if scenario != 'success':
                    body = body.replace("if 'ok' == 'hang':", 'if True:')
                native.write_text(prelude + body + '\ntime.sleep(30)\n', encoding='utf-8')
                launcher = '''#!{python}
import os, pathlib, signal, subprocess, sys, time
pathlib.Path({pid!r}).write_text(str(os.getpid()))
child = subprocess.Popen([sys.executable, {native!r}] + sys.argv[1:])
def forward(signum, frame):
    child.send_signal(signum)
    if {exits!r}:
        sys.exit(0)
signal.signal(signal.SIGTERM, forward)
signal.signal(signal.SIGINT, forward)
if {exits!r} and {success!r}:
    while not pathlib.Path({native_pid!r}).exists():
        time.sleep(.01)
    sys.exit(0)
sys.exit(child.wait())
'''.format(python=sys.executable, pid=str(self.pid_file), native=str(native),
           native_pid=str(native_pid_file), exits=launcher_exits, success=scenario == 'success')
                self.codex.write_text(launcher, encoding='utf-8')
                helper = subprocess.Popen([sys.executable, str(HELPER), '--json', '--codex',
                                           str(self.codex), '--timeout',
                                           '.4' if scenario == 'timeout' else '20'],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                native_pid = None
                launcher_pid = None
                try:
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline and not native_pid_file.exists():
                        time.sleep(.01)
                    self.assertTrue(native_pid_file.exists(), 'native app-server never started')
                    native_pid = int(native_pid_file.read_text())
                    launcher_pid = int(self.pid_file.read_text())
                    if scenario == 'cancel':
                        helper.send_signal(signal.SIGTERM)
                    try:
                        stdout, stderr = helper.communicate(timeout=4)
                    except subprocess.TimeoutExpired:
                        self.fail('helper cleanup blocked while native descendant held stdout')
                    if scenario == 'success':
                        self.assertEqual(0, helper.returncode, stderr)
                        self.assertEqual(75, json.loads(stdout)['summaryRemaining'])
                        self.assertEqual('', stderr)
                    else:
                        self.assertEqual(1, helper.returncode, stderr)
                        self.assertEqual('', stdout)
                        self.assertIn('取消' if scenario == 'cancel' else '超时', stderr)
                    self.assert_process_gone(launcher_pid)
                    # Orphaned grandchildren can briefly remain zombies until
                    # init reaps them. They must have stopped executing.
                    native_stat = Path('/proc/{}/stat'.format(native_pid))
                    self.assertTrue(not native_stat.exists() or
                                    native_stat.read_text().split()[2] == 'Z',
                                    'native descendant survived helper cleanup')
                finally:
                    for pid in (native_pid, launcher_pid):
                        if pid is not None:
                            try:
                                os.kill(pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                    if helper.poll() is None:
                        helper.kill()
                    helper.communicate(timeout=3)


if __name__ == '__main__':
    unittest.main()
