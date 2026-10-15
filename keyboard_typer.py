"""Keyboard Typer - send text as real Unicode keyboard input on Windows.

This utility deliberately does not use the clipboard. Use it only in windows
where you are authorized to enter the text.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk


if sys.platform != "win32":
    raise SystemExit("This utility requires Windows.")


user32 = ctypes.WinDLL("user32", use_last_error=True)

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_RETURN = 0x0D
VK_TAB = 0x09

WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
MOD_NOREPEAT = 0x4000
VK_F8 = 0x77
HOTKEY_ID = 0x4B54


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL


def send_key_unit(unit: int, key_up: bool = False) -> None:
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if key_up else 0)
    event = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(0, unit, flags, 0, 0),
    )
    sent = user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
    if sent != 1:
        error = ctypes.get_last_error()
        raise ctypes.WinError(error)


def send_virtual_key(vk: int) -> None:
    down = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(vk, 0, 0, 0, 0),
    )
    up = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0),
    )
    events = (INPUT * 2)(down, up)
    sent = user32.SendInput(2, events, ctypes.sizeof(INPUT))
    if sent != 2:
        error = ctypes.get_last_error()
        raise ctypes.WinError(error)


def send_text(text: str, cancelled: threading.Event, interval: float) -> None:
    """Send UTF-16 units so supplementary Unicode characters work too."""
    for character in text:
        if cancelled.is_set():
            return
        if character == "\n":
            send_virtual_key(VK_RETURN)
        elif character == "\t":
            send_virtual_key(VK_TAB)
        else:
            encoded = character.encode("utf-16-le", "surrogatepass")
            for offset in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[offset : offset + 2], "little")
                send_key_unit(unit)
                send_key_unit(unit, key_up=True)
        if interval and cancelled.wait(interval):
            return


class KeyboardTyperApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("键盘输入助手")
        self.root.geometry("620x470")
        self.root.minsize(520, 380)

        self.cancelled = threading.Event()
        self.typing_thread: threading.Thread | None = None
        self.ui_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self.delay_var = tk.StringVar(value="3")
        self.interval_var = tk.StringVar(value="30")
        self.minimize_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="准备就绪。F8 可随时停止。")

        self._build_ui()
        self._start_hotkey_listener()
        self.root.after(100, self._drain_ui_queue)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, text="要输入的文字", font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.text_box = tk.Text(frame, wrap="word", undo=True, height=12)
        self.text_box.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.text_box.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.text_box.configure(yscrollcommand=scrollbar.set)

        options = ttk.LabelFrame(frame, text="输入设置", padding=10)
        options.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        options.columnconfigure(4, weight=1)

        ttk.Label(options, text="启动延迟（秒）").grid(row=0, column=0, sticky="w")
        ttk.Entry(options, textvariable=self.delay_var, width=8).grid(
            row=0, column=1, padx=(6, 18), sticky="w"
        )
        ttk.Label(options, text="字符间隔（毫秒）").grid(row=0, column=2, sticky="w")
        ttk.Entry(options, textvariable=self.interval_var, width=8).grid(
            row=0, column=3, padx=(6, 18), sticky="w"
        )
        ttk.Checkbutton(
            options,
            text="开始后最小化窗口",
            variable=self.minimize_var,
        ).grid(row=0, column=4, sticky="w")

        actions = ttk.Frame(frame)
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        actions.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(actions, text="开始输入", command=self.start_typing)
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.stop_button = ttk.Button(actions, text="停止（F8）", command=self.stop_typing, state="disabled")
        self.stop_button.grid(row=0, column=1)
        ttk.Label(actions, textvariable=self.status_var, foreground="#555555").grid(
            row=0, column=2, padx=(12, 0), sticky="e"
        )

        ttk.Label(
            frame,
            text="用法：点击开始后，在倒计时内切换到目标输入框。工具会逐字发送，不读取或修改剪贴板。",
            foreground="#555555",
            wraplength=570,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(12, 0))

    def _start_hotkey_listener(self) -> None:
        self.hotkey_stop = threading.Event()
        self.hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self.hotkey_thread.start()

    def _hotkey_loop(self) -> None:
        registered = bool(user32.RegisterHotKey(None, HOTKEY_ID, MOD_NOREPEAT, VK_F8))
        if not registered:
            self.ui_queue.put(("status", "F8 注册失败，可使用停止按钮。"))
            return
        message = wintypes.MSG()
        try:
            while not self.hotkey_stop.is_set():
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_REMOVE):
                    if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                        self.cancelled.set()
                time.sleep(0.03)
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                kind, value = self.ui_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(value)
                elif kind == "finished":
                    self._typing_finished(value)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_ui_queue)

    def _parse_number(self, value: str, name: str, minimum: float, maximum: float) -> float:
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError(f"{name}必须是数字。") from exc
        if not minimum <= number <= maximum:
            raise ValueError(f"{name}应在 {minimum:g} 到 {maximum:g} 之间。")
        return number

    def start_typing(self) -> None:
        if self.typing_thread and self.typing_thread.is_alive():
            return
        text = self.text_box.get("1.0", "end-1c")
        if not text:
            messagebox.showwarning("没有文字", "请先输入要发送的文字。")
            return
        try:
            delay = self._parse_number(self.delay_var.get(), "启动延迟", 0, 60)
            interval = self._parse_number(self.interval_var.get(), "字符间隔", 0, 10000) / 1000
        except ValueError as error:
            messagebox.showerror("设置无效", str(error))
            return

        self.cancelled.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set(f"将在 {delay:g} 秒后开始，请切换到目标窗口。")
        if self.minimize_var.get():
            self.root.iconify()
        self.typing_thread = threading.Thread(
            target=self._type_worker,
            args=(text, delay, interval),
            daemon=True,
        )
        self.typing_thread.start()

    def _type_worker(self, text: str, delay: float, interval: float) -> None:
        if self.cancelled.wait(delay):
            self.ui_queue.put(("finished", "已停止。"))
            return
        try:
            send_text(text, self.cancelled, interval)
            result = "已停止。" if self.cancelled.is_set() else "输入完成。"
        except Exception as error:  # keep UI responsive if SendInput fails
            result = f"发送失败：{error}"
        self.ui_queue.put(("finished", result))

    def stop_typing(self) -> None:
        self.cancelled.set()
        self.status_var.set("正在停止……")

    def _typing_finished(self, status: str) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set(status)
        if self.root.state() == "iconic":
            self.root.deiconify()
            self.root.lift()

    def close(self) -> None:
        self.cancelled.set()
        self.hotkey_stop.set()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        ttk.Style(root).theme_use("vista")
    except tk.TclError:
        pass
    KeyboardTyperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
