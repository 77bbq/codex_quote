/* exported launch */
'use strict';
const {Gio, GLib} = imports.gi;

function launch(config, extensionPath, done) {
    const launcher = new Gio.SubprocessLauncher({
        flags: Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE,
    });
    if (config.nodeDir)
        launcher.setenv('PATH', `${config.nodeDir}:${GLib.getenv('PATH') || '/usr/local/bin:/usr/bin:/bin'}`, true);
    const process = launcher.spawnv([
        config.python,
        GLib.build_filenamev([extensionPath, 'codex-quota.py']),
        '--json', '--codex', config.codex, '--timeout', String(config.timeout),
    ]);
    let completed = false;
    process.communicate_utf8_async(null, null, (source, result) => {
        let snapshot = null;
        let error = null;
        try {
            const [, stdout, stderr] = source.communicate_utf8_finish(result);
            if (!source.get_successful())
                throw new Error((stderr || '').trim().slice(0, 600) || '额度查询进程异常退出。');
            if (!stdout || stdout.length > 1024 * 1024)
                throw new Error('额度查询没有返回有效数据。');
            try {
                snapshot = JSON.parse(stdout);
            } catch (_error) {
                throw new Error('额度查询返回了无法识别的数据，请检查程序版本。');
            }
        } catch (failure) {
            error = failure.message;
        }
        completed = true;
        done(snapshot, error);
    });
    return {
        cancel() {
            if (!completed) {
                // Keep communicate alive to reap the helper; its handler reaps app-server.
                try { process.send_signal(15); } catch (_error) { /* Already exited. */ }
            }
        },
    };
}
