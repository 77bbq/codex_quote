/* exported init, enable, disable */
'use strict';

const {Clutter, Gio, GLib, GObject, Pango, St} = imports.gi;
const ByteArray = imports.byteArray;
const Main = imports.ui.main;
const PanelMenu = imports.ui.panelMenu;
const PopupMenu = imports.ui.popupMenu;
const BarLevel = imports.ui.barLevel;
const Me = imports.misc.extensionUtils.getCurrentExtension();
const Model = Me.imports.quotaModel;
const Controller = Me.imports.quotaController;
const Process = Me.imports.quotaProcess;

let indicator = null;

function readConfig() {
    const file = Me.dir.get_child('config.json');
    const [, bytes] = file.load_contents(null);
    const config = JSON.parse(ByteArray.toString(bytes));
    for (const key of ['python', 'codex']) {
        if (typeof config[key] !== 'string' || !GLib.path_is_absolute(config[key]))
            throw new Error('安装配置中的程序路径无效，请重新运行安装脚本。');
    }
    if (typeof config.nodeDir !== 'string' || (config.nodeDir && !GLib.path_is_absolute(config.nodeDir)))
        throw new Error('安装配置中的 Node 路径无效，请重新运行安装脚本。');
    for (const key of ['interval', 'timeout']) {
        if (typeof config[key] !== 'number' || !Number.isFinite(config[key]) || config[key] <= 0)
            throw new Error('刷新间隔或查询超时配置无效。');
    }
    if (typeof config.threshold !== 'number' || !Number.isFinite(config.threshold) ||
        config.threshold < 0 || config.threshold > 100 || typeof config.notifications !== 'boolean')
        throw new Error('低额度提醒配置无效。');
    return config;
}

function label(text, styleClass, wrap) {
    const widget = new St.Label({text, style_class: styleClass || '', x_expand: true});
    if (wrap) {
        widget.clutter_text.line_wrap = true;
        widget.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
    }
    return widget;
}

function infoItem(child) {
    const item = new PopupMenu.PopupBaseMenuItem({reactive: false, can_focus: false});
    item.add_child(child);
    return item;
}

const QuotaIndicator = GObject.registerClass(
class QuotaIndicator extends PanelMenu.Button {
    _init() {
        super._init(0.5, 'Codex 剩余额度');
        this._label = label('Codex …', 'codex-quota-panel-label');
        this._label.y_align = Clutter.ActorAlign.CENTER;
        this.add_child(this._label);
        this.menu.box.add_style_class_name('codex-quota-menu');

        const heading = new St.BoxLayout({vertical: true, x_expand: true});
        heading.add_child(label('Codex 剩余额度', 'codex-quota-heading'));
        heading.add_child(label('所有已知窗口的最低剩余', 'codex-quota-muted codex-quota-subtitle'));
        this.menu.addMenuItem(infoItem(heading));
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._scroll = new St.ScrollView({x_expand: true, overlay_scrollbars: true,
            style_class: 'codex-quota-scroll'});
        this._scroll.set_policy(St.PolicyType.NEVER, St.PolicyType.AUTOMATIC);
        this._content = new St.BoxLayout({vertical: true, x_expand: true, style_class: 'codex-quota-content'});
        this._scroll.add_actor(this._content);
        this.menu.addMenuItem(infoItem(this._scroll));
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._footer = new St.BoxLayout({vertical: true, x_expand: true, style_class: 'codex-quota-footer'});
        this.menu.addMenuItem(infoItem(this._footer));
        this._refreshItem = new PopupMenu.PopupMenuItem('立即刷新');
        this._refreshItem.connect('activate', () => {
            if (this._controller)
                this._controller.refresh();
        });
        this.menu.addMenuItem(this._refreshItem);
        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open && this._controller)
                this._render(this._controller.state, false);
        });
        this._controller = null;
        this._config = null;
    }

    start() {
        try {
            this._config = readConfig();
        } catch (error) {
            this._render({snapshot: null, error: error.message, busy: false, low: false}, false);
            this._refreshItem.setSensitive(false);
            return;
        }
        this._controller = new Controller.QuotaController({
            launch: done => Process.launch(this._config, Me.path, done),
            schedule: (seconds, run) => GLib.timeout_add(GLib.PRIORITY_DEFAULT, Math.max(1, Math.round(seconds * 1000)), () => {
                run();
                return GLib.SOURCE_REMOVE;
            }),
            cancelTimer: id => GLib.source_remove(id),
            render: (state, notifyLow) => this._render(state, notifyLow),
        }, this._config, Model);
        this._controller.enable();
    }

    _render(state, notifyLow) {
        const low = Model.isLow(state.snapshot, this._config ? this._config.threshold : 20);
        this._label.text = Model.summaryText(state);
        this.accessible_name = `Codex 剩余额度：${this._label.text}`;
        if (low)
            this._label.add_style_class_name('codex-quota-low');
        else
            this._label.remove_style_class_name('codex-quota-low');
        this._refreshItem.label.text = state.busy ? '正在刷新…' : '立即刷新';
        this._refreshItem.setSensitive(!state.busy);
        this._content.destroy_all_children();
        this._footer.destroy_all_children();

        if (state.snapshot) {
            for (const bucket of state.snapshot.buckets)
                this._addBucket(bucket);
            if (state.snapshot.resetCredits !== null)
                this._content.add_child(label(`可用额度重置次数：${state.snapshot.resetCredits}`, 'codex-quota-muted'));
            const updated = new Date(state.snapshot.updatedAt);
            const local = `${updated.getMonth() + 1} 月 ${updated.getDate()} 日 ` +
                `${String(updated.getHours()).padStart(2, '0')}:${String(updated.getMinutes()).padStart(2, '0')}:${String(updated.getSeconds()).padStart(2, '0')}`;
            this._footer.add_child(label(`最近成功更新 ${local}`, 'codex-quota-muted'));
            if (state.snapshot.summaryRemaining === null)
                this._footer.add_child(label('额度未知，服务未返回可用百分比。', 'codex-quota-muted', true));
        } else {
            this._content.add_child(label(state.busy ? '正在查询额度…' : '暂无额度数据', 'codex-quota-muted'));
        }
        if (state.error) {
            const prefix = state.snapshot ? '旧数据 · 刷新失败' : '查询失败';
            this._footer.add_child(label(`${prefix}\n${state.error}`, 'codex-quota-error', true));
        }
        if (low)
            this._footer.add_child(label('额度偏低', 'codex-quota-low'));
        if (notifyLow && this._config.notifications)
            Main.notify('Codex 额度偏低', `最低剩余 ${Model.formatPercent(state.snapshot.summaryRemaining)}`);
    }

    _addBucket(bucket) {
        const group = new St.BoxLayout({vertical: true, x_expand: true, style_class: 'codex-quota-group'});
        group.add_child(label(bucket.name || bucket.id, 'codex-quota-group-name', true));
        if (bucket.windows.length === 0)
            group.add_child(label('暂无窗口数据', 'codex-quota-muted'));
        bucket.windows.forEach((window, index) => {
            const box = new St.BoxLayout({vertical: true, x_expand: true, style_class: 'codex-quota-window'});
            const row = new St.BoxLayout({x_expand: true, style_class: 'codex-quota-window-heading'});
            row.add_child(label(Model.durationLabel(window.durationMins, window.id === 'secondary' ? 1 : 0)));
            const percent = label(Model.formatPercent(window.remaining), 'codex-quota-percent');
            percent.x_expand = false;
            row.add_child(percent);
            box.add_child(row);
            const bar = new BarLevel.BarLevel({x_expand: true, style_class: 'barlevel codex-quota-bar'});
            bar.maximum_value = 1;
            bar.value = window.remaining === null ? 0 : window.remaining / 100;
            bar.accessible_name = `${Model.durationLabel(window.durationMins, index)}，剩余 ${Model.formatPercent(window.remaining)}`;
            if (window.remaining === null)
                bar.add_style_class_name('codex-quota-unknown');
            else if (window.remaining <= this._config.threshold) {
                bar.add_style_class_name('codex-quota-low');
                percent.add_style_class_name('codex-quota-low');
            }
            box.add_child(bar);
            box.add_child(label(Model.resetLabel(window.resetsAt, Date.now() / 1000), 'codex-quota-muted', true));
            group.add_child(box);
        });
        if (bucket.credits) {
            const credits = bucket.credits;
            group.add_child(label(`Credits（服务原值）：${credits.balance === null ? '未知' : credits.balance}`, 'codex-quota-muted', true));
            if (credits.unlimited === true)
                group.add_child(label('Credits：服务标记为无限', 'codex-quota-muted'));
            if (credits.hasCredits !== null)
                group.add_child(label(`Credits 可用：${credits.hasCredits ? '是' : '否'}`, 'codex-quota-muted'));
        }
        this._content.add_child(group);
    }

    stop() {
        if (this._controller)
            this._controller.disable();
        this._controller = null;
    }
});

function init() {}

function enable() {
    indicator = new QuotaIndicator();
    Main.panel.addToStatusArea(Me.metadata.uuid, indicator, 0, 'right');
    indicator.start();
}

function disable() {
    if (indicator) {
        indicator.stop();
        indicator.destroy();
        indicator = null;
    }
}
