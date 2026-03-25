# -*- mode: python ; coding: utf-8 -*-
"""StockRadar PyInstaller 打包配置"""

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('frontend', 'frontend'),
        ('klines_data.json', '.'),
        ('assets/tray_icon.png', 'assets'),
        ('lib', 'lib'),
        ('.venv/lib/python3.13/site-packages/akshare/file_fold', 'akshare/file_fold'),
    ],
    hiddenimports=[
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
        'rumps',
        'objc',
        'AppKit',
        'Foundation',
        'WebKit',
        'PyObjCTools',
        'PyObjCTools.AppHelper',
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

app = BUNDLE(
    coll,
    name='StockRadar.app',
    icon='assets/app_icon.icns',
    bundle_identifier='com.stockradar.desktop',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleShortVersionString': '1.8.5',
        'CFBundleDisplayName': 'StockRadar',
        'LSUIElement': True,
    },
)
