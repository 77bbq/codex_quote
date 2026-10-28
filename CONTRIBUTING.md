# 参与贡献

欢迎提交问题、建议和改进。项目目标是在 Linux 图形桌面上，以尽量少的依赖展示 Codex 的 ChatGPT 额度。

## 提交问题

请描述操作步骤、预期和实际行为，并注明 Ubuntu、桌面环境、Python 和 Codex CLI 版本。`echo "$XDG_SESSION_TYPE"` 可以帮助判断是 X11 还是 Wayland。请勿提交登录令牌、认证文件、API 密钥或包含个人账号信息的截图。

## 提交改动

1. Fork 本项目并创建分支，说明改动的目的。
2. 保持与 Python 3.8 兼容，不引入不必要的第三方运行时依赖。
3. 针对有风险的行为补充测试，运行项目现有的测试；修改界面时也请说明手动验证的环境和操作。
4. 在 Pull Request 中描述变更、验证方式和已知限制。无需分享真实额度或认证信息，可使用模拟数据。

在仓库根目录运行自动测试：

```bash
python3 -m unittest discover -s tests -v
```

修改顶部栏时，再运行 JavaScript 状态与生命周期测试，以及 GJS 子进程测试：

```bash
node tests/test_topbar_model.js
node tests/test_topbar_controller.js
gjs tests/test_topbar_process.js
```

测试使用模拟额度，不需要查询真实账号。安装后的跨语言集成测试需要本机有 Node 和 GJS；缺少这两个工具时，该项 Python 测试会跳过。原生卡片外观、主题、滚动和通知仍需在目标 GNOME 会话中手动验证。

提交贡献即表示你同意按本项目的 [MIT 许可证](LICENSE)授权贡献。请确保你有权提交所包含的代码和素材。
