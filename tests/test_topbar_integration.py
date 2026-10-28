"""Exercise the installed JS -> Python -> app-server contract with fake quota data."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
UUID = 'codex-quota@codex-quota.local'


@unittest.skipUnless(shutil.which('gjs') and shutil.which('node'), 'GJS and Node are required for the desktop integration smoke test')
class InstalledTopbarTests(unittest.TestCase):
    def test_installed_modules_query_fake_server_and_render_lowest_remaining(self):
        with tempfile.TemporaryDirectory(prefix='codex-quota-integration-') as temporary:
            directory = Path(temporary)
            codex = directory / 'fake codex'
            codex.write_text('#!' + sys.executable + '\nimport runpy, sys\nsys.argv = [' +
                             repr(str(ROOT / 'tests' / 'fake_server.py')) + ', "ok"]\n' +
                             'runpy.run_path(sys.argv[0], run_name="__main__")\n', encoding='utf-8')
            codex.chmod(0o755)
            # Only the version command is faked; the installer copies actual project files.
            shell = directory / 'gnome-shell'
            shell.write_text('#!/bin/sh\necho "GNOME Shell 3.36.9"\n', encoding='utf-8')
            shell.chmod(0o755)
            import os
            environment = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ.get('PATH', ''))
            install = subprocess.run([sys.executable, str(ROOT / 'install_topbar.py'),
                                      '--data-dir', str(directory / 'data with spaces'),
                                      '--codex', str(codex)], env=environment,
                                     capture_output=True, text=True, timeout=15)
            self.assertEqual(0, install.returncode, install.stderr)
            extension = directory / 'data with spaces' / 'gnome-shell' / 'extensions' / UUID
            config = json.loads((extension / 'config.json').read_text())
            script = directory / 'integration.js'
            script.write_text('''
const GLib = imports.gi.GLib;
imports.searchPath.unshift(%s);
const Model = imports.quotaModel;
const Process = imports.quotaProcess;
const Controller = imports.quotaController;
const config = %s;
const loop = new GLib.MainLoop(null, false);
let failure = null;
let reached = false;
const deadline = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 6, () => {
    failure = new Error('installed query timed out'); loop.quit(); return GLib.SOURCE_REMOVE;
});
const controller = new Controller.QuotaController({
    launch: done => Process.launch(config, %s, done),
    schedule: () => { loop.quit(); return 1; },
    cancelTimer: () => {},
    render: state => {
        if (!state.busy) {
            reached = true;
            if (state.error || Model.summaryText(state) !== 'Codex 42%%')
                failure = new Error(state.error || Model.summaryText(state));
            else print(Model.summaryText(state));
        }
    }
}, config, Model);
controller.enable();
loop.run();
controller.disable();
GLib.source_remove(deadline);
if (failure) throw failure;
if (!reached) throw new Error('installed query did not complete');
''' % (json.dumps(str(extension)), json.dumps(config), json.dumps(str(extension))), encoding='utf-8')
            process = subprocess.run(['gjs', str(script)], capture_output=True, text=True, timeout=10)
            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual('Codex 42%', process.stdout.strip())
            self.assertEqual('', process.stderr)


if __name__ == '__main__':
    unittest.main()
