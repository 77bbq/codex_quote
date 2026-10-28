// Run with: gjs tests/test_topbar_process.js
'use strict';
const {Gio, GLib} = imports.gi;
imports.searchPath.unshift(GLib.build_filenamev([GLib.get_current_dir(), 'gnome-extension', 'codex-quota@codex-quota.local']));
const Process = imports.quotaProcess;
function check(value, message) { if (!value) throw new Error(message); }
const directory = GLib.dir_make_tmp('codex-quota-process-XXXXXX');
const helper = GLib.build_filenamev([directory, 'codex-quota.py']);
const marker = GLib.build_filenamev([directory, 'cancelled']);
GLib.file_set_contents(helper, [
    'import json, signal, sys, time, os',
    'mode = sys.argv[sys.argv.index("--codex") + 1]',
    'if mode == "error":',
    '    print("查询失败：测试错误", file=sys.stderr); sys.exit(1)',
    'if mode == "bad":',
    '    print("not json"); sys.exit(0)',
    'if mode == "cancel":',
    '    def stop(signum, frame):',
    '        open(os.path.join(os.path.dirname(__file__), "cancelled"), "w").write("yes"); sys.exit(0)',
    '    signal.signal(signal.SIGTERM, stop)',
    '    print("ready", file=sys.stderr, flush=True)',
    '    time.sleep(30)',
    'else:',
    '    print(json.dumps({"mode": mode, "path": os.environ.get("PATH", "")}))',
].join('\n'));

const loop = new GLib.MainLoop(null, false);
const modes = ['ok', 'error', 'bad', 'cancel'];
let failure = null;
let deadline = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 8, () => {
    failure = new Error('process tests timed out'); loop.quit(); return GLib.SOURCE_REMOVE;
});
function next() {
    if (modes.length === 0) { loop.quit(); return; }
    const mode = modes.shift();
    const request = Process.launch({python: '/usr/bin/python3', codex: mode, nodeDir: '/tmp/test node directory',
        timeout: 2}, directory, (data, error) => {
        try {
            if (mode === 'ok') {
                check(!error && data.mode === 'ok', 'successful JSON must reach callback');
                check(data.path.startsWith('/tmp/test node directory:'), 'Node directory must prefix child PATH');
            } else if (mode === 'error') {
                check(error.includes('测试错误'), 'stderr must explain a failed query');
            } else if (mode === 'bad') {
                check(error && data === null, 'malformed output must fail');
            } else {
                check(GLib.file_test(marker, GLib.FileTest.EXISTS), 'cancel must signal the helper before completion');
            }
            next();
        } catch (err) { failure = err; loop.quit(); }
    });
    if (mode === 'cancel')
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 300, () => { request.cancel(); return GLib.SOURCE_REMOVE; });
}
try {
    next();
    loop.run();
} finally {
    GLib.source_remove(deadline);
    for (const file of [helper, marker]) {
        const target = Gio.File.new_for_path(file);
        if (target.query_exists(null)) target.delete(null);
    }
    Gio.File.new_for_path(directory).delete(null);
}
if (failure) throw failure;
print('Topbar Gio process: success, stderr, malformed JSON and cancellation passed.');
