"""Download the UI fonts (SIL Open Font License) into app/assets/fonts so the app never calls Google at runtime."""
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'app', 'assets', 'fonts')
CSS_URL = ('https://fonts.googleapis.com/css2?family=Manrope:wght@400..800&family=Unbounded:wght@500..700'
           '&family=JetBrains+Mono:wght@500..600&display=swap')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36'
KEEP = {'latin', 'latin-ext', 'cyrillic'}
LICENSES = {'Manrope': 'manrope', 'Unbounded': 'unbounded', 'JetBrainsMono': 'jetbrainsmono'}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=60) as r:
        return r.read()


def main():
    os.makedirs(OUT, exist_ok=True)
    css = get(CSS_URL).decode()
    out = []
    for subset, block in re.findall(r'/\* ([\w-]+) \*/\s*(@font-face \{.*?\})', css, re.S):
        if subset not in KEEP:
            continue
        family = re.search(r"font-family: '([^']+)'", block).group(1).replace(' ', '')
        url = re.search(r'url\((https://[^)]+)\)', block).group(1)
        name = f'{family}-{subset}.woff2'
        with open(os.path.join(OUT, name), 'wb') as f:
            f.write(get(url))
        out.append(f'/* {subset} */\n' + block.replace(url, name))
        print('saved', name)
    with open(os.path.join(OUT, 'fonts.css'), 'w', encoding='utf-8') as f:
        f.write('/* Manrope, Unbounded, JetBrains Mono — SIL Open Font License 1.1 (see OFL-*.txt) */\n' + '\n'.join(out) + '\n')
    for fam, slug in LICENSES.items():
        try:
            txt = get(f'https://raw.githubusercontent.com/google/fonts/main/ofl/{slug}/OFL.txt')
            with open(os.path.join(OUT, f'OFL-{fam}.txt'), 'wb') as f:
                f.write(txt)
        except Exception as e:
            print('license download failed', fam, e)


if __name__ == '__main__':
    main()
