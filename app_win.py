"""
StockRadar Windows 系统托盘应用
- pystray: 系统托盘图标 + 右键菜单
- pywebview: Edge WebView2 嵌入式浏览器窗口
- asyncio: 后台线程运行 WebSocket 服务器
"""

import sys
import os
import threading
import asyncio
import webbrowser
import json

import pystray
from PIL import Image

WS_PORT = int(os.environ.get('PORT', 31749))
SERVER_URL = f"http://localhost:{WS_PORT}"

WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 680

_PREFS_KEY = 'has_launched'


def _resource_path(relative):
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


def _prefs_path():
    from platform_dirs import get_data_dir
    return os.path.join(get_data_dir(), 'prefs.json')


def _load_prefs():
    path = _prefs_path()
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_prefs(prefs):
    with open(_prefs_path(), 'w', encoding='utf-8') as f:
        json.dump(prefs, f)


# ── asyncio 服务器管理 ──

_server_loop = None


def _start_server():
    global _server_loop
    _server_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_server_loop)
    from server import main as server_main
    _server_loop.run_until_complete(server_main())


def _stop_server():
    if _server_loop and _server_loop.is_running():
        _server_loop.call_soon_threadsafe(_server_loop.stop)


# ── WebView 管理 ──

_webview_window = None
_webview_started = threading.Event()


def _start_webview():
    """在独立线程中启动 pywebview（Edge WebView2 后端）"""
    import webview

    global _webview_window
    _webview_window = webview.create_window(
        'StockRadar - 异动雷达',
        SERVER_URL,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        hidden=True,
    )
    _webview_started.set()
    webview.start()


def _toggle_window():
    """切换 WebView 窗口的显示/隐藏"""
    if not _webview_started.is_set():
        return
    if _webview_window is None:
        return
    try:
        if _webview_window.hidden:
            _webview_window.show()
        else:
            _webview_window.hide()
    except Exception:
        pass


def _show_window():
    if _webview_started.is_set() and _webview_window:
        try:
            _webview_window.show()
        except Exception:
            pass


# ── 系统托盘 ──

def _on_open_browser(icon, item):
    webbrowser.open(SERVER_URL)


def _on_open_window(icon, item):
    _show_window()


def _on_quit(icon, item):
    _stop_server()
    icon.stop()
    if _webview_window:
        try:
            _webview_window.destroy()
        except Exception:
            pass
    os._exit(0)


def _on_tray_click(icon, item):
    """左键点击托盘图标 → 切换窗口"""
    _toggle_window()


def _build_menu():
    return pystray.Menu(
        pystray.MenuItem("在浏览器中打开", _on_open_browser),
        pystray.MenuItem("在窗口中打开", _on_open_window),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出 StockRadar", _on_quit),
    )


def _show_first_run_notification(icon):
    prefs = _load_prefs()
    if prefs.get(_PREFS_KEY):
        return
    icon.notify(
        "点击系统托盘的雷达图标查看行情面板\n右键点击图标查看更多选项",
        "StockRadar 已在系统托盘运行!",
    )
    prefs[_PREFS_KEY] = True
    _save_prefs(prefs)


def _on_tray_ready(icon):
    """托盘图标就绪后的回调"""
    icon.visible = True

    # 启动后台 WebSocket 服务器
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    # 启动 WebView（独立线程）
    webview_thread = threading.Thread(target=_start_webview, daemon=True)
    webview_thread.start()

    # 首次运行通知
    _show_first_run_notification(icon)


def main():
    icon_path = _resource_path('assets/tray_icon.png')
    if os.path.exists(icon_path):
        image = Image.open(icon_path)
    else:
        # 16x16 纯色 fallback
        image = Image.new('RGB', (16, 16), color='dodgerblue')

    icon = pystray.Icon(
        name='StockRadar',
        icon=image,
        title='StockRadar - 异动雷达',
        menu=_build_menu(),
    )

    # pystray 在 Windows 上支持默认左键动作
    icon.default_action = _on_tray_click

    icon.run(setup=_on_tray_ready)


if __name__ == '__main__':
    main()
