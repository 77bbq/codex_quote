# Codex 额度顶部栏与桌宠

在 Ubuntu 20.04 的 GNOME 顶部栏常驻显示 `Codex 72%`，点击展开原生额度卡片。显示的是所有已知额度窗口中最低的剩余百分比，各窗口、重置时间和最近成功更新时间都可在卡片中查看。另保留原有桌宠和命令行工具。

通过本机 Codex CLI 的现有 ChatGPT 登录查询，无需复制登录令牌，也无需安装 Python 第三方包。

## 顶部栏安装与启用

顶部栏扩展仅支持 **GNOME Shell 3.36 / X11**，目标环境为 Ubuntu 20.04.6、GNOME Shell 3.36.9、Python 3.8。新版 GNOME 和其他桌面环境不在当前支持范围。先确认环境和 Codex 登录：

```bash
gnome-shell --version
echo "$XDG_SESSION_TYPE"
codex --version
codex login status
```

如尚未登录，运行 `codex login` 并使用 ChatGPT 账号。获取源码后，在源码目录安装：

```bash
python3 install_topbar.py
```

安装器检查 GNOME 版本，将扩展及查询后端复制到 `${XDG_DATA_HOME:-$HOME/.local/share}/gnome-shell/extensions/codex-quota@codex-quota.local`，记录当前 Python、Codex 和 Node 的绝对入口路径。之后可移动源码目录；请保留这些运行时可执行文件。安装器不会查询账号或自动启用扩展。

**首次安装后**，在 X11 按 `Alt+F2`，输入 `r` 并回车，或注销后重新登录，使 GNOME 发现扩展。随后运行：

```bash
gnome-extensions enable codex-quota@codex-quota.local
```

顶部栏出现 `Codex …` 后会在后台查询，之后每次查询结束等待 120 秒再刷新，单次超时 20 秒。点击卡片中的「立即刷新」可手动查询。启用后可以关闭终端；扩展会随已启用的 GNOME 会话加载。剩余不超过 20% 时提示低额度，进入低额度状态时通知一次。

GNOME 的 PATH 可能与终端不同，nvm 用户尤其需要注意。安装器优先选择 Codex 同目录的 Node；可显式指定入口，路径含空格时请加引号：

```bash
python3 install_topbar.py --codex "$(command -v codex)" --python "$(command -v python3)" --node "$(command -v node)"
```

安装器保留 Codex 的符号链接入口，不会把 npm 入口替换为链接目标的 JavaScript 路径。`--node` 必须指向名为 `node` 的可执行入口（可以是符号链接）；`nodejs` 等其他入口名会被拒绝，因为配置只记录目录，供 `/usr/bin/env node` 查找。所选 Node 的目录会加入查询子进程的 PATH；不读取交互式 shell 配置。nvm 更新或删除旧版本后，请重新安装更新路径。

## 顶部栏更新、停用与移除

更新前先停用，再从更新后的源码目录覆盖安装：

```bash
gnome-extensions disable codex-quota@codex-quota.local
python3 install_topbar.py --replace
```

然后在 X11 使用 `Alt+F2` → `r` → 回车，或注销后重新登录，再执行上述 `gnome-extensions enable` 命令。普通重复安装会拒绝覆盖；覆盖和移除都要求目录中的安装标记及扩展 UUID 匹配，不会清理其他扩展。

仅停用可运行 `gnome-extensions disable codex-quota@codex-quota.local`。彻底移除：

```bash
gnome-extensions disable codex-quota@codex-quota.local
python3 install_topbar.py --uninstall
```

如当前会话仍显示扩展，请注销后重新登录。`--data-dir PATH` 可指定用户数据根目录，安装、更新和移除时应使用同一目录；例如测试目的地 `/tmp/quota-topbar-test`，扩展会放在其 `gnome-shell/extensions/` 下。运行 `python3 install_topbar.py --help` 查看参数。

顶部栏首次失败显示 `Codex —`；后续查询失败会保留旧数据，在顶部栏加 `!`，卡片保留最后成功时间及错误原因。未知额度不会当成 0%，窗口名称按实际服务时长显示。出错时先检查卡片提示、登录状态、网络，以及配置中记录的 Python/Codex/Node 是否仍存在。

**验证范围：**用户已在 Ubuntu 20.04 / GNOME Shell 3.36 / X11 环境反馈安装、启用后顶部栏显示正常。自动测试覆盖伪响应逻辑、查询与取消、生命周期、临时目录安装及安装后的跨语言查询链路；主题、滚动、通知和异常场景尚未完成系统性的实机验收。

### 安装后顶部栏没有出现

安装器输出「已安装」只表示文件复制成功，还需要按上述步骤重新加载 GNOME 并启用扩展。可在桌面终端查看状态：

```bash
gnome-extensions info codex-quota@codex-quota.local
```

`State: ENABLED` 表示扩展已启用；`State: ERROR` 表示加载出错。GNOME 3.36 的这条命令在未识别扩展或无法连接桌面会话时，可能没有任何输出，不能据此判断已启用。首次安装后先完成 `Alt+F2` → `r` → 回车（或注销后重新登录），再启用并查询状态。报告问题时请附安装器和启用命令的完整输出。

## 桌宠

桌宠是住在 Linux 桌面的可拖动小窗口：

![四种桌宠形象预览，显示的是模拟数据](assets/preview.png)

内置小猫、小兔、熊猫和机器人四种图案。右键桌宠，选择「切换形象」即可更换；小宠物会记住你的选择。图案由程序绘制，不依赖单独下载的图片。

### 桌宠功能

- 显示所有已知额度窗口中最低的剩余百分比；点击桌宠可查看各窗口、重置时间和上次成功更新时间。
- 拖动调整位置；右键打开菜单，切换形象、查看详情、立即刷新或退出；按 `Esc` 也可退出。
- 默认在剩余不超过 20% 时变换表情，并尝试发送桌面通知。查询在后台进行；失败时明确提示错误，并在详情中标记旧数据。
- 通过本机 Codex CLI 查询 ChatGPT 额度。不同账号返回的窗口可能不同，缺失数据不会当作 0%。

### 桌宠安装和启动

需要 Ubuntu 20.04 图形桌面、Python 3.8 或更新版本、已安装的 Codex CLI，以及可连接 OpenAI 的网络。使用现有的 ChatGPT 登录：

```bash
codex --version
codex login status
```

如尚未登录，请运行 `codex login` 并使用 ChatGPT 账号。获取本仓库源码后，在源码目录运行：

```bash
sudo apt update
sudo apt install python3-tk
python3 codex_pet.py
```

如需桌面通知且没有 `notify-send`，可安装：

```bash
sudo apt install libnotify-bin
```

启动程序的终端需要保持打开。桌宠不会自动设置开机自启。

### 桌宠设置

默认每次查询结束后等待 120 秒再刷新。可以用命令行调整刷新间隔（秒）和低额度阈值（百分比）：

```bash
python3 codex_pet.py --interval 60 --threshold 20
```

使用 `--no-notify` 关闭桌面通知；从非低额度状态进入低额度时通知一次，恢复后再次进入低额度才会再次提醒。如果 `codex` 不在 PATH 中，可以指定其完整路径：

```bash
python3 codex_pet.py --codex /实际路径/codex
```

可用 `--pet cat`、`--pet rabbit`、`--pet panda` 或 `--pet robot` 为本次启动指定形象。运行 `python3 codex_pet.py --help` 查看所有选项。右键切换的形象保存在 `~/.config/codex-quota-pet/settings.json`；如果 `XDG_CONFIG_HOME` 已设置为绝对路径，则使用该目录。删除配置文件可恢复默认选择。

## 命令行工具

不启动图形界面也可单次查询、持续查看或输出 JSON：

```bash
python3 codex-quota.py
python3 codex-quota.py --watch 120
python3 codex-quota.py --json --timeout 20
```

`--json` 为单次机器可读输出，不能与 `--watch` 同用。需要时传入 `--codex /实际路径/codex`；运行 `python3 codex-quota.py --help` 查看其他选项。

## 数据、隐私和限制

- 展示的是 ChatGPT/Codex 的用量窗口，**不是 OpenAI API 的美元余额**。服务返回 Credits 信息时，详情展示原始值，不假定货币或单位。
- 顶部栏、桌宠和命令行工具调用本机 `codex app-server` 查询；Codex 自己处理认证并连接 OpenAI。本项目不会读取或保存认证文件，也不会把认证信息发送给第三方服务。
- `app-server` 是实验性接口；不同 Codex CLI 版本或将来的协议变更可能影响使用。仅使用 API Key 登录时，可能无法读取 ChatGPT 订阅额度。
- 桌宠是**带背景的小型悬浮窗口**，不是透明图片。窗口置顶和拖动受桌面环境及窗口管理器影响，Wayland 和远程图形转发未验证。
- 顶部栏和桌宠需要图形桌面；纯终端环境可使用 `codex-quota.py`。

遇到问题可先确认 `codex --version`、`codex login status`、网络连接和图形桌面是否正常。查询失败后点击桌宠可查看原因。报告问题时请勿分享登录令牌、认证文件或个人额度截图。

## 参与和许可

欢迎反馈和贡献，详见 [CONTRIBUTING.md](CONTRIBUTING.md)。本项目使用 [MIT 许可证](LICENSE)。

额度字段及接口说明参考 [OpenAI Codex app-server 文档](https://learn.chatgpt.com/docs/app-server)。
