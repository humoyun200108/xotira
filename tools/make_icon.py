"""Draws the Xotira app icon (dark tile, lime gauge arc + needle dot) -> app/assets/xotira.ico + icon.png. Needs Pillow."""
import os
from PIL import Image, ImageDraw, ImageFilter

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', 'assets')
S = 1024                       # draw big, downsample for crisp edges
LIME, INK, TILE = (198, 244, 50, 255), (11, 14, 4, 255), (14, 17, 21, 255)

img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=230, fill=TILE, outline=(44, 52, 61, 255), width=10)

# soft lime glow behind the gauge
glow = Image.new('RGBA', (S, S), (0, 0, 0, 0))
ImageDraw.Draw(glow).ellipse((250, 330, 774, 854), fill=(198, 244, 50, 70))
img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(90)))
d = ImageDraw.Draw(img)

# gauge: track + filled arc (the disk), rounded ends
box = (232, 262, 792, 822)
w = 92
d.arc(box, start=180, end=360, fill=(42, 49, 58, 255), width=w)
d.arc(box, start=180, end=318, fill=LIME, width=w)
r = w // 2
cx, cy, rad = 512, 542, 280 - r
for ang in (180, 318):
    import math
    x = cx + rad * math.cos(math.radians(ang))
    y = cy + rad * math.sin(math.radians(ang))
    d.ellipse((x - r, y - r, x + r, y + r), fill=LIME)
# needle hub
d.ellipse((512 - 74, 620 - 74, 512 + 74, 620 + 74), fill=LIME)
d.ellipse((512 - 30, 620 - 30, 512 + 30, 620 + 30), fill=INK)

sizes = [256, 128, 64, 48, 32, 24, 16]
img.resize((256, 256), Image.LANCZOS).save(os.path.join(ASSETS, 'icon.png'))
img.resize((256, 256), Image.LANCZOS).save(os.path.join(ASSETS, 'xotira.ico'), sizes=[(s, s) for s in sizes])
print('ok')
