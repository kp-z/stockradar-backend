# -*- mode: python ; coding: utf-8 -*-
"""StockRadar Windows PyInstaller 打包配置"""

import os

block_cipher = None

# 检测 venv 中 akshare 的 file_fold 路径
_venv_base = os.path.join('.venv', 'Lib', 'site-packages', 'akshare', 'file_fold')
if not os.path.isdir(_venv_base):
    # Python 3.11+ on Windows 也可能是这个路径
    _venv_base = os.path.join('.venv', 'lib', 'site-packages', 'akshare', 'file_fold')
if not os.path.isdir(_venv_base):
    import site
    for sp in site.getsitepackages():
        candidate = os.path.join(sp, 'akshare', 'file_fold')
        if os.path.isdir(candidate):
            _venv_base = candidate
            break

a = Analysis(
    ['app_win.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),
        ('klines_data.json', '.'),
        ('assets/tray_icon.png', 'assets'),
        ('assets/app_icon.ico', 'assets'),
        ('lib', 'lib'),
        (_venv_base, 'akshare/file_fold'),
    ],
    hiddenimports=[
        'platform_dirs',
        'server',
        'ashare_adapter',
        'klines_store',
        'pre_screener',
        'snapshot_updater',
        'supabase_sync',
        'feeds',
        'feeds.realtime',
        'feeds.historical',
        'feeds.stock_list',
        'akshare',
        'mootdx',
        'mootdx.quotes',
        'mootdx.consts',
        'mootdx.utils',
        'tdxpy',
        'websockets',
        'websockets.asyncio',
        'websockets.asyncio.server',
        'websockets.datastructures',
        'pandas',
        'numpy',
        'requests',
        'pystray',
        'pystray._win32',
        'webview',
        'PIL',
        'PIL.Image',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StockRadar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
    version_info=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='StockRadar',
)
