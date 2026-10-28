#!/usr/bin/env python3
"""Ubuntu 桌面 Codex 额度宠物。"""
import argparse
import datetime
import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tempfile
import tkinter as tk
from tkinter import messagebox

spec = importlib.util.spec_from_file_location('codex_quota', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'codex-quota.py'))
quota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quota)

PETS = {'cat': '小猫', 'rabbit': '小兔', 'panda': '熊猫', 'robot': '机器人'}


def config_file():
    """Use the XDG config directory, falling back when it is unset or relative."""
    base = os.environ.get('XDG_CONFIG_HOME', '')
    if not os.path.isabs(base):
        base = os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'codex-quota-pet', 'settings.json')


def load_pet():
    try:
        with open(config_file(), encoding='utf-8') as handle:
            data = json.load(handle)
        pet = data.get('pet') if isinstance(data, dict) else None
        return pet if isinstance(pet, str) and pet in PETS else 'cat'
    except (OSError, ValueError):
        return 'cat'


def save_pet(pet):
    """Atomically save selection; raise OSError so the UI can report failure."""
    if pet not in PETS:
        raise ValueError('未知桌宠')
    target = config_file()
    folder = os.path.dirname(target)
    os.makedirs(folder, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=folder,
                                         prefix='.settings-', delete=False) as handle:
            temporary = handle.name
            json.dump({'pet': pet}, handle, ensure_ascii=False)
            handle.write('\n')
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def summary(result, threshold):
    """最紧张的窗口决定小猫状态，未知值不视作零。"""
    values = []
    for _key, bucket in quota.snapshots(result):
        for key in ('primary', 'secondary'):
            window = bucket.get(key)
            if isinstance(window, dict):
                value = quota.remaining(window)
                if value is not None:
                    values.append(value)
    if not values:
        return '额度未知', False
    minimum = min(values)
    return '最低剩余 {}'.format(quota.percent(minimum)), minimum <= threshold


class Pet:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.result = None
        self.updated = None
        self.error = None
        self.busy = False
        self.timer = None
        self.low = False
        self.closing = False
        self.cancel = threading.Event()
        self.worker = None
        self.messages = queue.Queue()
        self.drag_start = None
        self.dragged = False
        self.pet = args.pet or load_pet()
        self.pet_choice = tk.StringVar(master=root, value=self.pet)
        self.display = ('正在查询…', '稍等一下', 'loading')
        root.title('Codex 额度宠物')
        root.geometry('220x240+100+100')
        root.resizable(False, False)
        root.overrideredirect(True)
        try:
            root.attributes('-topmost', True)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(root, width=220, height=240, bg='#fff8ec', highlightthickness=0, cursor='hand2')
        self.canvas.pack(fill='both', expand=True)
        self.menu = tk.Menu(root, tearoff=False)
        self.menu.add_command(label='查看所有额度', command=self.details)
        self.menu.add_command(label='立即刷新', command=self.refresh)
        self.pet_menu = tk.Menu(self.menu, tearoff=False)
        for key, label in PETS.items():
            self.pet_menu.add_radiobutton(label=label, value=key, variable=self.pet_choice,
                                          command=self.select_pet)
        self.menu.add_cascade(label='切换形象', menu=self.pet_menu)
        self.menu.add_separator()
        self.menu.add_command(label='退出', command=self.close)
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Button-3>', self.show_menu)
        root.bind('<Escape>', lambda event: self.close())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.draw('正在查询…', '稍等一下', 'loading')
        self.refresh()
        self.root.after(120, self.poll)

    def draw(self, caption, status, mood):
        self.display = (caption, status, mood)
        c = self.canvas
        c.delete('all')
        c.create_rectangle(1, 1, 219, 239, fill='#fff8ec', outline='#ecd7b5', width=2)
        # Original vector artwork drawn locally; no image assets or dependencies.
        if self.pet == 'cat':
            c.create_oval(48, 80, 172, 189, fill='#e5a766', outline='#a7673b', width=2)
            c.create_polygon(51, 73, 54, 26, 88, 50, fill='#e5a766', outline='#a7673b', width=2)
            c.create_polygon(132, 50, 166, 26, 169, 73, fill='#e5a766', outline='#a7673b', width=2)
            c.create_polygon(59, 38, 61, 61, 77, 54, fill='#f3c0ae', outline='')
            c.create_polygon(143, 54, 159, 38, 160, 61, fill='#f3c0ae', outline='')
            c.create_oval(48, 43, 172, 140, fill='#eab779', outline='#a7673b', width=2)
            c.create_oval(84, 161, 136, 190, fill='#fff0d9', outline='')
            c.create_line(51, 105, 82, 108, fill='#a7673b'); c.create_line(53, 114, 82, 113, fill='#a7673b')
            c.create_line(138, 108, 169, 105, fill='#a7673b'); c.create_line(138, 113, 167, 114, fill='#a7673b')
        elif self.pet == 'rabbit':
            c.create_oval(51, 81, 169, 190, fill='#e9e2f1', outline='#8e7d9b', width=2)
            c.create_oval(55, 6, 86, 83, fill='#f3e9f5', outline='#8e7d9b', width=2)
            c.create_oval(134, 6, 165, 83, fill='#f3e9f5', outline='#8e7d9b', width=2)
            c.create_oval(65, 17, 77, 67, fill='#f4becb', outline='')
            c.create_oval(143, 17, 155, 67, fill='#f4becb', outline='')
            c.create_oval(48, 49, 172, 143, fill='#f7f1f8', outline='#8e7d9b', width=2)
            c.create_oval(79, 160, 141, 188, fill='#fffafa', outline='')
            c.create_oval(60, 103, 76, 111, fill='#f2c4ce', outline='')
            c.create_oval(144, 103, 160, 111, fill='#f2c4ce', outline='')
        elif self.pet == 'panda':
            c.create_oval(48, 79, 172, 190, fill='#edf0e9', outline='#53645d', width=2)
            c.create_oval(45, 24, 85, 65, fill='#4b5b57', outline='')
            c.create_oval(135, 24, 175, 65, fill='#4b5b57', outline='')
            c.create_oval(48, 42, 172, 143, fill='#f8f8ee', outline='#53645d', width=2)
            c.create_oval(64, 74, 95, 106, fill='#53645d', outline='')
            c.create_oval(125, 74, 156, 106, fill='#53645d', outline='')
            c.create_oval(83, 161, 137, 188, fill='#ffffff', outline='')
        else:
            c.create_line(110, 18, 110, 42, fill='#527b88', width=4)
            c.create_oval(103, 10, 117, 24, fill='#f9c66e', outline='#527b88', width=2)
            c.create_rectangle(52, 98, 168, 186, fill='#92c8cc', outline='#527b88', width=2)
            c.create_oval(58, 147, 74, 165, fill='#f9c66e', outline='')
            c.create_oval(146, 147, 162, 165, fill='#f9c66e', outline='')
            c.create_rectangle(45, 42, 175, 140, fill='#c1e4df', outline='#527b88', width=3)
            c.create_rectangle(91, 156, 129, 173, fill='#f9c66e', outline='#527b88')
        eye = '#ffffff' if self.pet == 'panda' else '#493323'
        c.create_oval(73, 83, 82, 96, fill=eye, outline='')
        c.create_oval(138, 83, 147, 96, fill=eye, outline='')
        c.create_polygon(105, 100, 115, 100, 110, 105, fill='#b66d64', outline='')
        if mood == 'low':
            c.create_arc(96, 107, 124, 121, start=0, extent=180, style='arc', outline='#7b493b', width=2)
        else:
            c.create_arc(96, 101, 124, 119, start=180, extent=180, style='arc', outline='#7b493b', width=2)
        color = '#a03c30' if mood in ('low', 'error') else '#5a4935'
        c.create_text(110, 192, text=caption, font=('TkDefaultFont', 12, 'bold'), fill=color)
        c.create_text(110, 215, text=status, font=('TkDefaultFont', 9), fill='#776452')
        c.create_text(110, 232, text='点击详情 · 拖动 · 右键菜单', font=('TkDefaultFont', 8), fill='#8a7865')

    def select_pet(self):
        self.pet = self.pet_choice.get()
        if self.pet not in PETS:
            self.pet = 'cat'
            self.pet_choice.set(self.pet)
        self.draw(*self.display)
        try:
            save_pet(self.pet)
        except (OSError, ValueError) as exc:
            messagebox.showwarning('无法保存形象',
                                   '本次切换已生效，但无法保存偏好：\n{}'.format(exc),
                                   parent=self.root)

    def press(self, event):
        self.drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self.dragged = False

    def move(self, event):
        if self.drag_start:
            sx, sy, wx, wy = self.drag_start
            dx, dy = event.x_root - sx, event.y_root - sy
            if abs(dx) + abs(dy) > 4:
                self.dragged = True
            if self.dragged:
                x = max(0, min(wx + dx, self.root.winfo_screenwidth() - self.root.winfo_width()))
                y = max(0, min(wy + dy, self.root.winfo_screenheight() - self.root.winfo_height()))
                self.root.geometry('+{}+{}'.format(x, y))

    def release(self, _event):
        if self.drag_start and not self.dragged:
            self.details()
        self.drag_start = None

    def show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def details(self):
        if self.result is None:
            body = '正在查询，请稍候。' if not self.error else '查询失败：\n' + self.error
        else:
            body = quota.format_limits(self.result)
            body += '\n\n最后成功更新：{}'.format(self.updated)
            if self.error:
                body += '\n\n注意：查询失败，以上为旧数据。\n' + self.error
        messagebox.showinfo('Codex 额度详情', body, parent=self.root)

    def refresh(self):
        if self.busy or self.closing:
            return
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        self.busy = True
        if self.result is None:
            self.draw('正在查询…', '稍等一下', 'loading')
        def worker():
            try:
                result = quota.fetch_limits([self.args.codex, 'app-server'], self.args.timeout,
                                            cancel_event=self.cancel)
                # Reject malformed results before displaying them as successful.
                quota.format_limits(result)
                self.messages.put((result, None))
            except Exception as exc:
                self.messages.put((None, str(exc) or '未知错误'))
        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def close(self):
        """Hide promptly, cancel any query and let it reap its app-server child."""
        if self.closing:
            return
        self.closing = True
        self.cancel.set()
        self.root.withdraw()
        self._finish_close()

    def _finish_close(self):
        if self.worker is not None and self.worker.is_alive():
            self.root.after(50, self._finish_close)
        else:
            self.root.destroy()

    def poll(self):
        if self.closing:
            return
        try:
            result, error = self.messages.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.error = error
            if error:
                self.draw('查询失败', '点击查看原因' if self.result is None else '旧数据 · 点击查看原因', 'error')
            else:
                self.result = result
                self.updated = datetime.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
                caption, low = summary(result, self.args.threshold)
                self.draw(caption, '额度偏低' if low else '已更新 ' + datetime.datetime.now().strftime('%H:%M:%S'), 'low' if low else 'normal')
                if low and not self.low and not self.args.no_notify:
                    self.notify(caption)
                self.low = low
            self.timer = self.root.after(int(self.args.interval * 1000), self.refresh)
        self.root.after(120, self.poll)

    def notify(self, text):
        program = shutil.which('notify-send')
        if program:
            try:
                subprocess.Popen([program, 'Codex 额度提醒', text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass


def main():
    p = argparse.ArgumentParser(description='Codex ChatGPT 额度桌面宠物')
    p.add_argument('--codex', default='codex', help='codex 可执行文件路径')
    p.add_argument('--interval', type=quota.positive_float, default=120, help='成功或失败后刷新间隔（秒，默认 120）')
    p.add_argument('--timeout', type=quota.positive_float, default=20, help='查询超时（秒，默认 20）')
    p.add_argument('--threshold', type=quota.threshold_value, default=20, help='低额度阈值百分比（默认 20）')
    p.add_argument('--no-notify', action='store_true', help='关闭桌面通知')
    p.add_argument('--pet', choices=sorted(PETS), help='本次使用的形象（不修改已保存偏好）')
    args = p.parse_args()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print('无法打开桌面窗口：{}。请在 Ubuntu 图形桌面会话运行。'.format(exc), file=sys.stderr)
        return 1
    Pet(root, args)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
