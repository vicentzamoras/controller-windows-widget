"""Settings, data paths and the Windows integration bits (autostart, single instance, theme)."""
import ctypes
import json
import os
import sys
import winreg
from pathlib import Path

APP = "SC2Tray"
CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / APP
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "notify_low": True,
    "low_threshold": 15,
    "notify_full": True,
    "notify_disconnect": False,
}


class Config:
    def __init__(self):
        self._d = dict(DEFAULTS)
        try:
            with open(CONFIG_FILE) as f:
                self._d.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self._d[key]

    def toggle(self, key):
        self._d[key] = not self._d[key]
        self.save()

    def save(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(self._d, f, indent=2)
            os.replace(tmp, CONFIG_FILE)
        except OSError:
            pass


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command():
    if getattr(sys, "frozen", False):           # PyInstaller build
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else sys.executable}" -m sc2tray'


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP)
        return True
    except OSError:
        return False


def set_autostart(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(k, APP)
            except FileNotFoundError:
                pass


def taskbar_is_light():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


ERROR_ALREADY_EXISTS = 183


def single_instance():
    """A named mutex held for the process lifetime; None if another instance owns it."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, f"Local\\{APP}-instance")
    if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return handle
