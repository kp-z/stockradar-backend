"""从 icon_1024.png 生成 Windows 多分辨率 app_icon.ico"""

import os
from PIL import Image

SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
src = os.path.join(project_root, 'assets', 'icon_1024.png')
dst = os.path.join(project_root, 'assets', 'app_icon.ico')

img = Image.open(src)
img.save(dst, format='ICO', sizes=SIZES)
print(f"Generated {dst}  ({os.path.getsize(dst)} bytes)")
