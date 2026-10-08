"""
Where the user's folders really are.

`Path.home() / "Desktop"` is wrong on any Windows machine with OneDrive folder
backup (or a redirected/relocated profile): Explorer shows
C:\\Users\\<you>\\OneDrive\\Desktop, while C:\\Users\\<you>\\Desktop is a stale
folder nobody sees. Writing there "works" and the user never finds the result.
This asks Windows where each folder actually is; the shell writes these keys
whenever a folder is moved, so they follow OneDrive and manual relocation.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

_OS = platform.system()

# Registry value names under "User Shell Folders" for each folder.
_WIN_KEYS = {
    "desktop":   "Desktop",
    "documents": "Personal",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures":  "My Pictures",
    "music":     "My Music",
    "videos":    "My Video",
}
_DEFAULT_NAMES = {
    "desktop": "Desktop", "documents": "Documents", "downloads": "Downloads",
    "pictures": "Pictures", "music": "Music", "videos": "Videos",
}
_XDG = {
    "desktop": "XDG_DESKTOP_DIR", "documents": "XDG_DOCUMENTS_DIR",
    "downloads": "XDG_DOWNLOAD_DIR", "pictures": "XDG_PICTURES_DIR",
    "music": "XDG_MUSIC_DIR", "videos": "XDG_VIDEOS_DIR",
}


def user_folder(kind: str) -> Path:
    """Real location of desktop | documents | downloads | pictures | music | videos."""
    kind = kind.lower()
    if _OS == "Windows" and kind in _WIN_KEYS:
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion"
                    r"\Explorer\User Shell Folders") as key:
                val, _t = winreg.QueryValueEx(key, _WIN_KEYS[kind])
            p = Path(os.path.expandvars(val))
            if p.is_dir():
                return p
        except Exception:
            pass
    elif _OS == "Linux" and kind in _XDG:
        xdg = os.environ.get(_XDG[kind], "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / _DEFAULT_NAMES.get(kind, kind.capitalize())


def desktop() -> Path:
    return user_folder("desktop")
