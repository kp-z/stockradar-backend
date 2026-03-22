"""
StockRadar Mac 菜单栏应用 (popover 版本)
- pyobjc: NSStatusItem + NSPopover + WKWebView
- asyncio: 后台线程运行 WebSocket 服务器
"""

import sys
import os
import threading
import asyncio
import webbrowser

import objc
from AppKit import (
    NSApplication,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSPopover,
    NSViewController,
    NSMakeRect,
    NSApp,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSEvent,
    NSAlert,
    NSAlertFirstButtonReturn,
    NSWindow,
    NSBackingStoreBuffered,
    NSScreen,
)
from Foundation import NSObject, NSURL, NSURLRequest, NSUserDefaults
from WebKit import WKWebView, WKWebViewConfiguration
from PyObjCTools import AppHelper


WS_PORT = int(os.environ.get('PORT', 31749))
SERVER_URL = f"http://localhost:{WS_PORT}"

POPOVER_WIDTH = 1100
POPOVER_HEIGHT = 680

FIRST_RUN_KEY = "StockRadarHasLaunched"


def _resource_path(relative):
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


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


# ── WebView 控制器 ──

class WebViewController(NSViewController):
    def loadView(self):
        config = WKWebViewConfiguration.alloc().init()
        frame = NSMakeRect(0, 0, POPOVER_WIDTH, POPOVER_HEIGHT)
        self.webView = WKWebView.alloc().initWithFrame_configuration_(frame, config)
        self.setView_(self.webView)

    def viewDidLoad(self):
        url = NSURL.URLWithString_(SERVER_URL)
        request = NSURLRequest.requestWithURL_(url)
        self.webView.loadRequest_(request)


# ── 菜单栏控制器 ──

class StatusBarController(NSObject):
    def init(self):
        self = objc.super(StatusBarController, self).init()
        if self is None:
            return None

        self._detached_window = None

        # Popover
        self.popover = NSPopover.alloc().init()
        self.popover.setBehavior_(1)  # NSPopoverBehaviorTransient
        self.popover.setContentSize_((POPOVER_WIDTH, POPOVER_HEIGHT))
        self.popover.setAnimates_(True)

        vc = WebViewController.alloc().init()
        self.popover.setContentViewController_(vc)

        # 状态栏图标
        self.statusItem = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )

        icon_path = _resource_path('assets/tray_icon.png')
        if os.path.exists(icon_path):
            icon = NSImage.alloc().initWithContentsOfFile_(icon_path)
            icon.setSize_((20, 20))
            self.statusItem.button().setImage_(icon)
        else:
            self.statusItem.button().setTitle_("SR")

        # 左键 action → toggle popover
        self.statusItem.button().setAction_(
            objc.selector(self.togglePopover_, signature=b'v@:@')
        )
        self.statusItem.button().setTarget_(self)

        # 构建右键菜单（不调用 setMenu_，手动弹出）
        self._menu = NSMenu.alloc().init()

        open_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "在浏览器中打开",
            objc.selector(self.openInBrowser_, signature=b'v@:@'),
            "",
        )
        open_item.setTarget_(self)
        self._menu.addItem_(open_item)

        win_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "在窗口中打开",
            objc.selector(self.openInWindow_, signature=b'v@:@'),
            "",
        )
        win_item.setTarget_(self)
        self._menu.addItem_(win_item)

        self._menu.addItem_(NSMenuItem.separatorItem())

        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "退出 StockRadar",
            objc.selector(self.quitApp_, signature=b'v@:@'),
            "",
        )
        quit_item.setTarget_(self)
        self._menu.addItem_(quit_item)

        # 监听右键事件弹出菜单
        # NSEventMaskRightMouseUp = 1 << 4
        NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            1 << 4, self._handleRightClick
        )

        return self

    @objc.python_method
    def _handleRightClick(self, event):
        """右键点击时检查是否在状态栏按钮上"""
        button = self.statusItem.button()
        loc = event.locationInWindow()
        if button.window() and event.window() == button.window():
            self.statusItem.popUpStatusItemMenu_(self._menu)
            return None  # 消耗事件
        return event

    @objc.python_method
    def _show_popover(self):
        button = self.statusItem.button()
        self.popover.showRelativeToRect_ofView_preferredEdge_(
            button.bounds(), button, 2  # NSMinYEdge
        )
        NSApp.activateIgnoringOtherApps_(True)

    @objc.python_method
    def _hide_popover(self):
        self.popover.performClose_(None)

    def togglePopover_(self, sender):
        if self.popover.isShown():
            self._hide_popover()
        else:
            self._show_popover()

    def openInWindow_(self, sender):
        """在独立 Mac 窗口中打开"""
        if self._detached_window and self._detached_window.isVisible():
            self._detached_window.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
            return

        # 切换到 Regular 模式才能显示标题栏红绿灯按钮
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)

        # NSWindowStyleMask: titled=1, closable=2, miniaturizable=4, resizable=8
        style_mask = 1 | 2 | 4 | 8
        rect = NSMakeRect(0, 0, POPOVER_WIDTH, POPOVER_HEIGHT)
        self._detached_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, NSBackingStoreBuffered, False
        )
        self._detached_window.setTitle_("StockRadar - 异动雷达")
        self._detached_window.center()
        self._detached_window.setReleasedWhenClosed_(False)

        config = WKWebViewConfiguration.alloc().init()
        webview = WKWebView.alloc().initWithFrame_configuration_(rect, config)
        url = NSURL.URLWithString_(SERVER_URL)
        request = NSURLRequest.requestWithURL_(url)
        webview.loadRequest_(request)
        self._detached_window.setContentView_(webview)

        self._detached_window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)

    def openInBrowser_(self, sender):
        webbrowser.open(SERVER_URL)

    def quitApp_(self, sender):
        _stop_server()
        NSApp.terminate_(None)


def _show_first_run_alert():
    """首次运行时显示使用提示"""
    defaults = NSUserDefaults.standardUserDefaults()
    if defaults.boolForKey_(FIRST_RUN_KEY):
        return

    alert = NSAlert.alloc().init()
    alert.setMessageText_("StockRadar 已在菜单栏运行!")
    alert.setInformativeText_(
        "点击菜单栏的雷达图标查看行情面板\n"
        "右键点击图标查看更多选项\n\n"
        "提示：右键菜单可「在窗口中打开」独立窗口"
    )
    alert.addButtonWithTitle_("知道了")
    alert.runModal()

    defaults.setBool_forKey_(True, FIRST_RUN_KEY)


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    # 后台线程启动服务器
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    # 主线程创建菜单栏控制器
    controller = StatusBarController.alloc().init()

    global _status_bar_controller
    _status_bar_controller = controller

    # 首次运行提示
    _show_first_run_alert()

    AppHelper.runEventLoop()


if __name__ == '__main__':
    main()
