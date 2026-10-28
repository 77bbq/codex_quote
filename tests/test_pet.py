import importlib.util
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('codex_pet', ROOT / 'codex_pet.py')
pet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pet)
quota = pet.quota
FAKE = str(Path(__file__).with_name('fake_server.py'))


class PreferencesTests(unittest.TestCase):
    def test_all_pet_choices_survive_restart_and_store_only_choice(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            for name in pet.PETS:
                pet.save_pet(name)
                self.assertEqual(name, pet.load_pet())
                self.assertEqual({'pet': name}, json.loads(Path(pet.config_file()).read_text(encoding='utf-8')))

    def test_malformed_missing_and_unexpected_data_fall_back(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            self.assertEqual('cat', pet.load_pet())
            path = Path(pet.config_file())
            path.parent.mkdir(parents=True)
            for contents in ('{', 'null', '{"pet": []}', '{"pet": {}}', '{"pet":"missing"}'):
                path.write_text(contents, encoding='utf-8')
                self.assertEqual('cat', pet.load_pet(), contents)

    def test_switch_remains_active_when_saving_is_unavailable(self):
        instance = pet.Pet.__new__(pet.Pet)
        instance.pet_choice = SimpleNamespace(get=lambda: 'rabbit')
        instance.display = ('70%', 'updated', 'normal')
        instance.root = object()
        instance.draw = mock.Mock()
        with mock.patch.object(pet, 'save_pet', side_effect=PermissionError('no access')), \
             mock.patch.object(pet.messagebox, 'showwarning') as warning:
            instance.select_pet()
        self.assertEqual('rabbit', instance.pet)
        instance.draw.assert_called_once_with('70%', 'updated', 'normal')
        warning.assert_called_once()

    def test_relative_xdg_path_uses_home(self):
        with mock.patch.dict(os.environ, {'XDG_CONFIG_HOME': 'relative'}), \
             mock.patch.object(pet.os.path, 'expanduser', return_value='/mock-home'):
            self.assertEqual(os.path.join('/mock-home', '.config', 'codex-quota-pet', 'settings.json'), pet.config_file())


class QuotaTests(unittest.TestCase):
    def test_exchange_multiple_buckets_and_lowest_window(self):
        data = quota.fetch_limits([sys.executable, FAKE, 'ok'], 3)
        self.assertEqual(('最低剩余 42%', True), pet.summary(data, 45))
        self.assertIn('120 分钟', quota.format_limits(data))

    def test_missing_and_unknown_windows_are_not_zero(self):
        data = {'rateLimits': {'primary': {'usedPercent': None}, 'secondary': None}}
        self.assertEqual(('额度未知', False), pet.summary(data, 20))
        self.assertIn('未知', quota.format_limits(data))

    def test_error_timeout_and_cancellation_are_reported(self):
        with self.assertRaisesRegex(quota.QuotaError, 'authentication'):
            quota.fetch_limits([sys.executable, FAKE, 'error'], 3)
        with self.assertRaisesRegex(quota.QuotaError, '超时'):
            quota.fetch_limits([sys.executable, FAKE, 'hang'], .2)
        event = threading.Event()
        timer = threading.Timer(.2, event.set)
        timer.start()
        try:
            start = time.monotonic()
            with self.assertRaisesRegex(quota.QuotaError, '取消'):
                quota.fetch_limits([sys.executable, FAKE, 'hang'], 5, cancel_event=event)
            self.assertLess(time.monotonic() - start, 3)
        finally:
            timer.cancel()

    def test_failure_keeps_previous_data_marked_stale(self):
        instance = pet.Pet.__new__(pet.Pet)
        instance.closing = False
        instance.busy = True
        instance.messages = queue.Queue()
        instance.messages.put((None, 'network error'))
        instance.result = {'rateLimits': {'primary': {'usedPercent': 70}}}
        instance.updated = 'old timestamp'
        instance.args = SimpleNamespace(interval=120)
        instance.root = SimpleNamespace(after=mock.Mock(return_value='timer'))
        instance.draw = mock.Mock()
        instance.poll()
        self.assertFalse(instance.busy)
        self.assertEqual('network error', instance.error)
        self.assertEqual('old timestamp', instance.updated)
        self.assertEqual(70, instance.result['rateLimits']['primary']['usedPercent'])
        instance.draw.assert_called_once_with('查询失败', '旧数据 · 点击查看原因', 'error')

    def test_low_notification_rearms_only_after_recovery(self):
        instance = pet.Pet.__new__(pet.Pet)
        instance.closing = False
        instance.busy = True
        instance.low = False
        instance.messages = queue.Queue()
        instance.args = SimpleNamespace(interval=120, threshold=20, no_notify=False)
        instance.root = SimpleNamespace(after=mock.Mock(return_value='timer'))
        instance.draw = mock.Mock()
        instance.notify = mock.Mock()
        low = {'rateLimits': {'primary': {'usedPercent': 90}}}
        recovered = {'rateLimits': {'primary': {'usedPercent': 10}}}
        for sample in (low, low, recovered, low):
            instance.messages.put((sample, None))
            instance.poll()
        self.assertEqual(2, instance.notify.call_count)
        self.assertEqual('low', instance.draw.call_args.args[2])


if __name__ == '__main__':
    unittest.main()
