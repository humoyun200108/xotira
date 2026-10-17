"""Builds app/demo.json — believable sample data for the demo page and README screenshots (no real files involved)."""
import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
sys.argv = ['make_demo', '--no-scan']
import server  # noqa: E402  (only for the bilingual cleanup target titles)

B = server.B
G = 1024 ** 3
M = 1024 ** 2
NOW = int(time.time())
DAY = 86400
HOME = r'C:\Users\Aziz'
STEAM = r'C:\Program Files (x86)\Steam\steamapps'
random.seed(7)

TOTAL = 1_000_202_273_280            # a "1 TB" drive
USED = int(869.0 * G)
FREE = TOTAL - USED


def gb(x):
    return int(x * G)


# ------------------------------------------------------------------ smart cleanup
SIZES = {'user-temp': 6.1, 'win-temp': 2.4, 'wu-cache': 3.9, 'delivery': 1.2, 'crash-user': 0.8, 'crash-sys': 0.3,
         'win-logs': 0.5, 'inetcache': 0.2, 'thumbs': 0.6, 'shader': 19.2, 'nvidia-dl': 2.1, 'chrome': 14.1, 'edge': 0.9,
         'yandex': 2.3, 'telegram': 9.8, 'discord': 0.7, 'editors': 1.6, 'capcut': 5.4, 'steam': 1.1, 'spotify': 1.3,
         'ae-disk': 22.4, 'adobe-temp': 0.1, 'adobe': 3.2, 'cameraraw': 0.4, 'npm': 2.6, 'pip': 1.9, 'uv': 0.4,
         'electron-dl': 0.3, 'playwright': 0.8, 'hf': 6.2}
smart = []
for t in server.TARGETS:
    d = {k: t[k] for k in ('id', 'group', 'title', 'desc', 'risk', 'admin', 'note', 'kind', 'age')}
    size = SIZES.get(t['id'])
    d.update(state='done', denied=bool(t['admin']), exists=bool(size) or t['kind'] != 'clean', paths=[], npaths=1)
    if t['kind'] == 'clean':
        d.update(size=gb(size) if size else 0, count=int((size or 0) * 4100), exists=bool(size))
    elif t['id'] == 'recycle':
        d.update(size=gb(7.4), count=341, exists=True)
    elif t['id'] == 'hiber':
        d.update(size=gb(12.7), exists=True)
    elif t['id'] == 'winold':
        d.update(size=0, exists=False)
    else:
        d.update(size=None)
    smart.append(d)

# ------------------------------------------------------------------ games
games = [
    dict(name='Skyforge Legends', size=112.4, played=3, updating=True, dl=(29.6, 47.8), shader=1.9),
    dict(name='Neon Drift X', size=74.2, played=143, shader=0.8),
    dict(name='Tundra Rally 2', size=48.1, played=9, shader=0.6),
    dict(name='Pixel Siege', size=31.3, played=241),
    dict(name='Orbit Tactics', size=20.6, played=None),
]
game_items = []
for i, g in enumerate(games):
    folder = os.path.join(STEAM, 'common', g['name'])
    dl = g.get('dl')
    game_items.append(dict(id=f'steam:{1100 + i}', appid=str(1100 + i), store='steam', name=g['name'], path=folder,
                           size=gb(g['size']), shader=gb(g.get('shader', 0)), downloading=0,
                           last_played=NOW - g['played'] * DAY if g['played'] is not None else None,
                           last_updated=NOW - 2 * DAY, updating=bool(g.get('updating')),
                           dl_total=gb(dl[1]) if dl else 0, dl_done=gb(dl[0]) if dl else 0, cover=False))


# ------------------------------------------------------------------ breakdown ("why is my disk full")
def items(*rows):
    return [dict(size=gb(s), path=p, name=n if n else os.path.basename(p.rstrip('\\*')) or p, files=p.endswith('\\*')) for n, p, s in rows]


cache_titles = {t['id']: t['title'] for t in server.TARGETS}
buckets = [
    ('games', 286.6, [(g['name'], g['path'], g['size'] / G) for g in game_items], [['other', 241], ['system', 38], ['video', 7.6]]),
    ('downloads', 118.0, [(B("Papkadagi fayllar", "Loose files in folder"), HOME + r'\Downloads\*', 71.3), (None, HOME + r'\Downloads\Telegram Desktop', 21.4),
                          (None, HOME + r'\Downloads\Kurslar', 11.2), (None, HOME + r'\Downloads\Toy videosi 2025', 8.9)],
     [['video', 84.2], ['archive', 14.1], ['installer', 9.6], ['image', 4.4]]),
    ('appdata', 88.0, [(None, HOME + r'\AppData\Local\Google', 12.8), (None, HOME + r'\AppData\Roaming\Telegram Desktop', 10.4),
                       (None, HOME + r'\AppData\Local\CapCut', 8.9), (None, HOME + r'\AppData\Roaming\Adobe', 7.1),
                       (None, r'C:\ProgramData\NVIDIA Corporation', 6.2), (None, HOME + r'\AppData\Local\Microsoft', 5.5)],
     [['other', 41], ['system', 27], ['cache', 12]]),
    ('programs', 72.0, [('Program Files › Adobe', r'C:\Program Files\Adobe', 24.6), (None, r'C:\Program Files\Microsoft Office', 6.1),
                        (None, r'C:\Program Files (x86)\Steam', 4.2), (None, r'C:\Program Files\Blackmagic Design', 3.8)],
     [['system', 39], ['other', 22], ['installer', 6]]),
    ('windows', 64.0, [(None, r'C:\Windows\WinSxS', 18.4), (None, r'C:\pagefile.sys', 16.0), (None, r'C:\hiberfil.sys', 12.7),
                       (None, r'C:\Windows\System32', 9.8), (None, r'C:\Windows\Installer', 4.2)], [['system', 51], ['other', 9]]),
    ('cache', 61.0, [(cache_titles['ae-disk'], HOME + r'\AppData\Local\Temp\Adobe\After Effects', 22.4),
                     (cache_titles['shader'], HOME + r'\AppData\Local\NVIDIA\DXCache', 19.2),
                     (cache_titles['chrome'], HOME + r'\AppData\Local\Google\Chrome\User Data', 14.1),
                     (cache_titles['user-temp'], HOME + r'\AppData\Local\Temp', 6.1)], [['other', 44], ['cache', 17]]),
    ('user', 78.0, [(None, HOME + r'\Documents', 31.2), (None, HOME + r'\Desktop', 18.6), (None, HOME + r'\Videos', 12.9),
                    (None, HOME + r'\Pictures', 9.4), (None, r'C:\Projects', 5.9)], [['video', 22.4], ['image', 17.8], ['project', 14.2], ['document', 6.1]]),
    ('virtual', 46.0, [(None, r'C:\ProgramData\BlueStacks_nxt', 21.4), (None, HOME + r'\AppData\Local\wsl', 14.2), (None, r'C:\LDPlayer', 10.4)],
     [['archive', 38], ['other', 8]]),
    ('dev', 22.0, [(None, HOME + r'\AppData\Local\Android', 7.4), ('shop-app › node_modules', r'C:\Projects\shop-app\node_modules', 4.6),
                   (None, HOME + r'\.cache', 3.2), ('landing › node_modules', r'C:\Projects\landing\node_modules', 3.5)], [['other', 12], ['system', 6]]),
    ('ai', 18.0, [(None, r'C:\ProgramData\Topaz Labs LLC', 9.2), (None, r'C:\Projects\sd\sd_xl_base_1.0.safetensors', 5.9),
                  ('Systran/faster-whisper-large-v3', HOME + r'\.cache\huggingface\hub\models--Systran--faster-whisper-large-v3', 2.9)],
     [['model', 12], ['other', 6]]),
    ('hidden', 8.6, [], []),
    ('recycle', 7.4, [(None, r'C:\$Recycle.Bin', 7.4)], []),
]
breakdown = dict(ts=NOW, root='C:\\', drive=True, total=TOTAL, used=USED, free=FREE, scanned=USED - gb(8.6), over=0,
                 buckets=[dict(id=b, size=gb(s), items=items(*rows), comp=[[c, gb(v)] for c, v in comp]) for b, s, rows, comp in buckets])

# ------------------------------------------------------------------ map (folder tree, sizes in GB)
TREE = {
    'C:\\': {'Users': 360.6, 'Program Files (x86)': 291.0, 'Program Files': 98.4, 'Windows': 35.3, 'ProgramData': 47.9,
             'pagefile.sys': 16.0, 'hiberfil.sys': 12.7, 'LDPlayer': 10.4, 'Projects': 21.3},
    'C:\\Users': {'Aziz': 358.9, 'Public': 1.7},
    HOME: {'AppData': 128.4, 'Downloads': 118.0, 'Documents': 31.2, 'Desktop': 18.6, 'Videos': 12.9, 'Pictures': 9.4, '.cache': 12.3},
    HOME + r'\AppData': {'Local': 96.8, 'Roaming': 30.9, 'LocalLow': 0.7},
    HOME + r'\AppData\Local': {'Temp': 28.5, 'Google': 12.8, 'NVIDIA': 19.4, 'CapCut': 8.9, 'wsl': 14.2, 'Android': 7.4, 'Microsoft': 5.6},
    HOME + r'\Downloads': {'Telegram Desktop': 21.4, 'Kurslar': 11.2, 'Toy videosi 2025': 8.9, 'film_1080p_final.mp4': 6.4,
                           'Windows11_24H2.iso': 5.6, 'jonli_efir_yozuvi.mp4': 4.9, 'DaVinci_Resolve_20.exe': 2.8, 'node-v22.msi': 0.03},
    'C:\\Program Files (x86)': {'Steam': 290.8, 'Microsoft': 0.2},
    'C:\\Program Files (x86)\\Steam': {'steamapps': 286.6, 'appcache': 3.1, 'package': 1.1},
    STEAM: {'common': 286.6},
    STEAM + '\\common': {g['name']: g['size'] for g in games},
}
FILE_EXT = {'.mp4': 'video', '.iso': 'archive', '.exe': 'installer', '.msi': 'installer', '.sys': 'system'}


def children(path):
    kids = TREE.get(path, {})
    out = []
    for name, size in sorted(kids.items(), key=lambda kv: -kv[1]):
        p = os.path.join(path, name)
        ext = os.path.splitext(name)[1].lower()
        is_dir = ext not in FILE_EXT
        it = dict(name=name, path=p, dir=is_dir, size=gb(size), mtime=NOW - random.randint(1, 400) * DAY)
        if is_dir:
            it.update(files=int(size * random.randint(900, 4000)), dirs=int(size * 30))
        else:
            it['cat'] = FILE_EXT[ext]
        if p in (r'C:\Users', r'C:\Program Files (x86)', r'C:\Program Files', r'C:\Windows', r'C:\ProgramData', HOME,
                 HOME + r'\AppData', HOME + r'\Downloads', HOME + r'\Documents', HOME + r'\Desktop', HOME + r'\Videos',
                 HOME + r'\Pictures', r'C:\pagefile.sys', r'C:\hiberfil.sys') or p.startswith(r'C:\Program Files'):
            it['prot'] = B("Muhim tizim yoki foydalanuvchi papkasi", "Important system or user folder")
        if p.startswith(HOME + r'\AppData'):
            it['warn'] = B("Dastur maʼlumotlari", "App data")
        out.append(it)
    return out


tree = {p: children(p) for p in TREE}

# ------------------------------------------------------------------ large files
BIG = [
    (HOME + r'\Downloads\Telegram Desktop\video_2025-11-03_21-44-12.mp4', 7.8, 'video', 210),
    (HOME + r'\Downloads\film_1080p_final.mp4', 6.4, 'video', 160),
    (HOME + r'\Downloads\Windows11_24H2.iso', 5.6, 'archive', 300),
    (HOME + r'\Downloads\jonli_efir_yozuvi.mp4', 4.9, 'video', 95),
    (HOME + r'\Downloads\Toy videosi 2025\toy_4k_part1.mp4', 4.6, 'video', 330),
    (HOME + r'\Downloads\Toy videosi 2025\toy_4k_part2.mp4', 4.3, 'video', 330),
    (HOME + r'\Videos\Captures\stream_2026-08-14.mp4', 3.9, 'video', 64),
    (HOME + r'\Documents\Zoom\darslik_yozuvi.mp4', 3.1, 'video', 410),
    (HOME + r'\Downloads\DaVinci_Resolve_20.exe', 2.8, 'installer', 40),
    (r'C:\Projects\sd\sd_xl_base_1.0.safetensors', 5.9, 'model', 220),
    (HOME + r'\Downloads\Kurslar\python_kurs.zip', 3.4, 'archive', 520),
    (HOME + r'\Desktop\eski_telefon_backup.zip', 9.1, 'archive', 610),
    (HOME + r'\Pictures\RAW\2025_toy\IMG_4411.CR3', 0.06, 'image', 300),
    (HOME + r'\Documents\montaj\reklama_final_v7.prproj', 0.4, 'project', 30),
    (HOME + r'\Downloads\Telegram Desktop\audiokitob.mp3', 0.9, 'audio', 140),
    (HOME + r'\Downloads\Office_2024_setup.exe', 4.2, 'installer', 260),
    (HOME + r'\Downloads\Kurslar\figma_kurs.rar', 2.7, 'archive', 300),
    (HOME + r'\Downloads\Telegram Desktop\konsert_2024.mkv', 3.6, 'video', 400),
    (r'C:\pagefile.sys', 16.0, 'system', 0),
    (r'C:\hiberfil.sys', 12.7, 'system', 0),
]
big = []
for p, s, c, age in BIG:
    it = dict(path=p, name=os.path.basename(p), size=gb(s), mtime=NOW - age * DAY - 3600, cat=c, sys=p.startswith('C:\\') and p.count('\\') == 1)
    if it['sys']:
        it['prot'] = B("Windows tizim fayli", "Windows system file")
    big.append(it)

types = dict(cats=[dict(cat=c, size=gb(s), count=n, exts=[dict(ext=e, size=gb(s * f), count=int(n * f)) for e, f in ex]) for c, s, n, ex in [
    ('other', 268, 412000, [('.pak', .4), ('.dat', .2), ('(kengaytmasiz)', .2)]), ('video', 121.4, 1830, [('.mp4', .8), ('.mkv', .12), ('.mov', .08)]),
    ('system', 104, 291000, [('.dll', .5), ('.sys', .3), ('.mui', .1)]), ('archive', 64, 950, [('.zip', .5), ('.vhdx', .3), ('.iso', .2)]),
    ('image', 26, 48200, [('.jpg', .5), ('.png', .3), ('.cr3', .2)]), ('installer', 22, 3100, [('.exe', .7), ('.msi', .3)]),
    ('model', 13, 140, [('.safetensors', .6), ('.onnx', .4)]), ('project', 9.8, 520, [('.prproj', .4), ('.aep', .4), ('.blend', .2)]),
    ('document', 6.1, 9400, [('.pdf', .6), ('.docx', .2), ('.xlsx', .2)]), ('audio', 4.2, 3800, [('.mp3', .6), ('.wav', .4)]),
    ('cache', 3.9, 21000, [('.tmp', .5), ('.log', .5)])]],
    exts=[dict(ext=e, size=gb(s), count=n, cat=c) for e, s, n, c in [
        ('.pak', 107, 640, 'other'), ('.mp4', 97, 1460, 'video'), ('.dll', 52, 148000, 'system'), ('.vhdx', 31, 4, 'archive'),
        ('.zip', 22, 610, 'archive'), ('.sys', 31, 3200, 'system'), ('.exe', 15, 2400, 'installer'), ('.jpg', 13, 24000, 'image'),
        ('.mkv', 14.6, 120, 'video'), ('.safetensors', 7.8, 12, 'model'), ('.iso', 12.8, 6, 'archive'), ('.png', 7.8, 14500, 'image')]], state='done')

junk = dict(scanned=True, state='done', items=[dict(path=p, kind=k, size=gb(s), files=int(s * 9000), mtime=NOW - d * DAY, project=os.path.dirname(p)) for p, k, s, d in [
    (r'C:\Projects\shop-app\node_modules', 'node_modules', 4.6, 12), (r'C:\Projects\landing\node_modules', 'node_modules', 3.5, 160),
    (r'C:\Projects\telegram-bot\.venv', 'Python venv', 1.9, 230), (r'C:\Projects\portfolio\.next', 'Next.js build', 0.8, 120),
    (r'C:\Projects\old-crm\node_modules', 'node_modules', 2.4, 400)]])
junk['total'] = sum(i['size'] for i in junk['items'])

dl_items = lambda rows: [dict(path=HOME + '\\Downloads\\' + n, name=n, size=gb(s), mtime=NOW - d * DAY, cat=c) for n, s, c, d in rows]
downloads = dict(path=HOME + r'\Downloads', total=gb(118), count=2841, groups={
    'installers': dl_items([('Office_2024_setup.exe', 4.2, 'installer', 260), ('DaVinci_Resolve_20.exe', 2.8, 'installer', 40),
                            ('ChromeSetup.exe', 0.01, 'installer', 90), ('Telegram_setup.exe', 0.05, 'installer', 200), ('node-v22.msi', 0.03, 'installer', 300)]),
    'extracted': dl_items([('Kurslar\\python_kurs.zip', 3.4, 'archive', 520), ('Kurslar\\figma_kurs.rar', 2.7, 'archive', 300)]),
    'videos': dl_items([('Telegram Desktop\\video_2025-11-03_21-44-12.mp4', 7.8, 'video', 210), ('film_1080p_final.mp4', 6.4, 'video', 160),
                        ('jonli_efir_yozuvi.mp4', 4.9, 'video', 95), ('Telegram Desktop\\konsert_2024.mkv', 3.6, 'video', 400)]),
    'old': dl_items([('Windows11_24H2.iso', 5.6, 'archive', 300), ('Telegram Desktop\\eski_rasmlar.zip', 1.2, 'archive', 420)])})
for k, g in downloads['groups'].items():
    downloads['groups'][k] = dict(items=g, size=sum(i['size'] for i in g), count=len(g))

apps = [dict(key=f'demo|{i}', name=n, version=v, publisher=p, size=gb(s), src='scan' if i % 3 == 0 else 'reg', location='', date=dt)
        for i, (n, v, p, s, dt) in enumerate([
            ('Adobe Premiere Pro 2026', '26.1', 'Adobe Inc.', 10.2, '2026-03-02'), ('Adobe After Effects 2026', '26.3', 'Adobe Inc.', 8.7, '2026-03-02'),
            ('BlueStacks 5', '5.21', 'BlueStacks', 21.4, '2025-06-14'), ('Microsoft Office Professional Plus 2024', '16.0', 'Microsoft', 6.1, '2025-02-10'),
            ('DaVinci Resolve', '20.0', 'Blackmagic Design', 3.8, '2026-08-21'), ('LDPlayer 9', '9.1', 'XUANZHI', 10.4, '2025-09-30'),
            ('Steam', '2.10', 'Valve', 4.2, '2024-11-05'), ('Telegram Desktop', '6.2', 'Telegram FZ-LLC', 0.4, '2026-09-28'),
            ('Visual Studio Code', '1.104', 'Microsoft', 0.6, '2026-10-01'), ('CapCut', '7.4', 'Bytedance', 1.2, '2026-07-12'),
            ('OBS Studio', '32.0', 'OBS Project', 0.5, '2026-05-17'), ('NVIDIA App', '11.0', 'NVIDIA', 1.1, '2026-09-02'),
            ('Discord', '1.0', 'Discord Inc.', 0.4, '2026-04-08'), ('Spotify', '1.2', 'Spotify AB', 0.5, '2025-12-22'),
            ('Python 3.13', '3.13.7', 'Python Software Foundation', 0.2, '2026-06-03'), ('Node.js', '22.11', 'OpenJS Foundation', 0.1, '2026-06-03')])]
apps.sort(key=lambda a: -a['size'])

# ------------------------------------------------------------------ progress history: 9 days, two cleanups
t0 = NOW - 9 * DAY
events = [dict(ts=NOW - 4 * DAY - 7200, kind='clean', title=B("Aqlli tozalash · 9 ta joy", "Smart cleanup · 9 places"), bytes=gb(21.6)),
          dict(ts=NOW - 2 * DAY - 3000, kind='delete', title=B("3 ta fayl/papka oʻchirildi", "3 files/folders deleted"), bytes=gb(16.0)),
          dict(ts=NOW - 5 * 3600, kind='recycle-move', title=B("Savatga tashlandi · 12 ta", "Moved to Recycle Bin · 12"), bytes=gb(7.4))]
# walk backwards from today's free space: games, downloads and caches keep eating space, cleanups give it back
steps = 9 * 24 * 2
samples, free = [], FREE
for i in range(steps, -1, -1):
    ts = t0 + i * 1800
    samples.append([ts, free, TOTAL - free, TOTAL])
    free += int(random.uniform(0.04, 0.2) * G)
    for e in events[:2]:
        if ts - 1800 < e['ts'] <= ts:
            free -= e['bytes']
samples.reverse()
samples[-1] = [NOW, FREE, USED, TOTAL]

growth = dict(ready=True, from_ts=NOW - 2 * DAY, to_ts=NOW - 600, used_delta=gb(9.4), scans=[],
              items=[dict(path=STEAM + r'\common\Skyforge Legends', delta=gb(18.2), now=gb(112.4)),
                     dict(path=HOME + r'\Desktop\eski loyiha', delta=-gb(11.8), now=0),
                     dict(path=HOME + r'\Downloads\Telegram Desktop', delta=gb(6.1), now=gb(21.4)),
                     dict(path=r'C:\Projects\old-crm\node_modules', delta=-gb(4.1), now=0),
                     dict(path=HOME + r'\AppData\Local\Temp\Adobe\After Effects', delta=gb(3.2), now=gb(22.4)),
                     dict(path=HOME + r'\AppData\Roaming\Telegram Desktop\tdata\user_data', delta=gb(2.4), now=gb(9.8))])
progress = dict(samples=samples, events=events, freed_total=gb(37.6), session=dict(freed=0, recycled=0),
                prognosis=dict(ready=True, per_day=gb(4.1), days=FREE / gb(4.1), span_h=216.0), growth=growth)

dups = dict(total_groups=6, wasted=gb(14.9), groups=[
    dict(size=gb(4.6), wasted=gb(4.6), sampled=True, cat='video', files=[dict(path=HOME + r'\Videos\toy_4k_part1.mp4', mtime=NOW - 330 * DAY),
                                                                           dict(path=HOME + r'\Downloads\Toy videosi 2025\toy_4k_part1.mp4', mtime=NOW - 90 * DAY)]),
    dict(size=gb(3.4), wasted=gb(6.8), sampled=False, cat='archive', files=[dict(path=HOME + r'\Documents\python_kurs.zip', mtime=NOW - 600 * DAY),
                                                                            dict(path=HOME + r'\Downloads\Kurslar\python_kurs.zip', mtime=NOW - 520 * DAY),
                                                                            dict(path=HOME + r'\Desktop\python_kurs (1).zip', mtime=NOW - 300 * DAY)]),
    dict(size=gb(2.1), wasted=gb(2.1), sampled=False, cat='video', files=[dict(path=HOME + r'\Pictures\Telefon\VID_20250612.mp4', mtime=NOW - 480 * DAY),
                                                                          dict(path=HOME + r'\Downloads\Telegram Desktop\VID_20250612.mp4', mtime=NOW - 470 * DAY)]),
    dict(size=gb(0.9), wasted=gb(0.9), sampled=False, cat='audio', files=[dict(path=HOME + r'\Music\audiokitob.mp3', mtime=NOW - 200 * DAY),
                                                                          dict(path=HOME + r'\Downloads\Telegram Desktop\audiokitob.mp3', mtime=NOW - 140 * DAY)]),
    dict(size=gb(0.3), wasted=gb(0.5), sampled=False, cat='image', files=[dict(path=HOME + r'\Pictures\RAW\IMG_4411.CR3', mtime=NOW - 300 * DAY),
                                                                          dict(path=HOME + r'\Desktop\IMG_4411.CR3', mtime=NOW - 100 * DAY),
                                                                          dict(path=HOME + r'\Downloads\IMG_4411.CR3', mtime=NOW - 60 * DAY)])])

info = dict(admin=False, user='Aziz', home=HOME, downloads=HOME + r'\Downloads', sysdrive='C:\\', version=server.APP_VERSION,
            drives=[dict(root='C:\\', letter='C', type='fixed', label='', fs='NTFS', total=TOTAL, used=USED, free=FREE, system=True)],
            recycle=dict(size=gb(7.4), count=341), stats=dict(freed=0, recycled=0, freed_total=gb(37.6)),
            scan=dict(state='done', root='C:\\', files=1284551, dirs=241003, bytes=USED - gb(8.6), errors=412, elapsed=27.4, current='', rate=46881),
            port=4477)

out = dict(now=NOW, info=info, smart=dict(items=smart, admin=False), breakdown=breakdown, games=game_items, tree=tree, big=big,
           types=types, junk=junk, downloads=downloads, apps=dict(items=apps, total=sum(a['size'] for a in apps)), progress=progress, dups=dups)
with open(os.path.join(ROOT, 'app', 'demo.json'), 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
print('demo.json written', os.path.getsize(os.path.join(ROOT, 'app', 'demo.json')) // 1024, 'KB')
