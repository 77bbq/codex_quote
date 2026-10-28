#!/usr/bin/env python3
"""Install the GNOME 3.36 quota extension without changing the running Shell."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


UUID = "codex-quota@codex-quota.local"
MARKER = ".codex-quota-install.json"
OWNERSHIP = {"installer": "codex-quota-topbar", "uuid": UUID, "version": 1}


def absolute_entry(value):
    """Keep a symlink's executable entry (an npm target may be JavaScript)."""
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def executable(value, label):
    entry = absolute_entry(value)
    if not entry.is_file() or not os.access(str(entry), os.X_OK):
        raise ValueError("{} 可执行文件不可用：{}".format(label, entry))
    return entry


def find_executable(value, name):
    candidate = value if value is not None else shutil.which(name)
    if not candidate:
        raise ValueError("找不到 {}；请指定 --{} 的完整路径".format(name, name))
    return executable(candidate, name)


def check_gnome_version():
    try:
        result = subprocess.run(["gnome-shell", "--version"], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("无法检测 GNOME Shell；仅支持 GNOME 3.36：{}".format(exc))
    if result.returncode or not re.search(r"\bGNOME Shell\s+3\.36(?:\.\d+)*\s*$", result.stdout.strip()):
        raise ValueError("仅支持 GNOME Shell 3.36，检测结果：{}".format(result.stdout.strip() or "未知"))


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def require_owned(destination):
    if destination.is_symlink() or not destination.is_dir():
        raise ValueError("拒绝操作非本安装器目录或符号链接：{}".format(destination))
    try:
        owned = (read_json(destination / MARKER) == OWNERSHIP and
                 read_json(destination / "metadata.json").get("uuid") == UUID)
    except (OSError, ValueError, AttributeError):
        owned = False
    if not owned:
        raise ValueError("目录缺少匹配的安装标记或扩展 UUID，拒绝覆盖或移除：{}".format(destination))


def install(destination, config, replace):
    source = Path(__file__).resolve().parent
    extension = source / "gnome-extension" / UUID
    if destination.exists() or destination.is_symlink():
        require_owned(destination)
        if not replace:
            raise ValueError("扩展已安装；更新请使用 --replace")
    try:
        metadata = read_json(extension / "metadata.json")
    except (OSError, ValueError) as exc:
        raise ValueError("无法读取扩展源文件：{}".format(exc))
    if not isinstance(metadata, dict) or metadata.get("uuid") != UUID:
        raise ValueError("扩展源文件的 UUID 不匹配")
    if not (source / "codex-quota.py").is_file():
        raise ValueError("源码目录缺少 codex-quota.py")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + UUID + "-staging-", dir=str(destination.parent)))
    backup = None
    try:
        # copytree's existing-directory option requires Python 3.8, our target version.
        shutil.copytree(str(extension), str(staging), dirs_exist_ok=True)
        shutil.copy2(str(source / "codex-quota.py"), str(staging / "codex-quota.py"))
        for name, data in (("config.json", config), (MARKER, OWNERSHIP)):
            with (staging / name).open("w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
        if destination.exists() or destination.is_symlink():
            require_owned(destination)
            if not replace:
                raise ValueError("扩展已安装；更新请使用 --replace")
            backup = Path(tempfile.mkdtemp(prefix="." + UUID + "-backup-", dir=str(destination.parent)))
            backup.rmdir()
            destination.rename(backup)
        try:
            staging.rename(destination)
        except OSError:
            if backup is not None:
                backup.rename(destination)
                backup = None
            raise
    finally:
        if staging.exists():
            shutil.rmtree(str(staging))
    if backup is not None:
        shutil.rmtree(str(backup))


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装或移除 Codex GNOME 3.36 顶部栏扩展；不自动启用。")
    parser.add_argument("--codex", metavar="PATH", help="Codex 可执行入口的完整路径")
    parser.add_argument("--python", metavar="PATH", help="Python 3.8+ 可执行入口（默认当前 Python）")
    parser.add_argument("--node", metavar="PATH", help="名为 node 的可执行入口；默认优先 Codex 同目录的 node")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--replace", action="store_true", help="覆盖本安装器安装的扩展")
    actions.add_argument("--uninstall", action="store_true", help="只移除本安装器安装的扩展")
    parser.add_argument("--data-dir", metavar="PATH", help="用户数据根目录，默认 XDG_DATA_HOME 或 ~/.local/share")
    args = parser.parse_args(argv)
    xdg = os.environ.get("XDG_DATA_HOME", "")
    data_dir = args.data_dir or (xdg if os.path.isabs(xdg) else "~/.local/share")
    destination = absolute_entry(data_dir) / "gnome-shell" / "extensions" / UUID
    try:
        if args.uninstall:
            if destination.exists() or destination.is_symlink():
                require_owned(destination)
                shutil.rmtree(str(destination))
                print("已移除：{}".format(destination))
            else:
                print("扩展未安装：{}".format(destination))
            print("如当前会话仍显示扩展，请注销后重新登录。")
            return 0
        check_gnome_version()
        python = executable(args.python or sys.executable, "python")
        codex = find_executable(args.codex, "codex")
        sibling_node = codex.parent / "node"
        node = find_executable(args.node or (str(sibling_node) if sibling_node.is_file() and
                               os.access(str(sibling_node), os.X_OK) else None), "node")
        if node.name != "node":
            raise ValueError("Node 需要名为 node 的可执行入口；配置仅记录目录供 /usr/bin/env node 查找：{}".format(node))
        config = {"python": str(python), "codex": str(codex), "nodeDir": str(node.parent),
                  "interval": 120, "timeout": 20, "threshold": 20, "notifications": True}
        install(destination, config, args.replace)
    except (OSError, ValueError, shutil.Error) as exc:
        print("安装器错误：{}".format(exc), file=sys.stderr)
        return 1
    print("已安装：{}".format(destination))
    print("尚未加载或启用扩展。GNOME 3.36 / X11 首次安装或更新后：")
    print("按 Alt+F2，输入 r 并回车（或注销后重新登录），然后运行：")
    print("gnome-extensions enable " + UUID)
    print("启用后无需保持终端打开。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
