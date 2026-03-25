"""跨平台数据目录 — macOS / Windows / Linux"""

import sys
import os
import platform


def get_data_dir() -> str:
    """可读写的用户数据目录（SQLite、缓存等）。
    开发模式返回项目根目录，打包后按平台返回标准位置。
    """
    if not getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(__file__))

    system = platform.system()
    if system == 'Darwin':
        base = os.path.expanduser('~/Library/Application Support')
    elif system == 'Windows':
        base = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    else:
        base = os.environ.get('XDG_DATA_HOME',
                              os.path.expanduser('~/.local/share'))

    data_dir = os.path.join(base, 'StockRadar')
    os.makedirs(data_dir, exist_ok=True)
    return data_dir
