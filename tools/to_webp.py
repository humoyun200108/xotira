"""Converts docs/screenshots/*.png (from screenshots.cjs) to WebP — about 3x smaller for the README. Needs Pillow."""
import glob
import os

from PIL import Image

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'screenshots')
for png in glob.glob(os.path.join(DIR, '*.png')):
    Image.open(png).convert('RGB').save(png[:-4] + '.webp', 'WEBP', quality=90, method=6)
    os.remove(png)
    print('webp', os.path.basename(png)[:-4])
