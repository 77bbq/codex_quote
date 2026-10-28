"""Installer behavior tests; every destination and executable is a local fixture."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


UUID = "codex-quota@codex-quota.local"
INSTALLER = Path(__file__).resolve().parents[1] / "install_topbar.py"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="quota installer ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "source with spaces"
        self.extension = self.source / "gnome-extension" / UUID
        self.extension.mkdir(parents=True)
        (self.extension / "metadata.json").write_text(json.dumps({
            "uuid": UUID, "shell-version": ["3.36"], "name": "Fixture",
        }))
        (self.extension / "extension.js").write_text("// extension fixture\n")
        (self.extension / "quotaModel.js").write_text("// model fixture\n")
        (self.extension / "stylesheet.css").write_text("/* style fixture */\n")
        (self.source / "codex-quota.py").write_text("print('fixture backend')\n")
        self.script = self.source / "install_topbar.py"
        if INSTALLER.exists():
            shutil.copy2(str(INSTALLER), str(self.script))
        self.bin = self.root / "session bin"
        self.bin.mkdir()
        self.make_executable(self.bin / "gnome-shell", "#!/bin/sh\nprintf 'GNOME Shell %s\\n' \"$FIXTURE_GNOME_VERSION\"\n")
        self.nvm = self.root / "nvm runtime" / "bin"
        self.nvm.mkdir(parents=True)
        self.node = self.make_executable(self.nvm / "node", "#!/bin/sh\nexit 0\n")
        self.action_log = self.root / "unexpected external action"
        forbidden_action = '#!/bin/sh\nprintf called >> "$FIXTURE_ACTION_LOG"\nexit 99\n'
        target = self.make_executable(self.root / "codex entry.js", forbidden_action)
        self.make_executable(self.bin / "gnome-extensions", forbidden_action)
        self.codex = self.nvm / "codex"
        self.codex.symlink_to(target)
        self.python = self.bin / "python-entry"
        self.python.symlink_to(sys.executable)
        self.data = self.root / "data with spaces"
        self.destination = self.data / "gnome-shell" / "extensions" / UUID
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + str(self.nvm),
                        FIXTURE_GNOME_VERSION="3.36.9", XDG_DATA_HOME=str(self.data),
                        HOME=str(self.root / "home"), FIXTURE_ACTION_LOG=str(self.action_log))

    def make_executable(self, path, content):
        path.write_text(content)
        path.chmod(0o755)
        return path

    def run_installer(self, *args, explicit=True, env=None):
        command = [sys.executable, str(self.script)]
        if explicit:
            command += ["--data-dir", str(self.data), "--codex", str(self.codex),
                        "--python", str(self.python)]
        return subprocess.run(command + list(args), env=env or self.env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=10)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_install_copies_complete_extension_and_backend_with_explicit_config(self):
        result = self.run_installer()
        self.assert_success(result)
        self.assertFalse(self.action_log.exists(), "Installer must not query Codex or enable the extension")
        self.assertEqual(json.loads((self.destination / "config.json").read_text()), {
            "python": str(self.python), "codex": str(self.codex), "nodeDir": str(self.nvm),
            "interval": 120, "timeout": 20, "threshold": 20, "notifications": True,
        })
        for name in ("metadata.json", "extension.js", "quotaModel.js", "stylesheet.css"):
            self.assertEqual((self.destination / name).read_bytes(), (self.extension / name).read_bytes())
        shutil.rmtree(str(self.source))
        result = subprocess.run([sys.executable, str(self.destination / "codex-quota.py")],
                                stdout=subprocess.PIPE, universal_newlines=True, timeout=10)
        self.assertEqual(result.stdout.strip(), "fixture backend")

    def test_install_outputs_manual_enable_and_x11_reload_steps(self):
        result = self.run_installer()
        self.assert_success(result)
        self.assertIn("gnome-extensions enable " + UUID, result.stdout)
        self.assertIn("Alt+F2", result.stdout)
        self.assertIn("X11", result.stdout)

    def test_default_detection_preserves_nvm_symlink_and_uses_codex_sibling_node(self):
        # A session Node must not override the runtime beside the selected nvm Codex.
        self.make_executable(self.bin / "node", "#!/bin/sh\nexit 0\n")
        self.assert_success(self.run_installer(explicit=False))
        config = json.loads((self.destination / "config.json").read_text())
        self.assertEqual(config["codex"], str(self.codex))
        self.assertEqual(config["nodeDir"], str(self.nvm))

    def test_explicit_node_overrides_detected_runtime(self):
        chosen_dir = self.root / "chosen runtime"
        chosen_dir.mkdir()
        chosen = self.make_executable(chosen_dir / "node", "#!/bin/sh\nexit 0\n")
        self.assert_success(self.run_installer("--node", str(chosen)))
        self.assertEqual(json.loads((self.destination / "config.json").read_text())["nodeDir"], str(chosen_dir))

    def test_nonstandard_node_entry_is_rejected_before_installing(self):
        for name in ("nodejs", "chosen node"):
            chosen = self.make_executable(self.bin / name, "#!/bin/sh\nexit 0\n")
            result = self.run_installer("--node", str(chosen))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("名为 node", result.stderr)
            self.assertFalse(self.destination.exists())

    def test_repeated_install_requires_replace_and_replace_updates_files(self):
        self.assert_success(self.run_installer())
        (self.extension / "extension.js").write_text("// upgraded\n")
        (self.destination / "obsolete.js").write_text("old")
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertEqual((self.destination / "extension.js").read_text(), "// extension fixture\n")
        self.assert_success(self.run_installer("--replace"))
        self.assertEqual((self.destination / "extension.js").read_text(), "// upgraded\n")
        self.assertFalse((self.destination / "obsolete.js").exists())

    def test_failed_replace_leaves_existing_installation_untouched(self):
        self.assert_success(self.run_installer())
        (self.extension / "metadata.json").write_text('{"uuid":"different"}')
        self.assertNotEqual(self.run_installer("--replace").returncode, 0)
        self.assertEqual((self.destination / "extension.js").read_text(), "// extension fixture\n")

    def test_unowned_directory_and_symlink_are_never_replaced_or_removed(self):
        self.destination.mkdir(parents=True)
        sentinel = self.destination / "personal.txt"
        sentinel.write_text("keep")
        for args in (("--replace",), ("--uninstall",)):
            self.assertNotEqual(self.run_installer(*args).returncode, 0)
            self.assertEqual(sentinel.read_text(), "keep")
        other = self.destination.with_name("other-extension")
        self.destination.rename(other)
        self.destination.symlink_to(other, target_is_directory=True)
        for args in (("--replace",), ("--uninstall",)):
            self.assertNotEqual(self.run_installer(*args).returncode, 0)
            self.assertEqual((other / "personal.txt").read_text(), "keep")

    def test_uninstall_removes_only_owned_extension_without_runtime_or_gnome(self):
        self.assert_success(self.run_installer())
        sibling = self.destination.with_name("other-extension")
        sibling.mkdir()
        (sibling / "keep").write_text("safe")
        self.env["PATH"] = str(self.root / "missing executables")
        self.assert_success(self.run_installer("--uninstall"))
        self.assertFalse(self.destination.exists())
        self.assertEqual((sibling / "keep").read_text(), "safe")
        self.assert_success(self.run_installer("--uninstall"))

    def test_other_gnome_versions_are_rejected_before_creating_destination(self):
        for version in ("3.38.1", "36.0", "45.2", "3.360.1", "bad-version"):
            self.env["FIXTURE_GNOME_VERSION"] = version
            result = self.run_installer()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("3.36", result.stderr)
            self.assertFalse(self.destination.exists())

    def test_invalid_runtime_is_rejected_before_creating_destination(self):
        for option in ("--python", "--codex", "--node"):
            result = self.run_installer(option, str(self.root / "does not exist"))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.destination.exists())

    def test_wrong_uuid_metadata_cannot_authorize_uninstall(self):
        self.assert_success(self.run_installer())
        (self.destination / "metadata.json").write_text('{"uuid":"another-extension"}')
        self.assertNotEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertTrue((self.destination / "extension.js").exists())


if __name__ == "__main__":
    unittest.main()
