#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Xotira — smart disk cleaner for Windows. Explains *why* the disk is full and frees space safely.

Local web app: a small stdlib-only HTTP server on 127.0.0.1 plus a single-page UI (index.html).
Nothing leaves the computer. Author: Humoyun Safarov (t.me/humoyunsafarov). License: MIT.

    pythonw launcher.pyw          # normal start: hidden server + app window
    python server.py [--open]     # developer start (console), http://127.0.0.1:4477
"""
import os, sys, json, time, glob, queue, heapq, shutil, string, hashlib, threading
import subprocess, ctypes, uuid, winreg, webbrowser, traceback, re
import stat as st_mod
from ctypes import wintypes as wt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.setrecursionlimit(20000)


def arg_val(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


PORT = int(arg_val('--port', os.environ.get('XOTIRA_PORT', 4477)))
APP_MODE = '--app' in sys.argv          # started from the desktop icon: quit by itself once the window is closed
IDLE_EXIT = int(os.environ.get('XOTIRA_IDLE', 300))
LAST_HIT = [time.time()]
K32 = ctypes.windll.kernel32
SH32 = ctypes.windll.shell32

# ---------------------------------------------------------------- paths
HOME = os.environ.get('USERPROFILE') or os.path.expanduser('~')
LOCAL = os.environ.get('LOCALAPPDATA') or os.path.join(HOME, 'AppData', 'Local')
ROAM = os.environ.get('APPDATA') or os.path.join(HOME, 'AppData', 'Roaming')
WINDIR = os.environ.get('WINDIR') or r'C:\Windows'
SYSDRIVE = (os.environ.get('SystemDrive') or 'C:') + '\\'
PDATA = os.environ.get('ProgramData') or r'C:\ProgramData'
PF = os.environ.get('ProgramFiles') or r'C:\Program Files'
PF86 = os.environ.get('ProgramFiles(x86)') or r'C:\Program Files (x86)'
TEMP = os.environ.get('TEMP') or os.path.join(LOCAL, 'Temp')
HERE = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = '1.0.0'


def long_name(p):
    """Expand 8.3 short names (C:\\Users\\JOHNDO~1) so path comparisons and dedup work."""
    buf = ctypes.create_unicode_buffer(1024)
    n = K32.GetLongPathNameW(p, buf, 1024)
    return buf.value if 0 < n < 1024 else p


HOME, LOCAL, ROAM, TEMP = (long_name(p) for p in (HOME, LOCAL, ROAM, TEMP))


def shell_folder(guid, fallback):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as k:
            return os.path.expandvars(winreg.QueryValueEx(k, guid)[0])
    except OSError:
        return fallback


DOWNLOADS = shell_folder('{374DE290-123F-4565-9164-39C4925E467B}', os.path.join(HOME, 'Downloads'))


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def under(p, base):
    p, b = norm(p), norm(base).rstrip('\\')
    return p == b or p.startswith(b + '\\')


def lp(p):
    """Long-path prefix so deep node_modules trees still work."""
    return '\\\\?\\' + p if len(p) >= 240 and not p.startswith('\\\\') else p


def is_admin():
    try:
        return bool(SH32.IsUserAnAdmin())
    except Exception:
        return False


ADMIN = is_admin()

# ---------------------------------------------------------------- file categories
CATS = {
    'video': 'mp4 mov mkv avi webm wmv flv m4v mts m2ts mxf 3gp mpg mpeg vob braw r3d',
    'image': 'jpg jpeg png gif bmp tif tiff webp heic heif raw cr2 cr3 nef arw dng psd psb exr hdr avif',
    'audio': 'mp3 wav flac aac ogg m4a wma aif aiff opus',
    'archive': 'zip rar 7z tar gz tgz bz2 xz zst iso img vhd vhdx wim esd cab dmg',
    'installer': 'exe msi msix msixbundle appx appxbundle',
    'project': 'aep aepx prproj blend blend1 c4d fbx obj glb gltf abc usd usdz drp ai indd max ma mb hip spp sbsar',
    'model': 'safetensors ckpt pt pth onnx gguf h5 tflite',
    'document': 'pdf doc docx xls xlsx ppt pptx txt rtf odt ods csv epub djvu',
    'cache': 'tmp temp log dmp etl cache bak old',
    'system': 'dll sys mui cat dat db sqlite pak',
}
EXT2CAT = {'.' + e: c for c, exts in CATS.items() for e in exts.split()}


def cat_of(name):
    return EXT2CAT.get(os.path.splitext(name)[1].lower(), 'other')


# ---------------------------------------------------------------- safety rules
_PROTECT_EXACT = {norm(p) for p in [
    SYSDRIVE, HOME, os.path.dirname(HOME), LOCAL, ROAM, os.path.join(HOME, 'AppData'), PDATA, PF, PF86, WINDIR,
    DOWNLOADS, TEMP] + [os.path.join(HOME, x) for x in
                        ('Desktop', 'Documents', 'Downloads', 'Pictures', 'Videos', 'Music', 'OneDrive', 'Favorites')]}
_PROTECT_TREE = [WINDIR, PF, PF86, HERE, os.path.join(PDATA, 'Microsoft'), os.path.join(PDATA, 'Package Cache'),
                 os.path.join(SYSDRIVE, 'System Volume Information'), os.path.join(SYSDRIVE, '$Recycle.Bin'),
                 os.path.join(SYSDRIVE, 'Recovery'), os.path.join(SYSDRIVE, 'Boot'), os.path.join(HOME, '.claude')]
_SYS_ROOT_FILES = {'pagefile.sys', 'hiberfil.sys', 'swapfile.sys', 'dumpstack.log.tmp', 'bootmgr', 'bootnxt'}


def protected(p):
    n = norm(p)
    if len(n) <= 3:
        return B("Disk ildizi — oʻchirib boʻlmaydi", "Drive root — can't be deleted")
    if n in _PROTECT_EXACT:
        return B("Muhim tizim yoki foydalanuvchi papkasi (ichidagilarni oʻchirish mumkin)",
                 "Important system or user folder (its contents can be deleted)")
    if os.path.dirname(n) == norm(SYSDRIVE) and os.path.basename(n) in _SYS_ROOT_FILES:
        return B("Windows tizim fayli — Aqlli tozalash boʻlimidan boshqariladi", "Windows system file — managed in Smart cleanup")
    for b in _PROTECT_TREE:
        if under(n, b):
            if under(n, PF) or under(n, PF86):
                return B("Dastur papkasi — “Dasturlar” boʻlimidan oʻchiring", "Program folder — uninstall it from Apps")
            return B("Himoyalangan tizim joyi", "Protected system location")
    return None


def warn_of(p):
    if any(under(p, b) for b in (LOCAL, ROAM, PDATA)):
        return B("Dastur maʼlumotlari: oʻchirilsa shu dastur sozlamalari yoʻqolishi mumkin",
                 "App data: deleting it may reset that app's settings")
    return None


_SYS_PREFIX = [norm(b).rstrip('\\') + '\\' for b in [
    WINDIR, PF, PF86, PDATA, LOCAL, ROAM, os.path.join(HOME, 'AppData'),
    os.path.join(SYSDRIVE, '$Recycle.Bin'), os.path.join(SYSDRIVE, 'System Volume Information'),
    os.path.join(SYSDRIVE, 'Recovery')]]


def is_sys_lower(pl):
    return any(pl.startswith(b) for b in _SYS_PREFIX) or os.path.dirname(pl) == norm(SYSDRIVE)


# ---------------------------------------------------------------- dev junk detection
JUNK = {'node_modules': 'node_modules', '.venv': 'Python venv', 'venv': 'Python venv', '.next': 'Next.js build',
        '.nuxt': 'Nuxt build', '.svelte-kit': 'SvelteKit build', '.parcel-cache': 'Parcel kesh',
        '.turbo': 'Turbo kesh', '.angular': 'Angular kesh', '.pytest_cache': 'pytest kesh',
        '.mypy_cache': 'mypy kesh', '.gradle': 'Gradle kesh', 'target': 'Rust build'}
_JUNK_SKIP = [LOCAL, ROAM, os.path.join(HOME, 'AppData'), WINDIR, PF, PF86, PDATA]


def junk_kind(path, parent):
    name = os.path.basename(path).lower()
    kind = JUNK.get(name)
    if not kind or any(under(path, b) for b in _JUNK_SKIP):
        return None
    for part in parent.split('\\')[1:]:
        pl = part.lower()
        if pl.startswith('.') or pl.startswith('$') or pl in JUNK:
            return None
    if name in ('venv', '.venv') and not os.path.exists(os.path.join(path, 'pyvenv.cfg')):
        return None
    if name == 'target' and not os.path.exists(os.path.join(parent, 'Cargo.toml')):
        return None
    return kind


# ---------------------------------------------------------------- scanner
BIG_MIN = 1 << 20          # files >= 1 MB are remembered individually
REPARSE_LINK_TAGS = (0xA0000003, 0xA000000C)   # junction, symlink
CLOUD_ONLY = 0x400000 | 0x40000 | 0x1000        # recall-on-access / recall-on-open / offline


class Node:
    __slots__ = ('name', 'parent', 'kids', 'size', 'nfiles', 'ndirs', 'own', 'mtime', 'err', 'junk')

    def __init__(self, name, parent, mtime=0.0):
        self.name, self.parent, self.mtime = name, parent, mtime
        self.kids = None
        self.size = self.nfiles = self.ndirs = self.own = 0
        self.err = False
        self.junk = None


def node_path(n):
    parts = []
    while n.parent is not None:
        parts.append(n.name)
        n = n.parent
    return os.path.join(n.name, *reversed(parts))


class Scan:
    def __init__(self, root):
        root = os.path.abspath(root)
        self.root_path = root
        self.root = Node(root, None)
        self.index = {norm(root): self.root}
        self.lock = threading.Lock()
        self.q = queue.Queue()
        self.files = self.dirs = self.bytes = self.errors = 0
        self.big, self.ext, self.junk = [], {}, []
        self.state, self.cancelled, self.current = 'running', False, root
        self.t0, self.t1 = time.time(), None
        self.version, self.bd, self.bd_ver = 0, None, -1

    def start(self, workers=12):
        self.q.put((self.root_path, self.root))
        self.threads = [threading.Thread(target=self._worker, daemon=True) for _ in range(workers)]
        for t in self.threads:
            t.start()
        threading.Thread(target=self._wait, daemon=True).start()

    def _wait(self):
        self.q.join()
        self.t1 = time.time()
        self.state = 'cancelled' if self.cancelled else 'done'
        for _ in self.threads:
            self.q.put(None)
        if self.state == 'done':
            threading.Thread(target=on_scan_done, args=(self,), daemon=True).start()

    def _worker(self):
        while True:
            item = self.q.get()
            if item is None:
                self.q.task_done()
                return
            try:
                if not self.cancelled:
                    self._scan_dir(*item)
            except Exception:
                pass
            finally:
                self.q.task_done()

    def _scan_dir(self, path, node):
        self.current = path
        own = nf = 0
        subs, big, ext = [], [], {}
        try:
            it = os.scandir(lp(path))
        except OSError:
            node.err = True
            with self.lock:
                self.errors += 1
                self.dirs += 1
            return
        try:
            with it:
                for e in it:
                    try:
                        s = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    a = s.st_file_attributes
                    if a & 0x10:
                        if a & 0x400 and s.st_reparse_tag in REPARSE_LINK_TAGS:
                            continue
                        subs.append((e.name, s.st_mtime))
                        continue
                    if a & 0x400 and s.st_reparse_tag == 0xA000000C:
                        continue
                    sz = 0 if a & CLOUD_ONLY else s.st_size
                    own += sz
                    nf += 1
                    x = os.path.splitext(e.name)[1].lower()
                    r = ext.get(x)
                    if r is None:
                        ext[x] = [1, sz]
                    else:
                        r[0] += 1
                        r[1] += sz
                    if sz >= BIG_MIN:
                        big.append((sz, os.path.join(path, e.name), s.st_mtime, s.st_atime))
        except OSError:
            node.err = True
        kids = []
        for name, mt in subs:
            k = Node(name, node, mt)
            kp = os.path.join(path, name)
            if name.lower() in JUNK:
                k.junk = junk_kind(kp, path)
            kids.append((kp, k))
        with self.lock:
            node.own = own
            node.kids = [k for _, k in kids] or None
            p = node
            while p is not None:
                p.size += own
                p.nfiles += nf
                p.ndirs += len(kids)
                p = p.parent
            self.files += nf
            self.bytes += own
            self.dirs += 1
            for x, (c, s) in ext.items():
                r = self.ext.get(x)
                if r is None:
                    self.ext[x] = [c, s]
                else:
                    r[0] += c
                    r[1] += s
            self.big.extend(big)
            for kp, k in kids:
                self.index[norm(kp)] = k
                if k.junk:
                    self.junk.append((kp, k))
        for kp, k in kids:
            self.q.put((kp, k))

    def status(self):
        el = (self.t1 or time.time()) - self.t0
        return dict(state=self.state, root=self.root_path, files=self.files, dirs=self.dirs, bytes=self.bytes,
                    errors=self.errors, elapsed=round(el, 1), current=self.current if self.state == 'running' else '',
                    rate=int(self.files / el) if el > 0 else 0)

    def on_deleted(self, path, size, is_dir, fully=True):
        with self.lock:
            self.version += 1
            key = norm(path)
            if is_dir:
                n = self.index.get(key)
                if n is None:
                    return
                par = n.parent
                if fully:
                    size, nfiles, ndirs = n.size, n.nfiles, n.ndirs + 1
                    if par is not None and par.kids:
                        try:
                            par.kids.remove(n)
                        except ValueError:
                            pass
                    self.index.pop(key, None)
                    pre = key.rstrip('\\') + '\\'
                    self.big = [b for b in self.big if not b[1].lower().startswith(pre)]
                    self.junk = [j for j in self.junk if j[1] is not n]
                    p = par
                else:
                    nfiles = ndirs = 0
                    p = n
            else:
                par = self.index.get(norm(os.path.dirname(path)))
                nfiles, ndirs = 1, 0
                pl = path.lower()
                self.big = [b for b in self.big if b[1].lower() != pl]
                if par is not None:
                    par.own -= size
                p = par
            while p is not None:
                p.size -= size
                p.nfiles -= nfiles
                p.ndirs -= ndirs
                p = p.parent
            self.bytes -= size
            self.files -= nfiles


SCAN = None
SCAN_LOCK = threading.Lock()


def start_scan(path):
    global SCAN
    with SCAN_LOCK:
        if SCAN and SCAN.state == 'running':
            SCAN.cancelled = True
        SCAN = Scan(path)
        SCAN.start()
    return SCAN


def node_size(path):
    sc = SCAN
    if sc:
        n = sc.index.get(norm(path))
        if n is not None and sc.state == 'done':
            return n.size
    return None


# ---------------------------------------------------------------- measure / clean helpers
def measure(paths, min_age_h=0, exclude=()):
    total = count = 0
    denied = False
    cutoff = time.time() - min_age_h * 3600 if min_age_h else None
    for top in paths:
        try:
            a = os.stat(lp(top), follow_symlinks=False)
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        if not st_mod.S_ISDIR(a.st_mode):
            if cutoff is None or a.st_mtime < cutoff:
                total += a.st_size
                count += 1
            continue
        stack = [(top, True)]
        while stack:
            d, is_top = stack.pop()
            try:
                it = os.scandir(lp(d))
            except PermissionError:
                denied = True
                continue
            except OSError:
                continue
            try:
                with it:
                    for e in it:
                        if is_top and e.name.lower() in exclude:
                            continue
                        try:
                            s = e.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        fa = s.st_file_attributes
                        if fa & 0x10:
                            if not fa & 0x400:
                                stack.append((e.path, False))
                        elif cutoff is None or s.st_mtime < cutoff:
                            total += s.st_size
                            count += 1
            except OSError:
                pass
    return total, count, denied


def _rm_file(path):
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return True
    except PermissionError:
        try:
            os.chmod(path, st_mod.S_IWRITE)
            os.remove(path)
            return True
        except OSError:
            return False
    except OSError:
        return False


def clean_contents(paths, min_age_h, exclude, job, tick=None):
    cutoff = time.time() - min_age_h * 3600 if min_age_h else None
    stt = {'freed': 0, 'files': 0, 'failed': 0}

    def gone(size, path=''):
        stt['freed'] += size
        stt['files'] += 1
        if tick:
            tick(stt, path)

    def walk(d, is_top):
        try:
            with os.scandir(lp(d)) as it:
                entries = list(it)
        except OSError:
            stt['failed'] += 1
            return
        for e in entries:
            if job.cancel:
                return
            if is_top and e.name.lower() in exclude:
                continue
            try:
                s = e.stat(follow_symlinks=False)
            except OSError:
                continue
            fa = s.st_file_attributes
            if fa & 0x10:
                if fa & 0x400:
                    continue
                walk(e.path, False)
                try:
                    os.rmdir(e.path)
                except OSError:
                    pass
            elif cutoff is None or s.st_mtime < cutoff:
                if _rm_file(e.path):
                    gone(s.st_size, e.path)
                else:
                    stt['failed'] += 1

    for p in paths:
        if os.path.isdir(p):
            walk(p, True)
        elif os.path.isfile(p):
            try:
                sz = os.stat(p).st_size
            except OSError:
                sz = 0
            if _rm_file(p):
                gone(sz, p)
            else:
                stt['failed'] += 1
    return stt


# ---------------------------------------------------------------- Windows shell helpers
class SHQUERYRBINFO(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('i64Size', ctypes.c_longlong), ('i64NumItems', ctypes.c_longlong)]


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [('hwnd', wt.HWND), ('wFunc', wt.UINT), ('pFrom', ctypes.c_wchar_p), ('pTo', ctypes.c_wchar_p),
                ('fFlags', ctypes.c_ushort), ('fAnyOperationsAborted', wt.BOOL),
                ('hNameMappings', ctypes.c_void_p), ('lpszProgressTitle', ctypes.c_wchar_p)]


def recycle_info():
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    try:
        if SH32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
            return info.i64Size, info.i64NumItems
    except Exception:
        pass
    return None, None


def empty_recycle():
    return SH32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)


def send_to_recycle(paths):
    buf = ctypes.create_unicode_buffer('\0'.join(paths) + '\0')
    op = SHFILEOPSTRUCTW()
    op.wFunc = 3  # FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_wchar_p)
    # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI | WANTNUKEWARNING (asks before anything is destroyed for real)
    op.fFlags = 0x40 | 0x10 | 0x4 | 0x400 | 0x4000
    return SH32.SHFileOperationW(ctypes.byref(op))


def drives():
    out = []
    mask = K32.GetLogicalDrives()
    for i, l in enumerate(string.ascii_uppercase):
        if not (mask >> i) & 1:
            continue
        root = l + ':\\'
        t = K32.GetDriveTypeW(root)
        if t not in (2, 3, 4, 6):
            continue
        try:
            total, used, free = shutil.disk_usage(root)
        except OSError:
            continue
        name = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        K32.GetVolumeInformationW(root, name, 261, None, None, None, fs, 261)
        out.append(dict(root=root, letter=l, type={2: 'removable', 3: 'fixed', 4: 'network', 6: 'ram'}[t],
                        label=name.value, fs=fs.value, total=total, used=used, free=free,
                        system=norm(root) == norm(SYSDRIVE)))
    return out


def sys_free():
    try:
        return shutil.disk_usage(SYSDRIVE).free
    except OSError:
        return 0


def root_file_size(name):
    try:
        with os.scandir(SYSDRIVE) as it:
            for e in it:
                if e.name.lower() == name:
                    return e.stat(follow_symlinks=False).st_size
    except OSError:
        pass
    return 0


# ---------------------------------------------------------------- smart cleanup targets
E = glob.escape
J = os.path.join


def chromium(base):
    b = E(base)
    pats = []
    for sub in ('Cache', 'Code Cache', 'GPUCache', 'DawnCache', 'DawnGraphiteCache', 'DawnWebGPUCache',
                J('Service Worker', 'CacheStorage'), J('Service Worker', 'ScriptCache')):
        pats.append(J(b, '*', sub))
    for sub in ('ShaderCache', 'GrShaderCache', 'GraphiteDawnCache'):
        pats.append(J(b, sub))
    return pats


def electron(base):
    b = E(base)
    return [J(b, s) for s in ('Cache', 'Code Cache', 'GPUCache', 'DawnCache', 'DawnGraphiteCache',
                              J('Service Worker', 'CacheStorage'), J('Service Worker', 'ScriptCache'))]


def B(uz, en):
    """A user-facing string in both UI languages; the page shows the one the user picked."""
    return {'uz': uz, 'en': en}


def T(id, group, title, desc, pats, risk='safe', admin=False, age=0, note=None, exclude=()):
    return dict(id=id, group=group, title=title, desc=desc, pats=pats, risk=risk, admin=admin, age=age,
                note=note, exclude=tuple(x.lower() for x in exclude), kind='clean')


BROWSER_DESC = B("Sayt keshlari. Login, parol va tarix oʻchmaydi.", "Website caches. Logins, passwords and history stay.")


def build_targets():
    L, R, H, W = E(LOCAL), E(ROAM), E(HOME), E(WINDIR)
    t = [
        # ---- Windows
        T('user-temp', 'system', B("Vaqtinchalik fayllar (Temp)", "Temporary files (Temp)"),
          B("Dasturlar qoldirgan vaqtinchalik fayllar. Faqat 24 soatdan eskilari oʻchiriladi.",
            "Leftovers from programs. Only files older than 24 hours are removed."),
          [E(TEMP)], age=24, exclude=['claude', 'adobe']),
        T('win-temp', 'system', B("Windows Temp", "Windows Temp"),
          B("Tizim darajasidagi vaqtinchalik fayllar.", "System-level temporary files."), [J(W, 'Temp')], admin=True, age=24),
        T('wu-cache', 'system', B("Windows Update keshi", "Windows Update cache"),
          B("Oʻrnatib boʻlingan yangilanishlarning yuklab olingan paketlari.", "Downloaded packages of updates that are already installed."),
          [J(W, 'SoftwareDistribution', 'Download')], admin=True),
        T('delivery', 'system', B("Delivery Optimization keshi", "Delivery Optimization cache"),
          B("Yangilanishlarni boshqa kompyuterlarga tarqatish uchun saqlangan nusxalar.", "Copies kept to share updates with other PCs."),
          [J(W, 'ServiceProfiles', 'NetworkService', 'AppData', 'Local', 'Microsoft', 'Windows', 'DeliveryOptimization', 'Cache')],
          admin=True),
        T('crash-user', 'system', B("Ilovalar crash-dump fayllari", "App crash dumps"),
          B("Dasturlar qulaganda yozilgan xotira nusxalari va xato hisobotlari.", "Memory dumps and error reports written when programs crashed."),
          [J(L, 'CrashDumps'), J(L, 'Microsoft', 'Windows', 'WER')]),
        T('crash-sys', 'system', B("Tizim xato hisobotlari", "System error reports"),
          B("Windows minidump, MEMORY.DMP va WER arxivlari.", "Windows minidumps, MEMORY.DMP and WER archives."),
          [J(W, 'Minidump'), J(W, 'MEMORY.DMP'), J(E(PDATA), 'Microsoft', 'Windows', 'WER', 'ReportArchive'),
           J(E(PDATA), 'Microsoft', 'Windows', 'WER', 'ReportQueue')], admin=True),
        T('win-logs', 'system', B("Windows CBS jurnallari", "Windows CBS logs"),
          B("Eski tizim xizmat jurnallari arxivlari.", "Old Windows servicing log archives."),
          [J(W, 'Logs', 'CBS', 'CbsPersist_*')], admin=True),
        T('inetcache', 'system', B("Windows internet keshi", "Windows internet cache"),
          B("Eski IE/WebView va tizim komponentlari keshi.", "Old IE/WebView and system component cache."),
          [J(L, 'Microsoft', 'Windows', 'INetCache'), J(L, 'Packages', '*', 'AC', 'INetCache'), J(L, 'Packages', '*', 'AC', 'Temp')]),
        T('thumbs', 'system', B("Rasm eskizlari (thumbnail) keshi", "Thumbnail cache"),
          B("Explorer avtomatik qayta yaratadi. Band boʻlganlari oʻtkazib yuboriladi.", "Explorer rebuilds it automatically. Files in use are skipped."),
          [J(L, 'Microsoft', 'Windows', 'Explorer', 'thumbcache_*.db'), J(L, 'Microsoft', 'Windows', 'Explorer', 'iconcache_*.db')]),
        T('shader', 'system', B("GPU shader keshi", "GPU shader cache"),
          B("NVIDIA / DirectX / AMD shader keshlari — oʻyinlar qayta yaratadi.", "NVIDIA / DirectX / AMD shader caches — games rebuild them."),
          [J(L, 'D3DSCache'), J(L, 'NVIDIA', 'DXCache'), J(L, 'NVIDIA', 'GLCache'), J(L, 'NVIDIA Corporation', 'NV_Cache'),
           J(L, 'AMD', 'DxCache'), J(L, 'AMD', 'GLCache'), J(L, 'AMD', 'DxcCache'), J(L, 'Intel', 'ShaderCache')]),
        T('nvidia-dl', 'system', B("NVIDIA drayver oʻrnatuvchilari", "NVIDIA driver installers"),
          B("Avval yuklab olingan drayver paketlari (oʻrnatilgan drayverga taʼsir qilmaydi).",
            "Previously downloaded driver packages (the installed driver is not affected)."),
          [J(E(PDATA), 'NVIDIA Corporation', 'Downloader'), J(E(SYSDRIVE), 'NVIDIA')], admin=True),
        # ---- browsers
        T('chrome', 'browser', B("Google Chrome keshi", "Google Chrome cache"), BROWSER_DESC,
          chromium(J(LOCAL, 'Google', 'Chrome', 'User Data')),
          note=B("Chrome ochiq boʻlsa band fayllar qoladi", "Files in use stay while Chrome is open")),
        T('edge', 'browser', B("Microsoft Edge keshi", "Microsoft Edge cache"), BROWSER_DESC,
          chromium(J(LOCAL, 'Microsoft', 'Edge', 'User Data'))),
        T('brave', 'browser', B("Brave keshi", "Brave cache"), BROWSER_DESC,
          chromium(J(LOCAL, 'BraveSoftware', 'Brave-Browser', 'User Data'))),
        T('yandex', 'browser', B("Yandex Browser keshi", "Yandex Browser cache"), BROWSER_DESC,
          chromium(J(LOCAL, 'Yandex', 'YandexBrowser', 'User Data'))),
        T('opera', 'browser', B("Opera keshi", "Opera cache"), BROWSER_DESC,
          [J(L, 'Opera Software', '*', 'Cache'), J(L, 'Opera Software', '*', 'Default', 'Cache')]
          + electron(J(ROAM, 'Opera Software', 'Opera Stable')) + electron(J(ROAM, 'Opera Software', 'Opera Stable', 'Default'))
          + electron(J(ROAM, 'Opera Software', 'Opera GX Stable'))),
        T('firefox', 'browser', B("Firefox keshi", "Firefox cache"), BROWSER_DESC,
          [J(L, 'Mozilla', 'Firefox', 'Profiles', '*', s) for s in ('cache2', 'startupCache', 'thumbnails')]),
        # ---- apps
        T('telegram', 'apps', B("Telegram keshi", "Telegram cache"),
          B("Koʻrilgan rasm, video va stiker keshi. Chatlar va akkaunt oʻchmaydi.",
            "Cached photos, videos and stickers you've viewed. Chats and account stay."),
          [J(R, 'Telegram Desktop', 'tdata', 'user_data*'),
           J(L, 'Packages', 'TelegramMessengerLLP*', 'LocalCache', 'Roaming', 'Telegram Desktop UWP', 'tdata', 'user_data*')],
          risk='care', note=B("Avval Telegramni yoping", "Close Telegram first")),
        T('discord', 'apps', B("Discord keshi", "Discord cache"), B("Rasm va media keshi.", "Image and media cache."),
          electron(J(ROAM, 'discord'))),
        T('editors', 'apps', B("VS Code / Cursor / Antigravity keshi", "VS Code / Cursor / Antigravity cache"),
          B("Muharrir keshlari, eski kengaytma paketlari va loglar.", "Editor caches, old extension packages and logs."),
          [p for app in ('Code', 'Cursor', 'Antigravity', 'Windsurf') for p in
           electron(J(ROAM, app)) + [J(R, app, 'CachedData'), J(R, app, 'CachedExtensionVSIXs'), J(R, app, 'logs')]]),
        T('capcut', 'apps', B("CapCut keshi", "CapCut cache"),
          B("Effekt, shablon va preview keshi. Loyihalar oʻchmaydi.", "Effect, template and preview cache. Projects stay."),
          [J(L, 'CapCut', 'User Data', 'Cache')], note=B("CapCut yopiq boʻlsin", "Close CapCut first")),
        T('steam', 'apps', B("Steam keshi", "Steam cache"), B("Doʻkon sahifalari va shader keshi.", "Store pages and shader cache."),
          [J(L, 'Steam', 'htmlcache'), J(E(PF86), 'Steam', 'appcache', 'httpcache'),
           J(E(PF86), 'Steam', 'steamapps', 'shadercache'), J(E(PF86), 'Steam', 'logs'), J(E(PF86), 'Steam', 'dumps')]),
        T('spotify', 'apps', B("Spotify keshi", "Spotify cache"),
          B("Oflayn saqlanmagan qoʻshiqlar keshi.", "Cache of songs that aren't saved for offline."),
          [J(L, 'Spotify', 'Storage'), J(L, 'Packages', 'SpotifyAB*', 'LocalCache', 'Spotify', 'Data')]),
        # ---- video / design
        T('ae-disk', 'media', B("After Effects disk keshi", "After Effects disk cache"),
          B("Preview render keshi (barcha AE versiyalari). AE kerak boʻlganda qayta yaratadi — loyihalar oʻchmaydi.",
            "Preview render cache (all AE versions). AE rebuilds it when needed — projects stay."),
          [J(E(TEMP), 'Adobe', 'After Effects', '*', 'Disk Cache*'), J(R, 'Adobe', 'Common', 'Disk Cache*')],
          note=B("After Effects yopiq boʻlsin. Maslahat: AE > Preferences > Media & Disk Cache'da limitni 20–30 GB qiling",
                 "Close After Effects first. Tip: set the limit to 20–30 GB in AE > Preferences > Media & Disk Cache")),
        T('adobe-temp', 'media', B("Adobe vaqtinchalik fayllari", "Adobe temporary files"),
          B("Premiere / Photoshop / Acrobat vaqtinchalik fayllari.", "Premiere / Photoshop / Acrobat temp files."),
          [J(E(TEMP), 'Adobe', s) for s in ('Premiere Pro', 'Acrobat', 'GPUSniffer', 'GrowthSDK', 'UXP', 'com.adobe.dunamis')]
          + [J(E(TEMP), 'Adobe', '*.log')]),
        T('adobe', 'media', B("Adobe Media Cache (Premiere / AE)", "Adobe Media Cache (Premiere / AE)"),
          B("Audio peak, konform va media kesh fayllari — loyiha ochilganda qayta yaratiladi.",
            "Audio peak, conformed and media cache files — rebuilt when a project opens."),
          [J(R, 'Adobe', 'Common', s) for s in ('Media Cache Files', 'Media Cache', 'Peak Files', 'Analyzer Cache Files')],
          note=B("Premiere va After Effects yopiq boʻlsin", "Close Premiere and After Effects first")),
        T('cameraraw', 'media', B("Camera Raw / Lightroom keshi", "Camera Raw / Lightroom cache"),
          B("RAW preview keshi.", "RAW preview cache."), [J(L, 'Adobe', 'CameraRaw', 'Cache'), J(L, 'Adobe', 'CameraRaw', 'GPU')]),
        # ---- developer caches
        T('npm', 'dev', B("npm keshi", "npm cache"),
          B("Yuklangan paketlar keshi. Keyingi npm install biroz sekinroq boʻladi.", "Downloaded package cache. The next npm install is a bit slower."),
          [J(L, 'npm-cache', '_cacache'), J(L, 'npm-cache', '_npx')]),
        T('pip', 'dev', B("pip keshi", "pip cache"), B("Python paket keshi.", "Python package cache."), [J(L, 'pip', 'Cache'), J(L, 'pip', 'cache')]),
        T('uv', 'dev', B("uv keshi", "uv cache"), B("uv Python paket keshi.", "uv Python package cache."), [J(L, 'uv', 'cache')]),
        T('yarn', 'dev', B("Yarn keshi", "Yarn cache"), B("Yarn paket keshi.", "Yarn package cache."), [J(L, 'Yarn', 'Cache')]),
        T('gocache', 'dev', B("Go build keshi", "Go build cache"), B("Go kompilyatsiya keshi.", "Go compilation cache."), [J(L, 'go-build')]),
        T('electron-dl', 'dev', B("Electron yuklamalari keshi", "Electron downloads cache"),
          B("electron-builder yuklagan binarlar.", "Binaries downloaded by electron-builder."),
          [J(L, 'electron', 'Cache'), J(L, 'electron-builder', 'Cache')]),
        T('playwright', 'dev', B("Playwright brauzerlari", "Playwright browsers"),
          B("Avtomatlashtirish uchun headless Chromium/Firefox. Oʻchirilsa `npx playwright install` qayta yuklaydi.",
            "Headless Chromium/Firefox for automation. `npx playwright install` downloads them again."),
          [J(L, 'ms-playwright')], risk='care'),
        T('puppeteer', 'dev', B("Puppeteer brauzerlari", "Puppeteer browsers"),
          B("Kerak boʻlganda qayta yuklab olinadi.", "Downloaded again when needed."), [J(H, '.cache', 'puppeteer')], risk='care'),
        T('hf', 'dev', B("HuggingFace / Whisper / Torch modellar", "HuggingFace / Whisper / Torch models"),
          B("AI modellar keshi — kerak boʻlganda qayta yuklanadi (katta hajm, sekin internetda ehtiyot boʻling).",
            "AI model cache — re-downloaded when needed (large; be careful on slow internet)."),
          [J(H, '.cache', 'huggingface'), J(H, '.cache', 'whisper'), J(H, '.cache', 'torch')], risk='care'),
        T('pnpm', 'dev', B("pnpm store", "pnpm store"), B("pnpm umumiy paket ombori.", "pnpm's shared package store."),
          [J(L, 'pnpm', 'store'), J(L, 'pnpm-store')], risk='care'),
        T('nuget', 'dev', B("NuGet paketlari", "NuGet packages"), B(".NET paket keshi.", ".NET package cache."),
          [J(H, '.nuget', 'packages')], risk='care'),
        T('gradle', 'dev', B("Gradle keshi", "Gradle cache"), B("Gradle yuklamalari.", "Gradle downloads."),
          [J(H, '.gradle', 'caches')], risk='care'),
    ]

    def sp(id, title, desc, risk='safe', admin=False, note=None):
        return dict(id=id, group='tools', title=title, desc=desc, pats=[], kind=id, risk=risk, admin=admin,
                    note=note, age=0, exclude=())

    t += [
        sp('recycle', B("Savat (Recycle Bin)", "Recycle Bin"),
           B("Oʻchirilgan fayllar hali ham joy egallaydi. Boʻshatilgach qaytarib boʻlmaydi.",
             "Deleted files still take space. Emptying it can't be undone."), risk='care'),
        sp('hiber', B("Hibernatsiya fayli (hiberfil.sys)", "Hibernation file (hiberfil.sys)"),
           B("Uyqu (Hibernate) va Fast Startup uchun RAM hajmidagi fayl. Oʻchirilsa bu funksiyalar oʻchadi.",
             "RAM-sized file for Hibernate and Fast Startup. Turning it off disables both."),
           risk='care', admin=True, note=B("Qayta yoqish: powercfg /h on", "Turn back on: powercfg /h on")),
        sp('dism', B("WinSxS komponentlarini tozalash", "Clean up WinSxS components"),
           B("DISM eski Windows komponent versiyalarini olib tashlaydi. 5–20 daqiqa ketishi mumkin.",
             "DISM removes old versions of Windows components. May take 5–20 minutes."), admin=True),
        sp('winold', B("Eski Windows (Windows.old)", "Previous Windows (Windows.old)"),
           B("Oldingi Windows oʻrnatmasi. Windows Disk Cleanup orqali olib tashlanadi.",
             "The previous Windows installation. Removed via Windows Disk Cleanup."), admin=True),
        sp('restore', B("Tizim tiklash nuqtalari", "System Restore points"),
           B("System Restore nusxalari yashirin joy egallaydi. Sozlamalarda limitni kamaytiring yoki eskilarini oʻchiring.",
             "Restore points take hidden space. Lower the limit or delete old ones in settings.")),
        sp('cleanmgr', B("Windows Disk Cleanup", "Windows Disk Cleanup"),
           B("Windowsʼning oʻz tozalash vositasini ochish.", "Open Windows' own cleanup tool.")),
        sp('storagesense', B("Storage Sense sozlamalari", "Storage Sense settings"),
           B("Avtomatik tozalashni yoqish (Windows sozlamalari).", "Turn on automatic cleanup (Windows Settings).")),
    ]
    return t


TARGETS = build_targets()
TMAP = {t['id']: t for t in TARGETS}
SMART = {}
SMART_LOCK = threading.Lock()


def expand(t):
    seen, out = set(), []
    for pat in t['pats']:
        for p in glob.glob(pat):
            k = norm(p)
            if k not in seen:
                seen.add(k)
                out.append(p)
    return out


def measure_target(t):
    k = t['kind']
    r = dict(id=t['id'], state='done', size=0, count=0, denied=False, exists=True, paths=[])
    try:
        if k == 'clean':
            paths = expand(t)
            r['paths'] = paths
            r['exists'] = bool(paths)
            if paths:
                r['size'], r['count'], r['denied'] = measure(paths, t['age'], t['exclude'])
        elif k == 'recycle':
            r['size'], r['count'] = recycle_info()
        elif k == 'hiber':
            r['size'] = root_file_size('hiberfil.sys')
            r['exists'] = r['size'] > 0
        elif k == 'winold':
            paths = [p for p in (J(SYSDRIVE, 'Windows.old'), J(SYSDRIVE, '$Windows.~BT'), J(SYSDRIVE, '$Windows.~WS'))
                     if os.path.exists(p)]
            r['paths'] = paths
            r['exists'] = bool(paths)
            if paths:
                r['size'], r['count'], r['denied'] = measure(paths)
        else:
            r['size'] = None
    except Exception as e:
        r['state'] = 'error'
        r['error'] = str(e)
    with SMART_LOCK:
        SMART[t['id']] = r
    return r


def measure_all():
    with SMART_LOCK:
        for t in TARGETS:
            SMART[t['id']] = dict(id=t['id'], state='measuring')
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(measure_target, TARGETS))


def smart_payload():
    items = []
    with SMART_LOCK:
        for t in TARGETS:
            r = SMART.get(t['id'], {'state': 'measuring'})
            d = {k: t[k] for k in ('id', 'group', 'title', 'desc', 'risk', 'admin', 'note', 'kind', 'age')}
            d.update({k: v for k, v in r.items() if k != 'paths'})
            d['paths'] = (r.get('paths') or [])[:4]
            d['npaths'] = len(r.get('paths') or [])
            items.append(d)
    return dict(items=items, admin=ADMIN)


# ---------------------------------------------------------------- jobs
JOBS = {}
STATS = {'freed': 0, 'recycled': 0}
STATS_LOCK = threading.Lock()


def add_stat(k, v):
    with STATS_LOCK:
        STATS[k] += max(0, int(v or 0))


class Job:
    def __init__(self, kind, title=''):
        self.id = uuid.uuid4().hex[:10]
        self.kind, self.title = kind, title
        self.state, self.progress, self.msg, self.result = 'running', None, '', None
        self.live = {}
        self.cancel = False
        self.t0, self.t1 = time.time(), None

    def d(self):
        return dict(id=self.id, kind=self.kind, title=self.title, state=self.state, progress=self.progress,
                    msg=self.msg, result=self.result, live=self.live,
                    elapsed=round((self.t1 or time.time()) - self.t0, 1))


def start_job(kind, title, fn, *args):
    j = Job(kind, title)
    JOBS[j.id] = j

    def run():
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 2)
        except Exception:
            pass
        try:
            j.result = fn(j, *args)
            j.state = 'done'
            j.progress = 1
        except Exception as e:
            traceback.print_exc()
            j.state, j.msg = 'error', (e.args[0] if e.args and isinstance(e.args[0], dict) else str(e))
        j.t1 = time.time()

    threading.Thread(target=run, daemon=True).start()
    return j


def rescan_after(freed):
    """A big cleanup makes the tree stale — rescan so the map, diagnosis and growth history stay true."""
    sc = SCAN
    if freed >= (2 << 30) and sc and sc.state == 'done' and is_drive_root(sc.root_path):
        threading.Timer(1.0, lambda: start_scan(sc.root_path)).start()


OPENERS = {'cleanmgr', 'winold', 'storagesense', 'restore'}


def job_clean(job, ids):
    freed = failed = 0
    done = []
    free_before = sys_free()
    plan = [TMAP[i] for i in ids if i in TMAP]
    expect = {t['id']: (SMART.get(t['id']) or {}).get('size') or 0 for t in plan}
    total_expect = sum(expect.values()) or 1
    job.live = dict(freed=0, current='', items=[dict(id=t['id'], title=t['title'], size=expect[t['id']], freed=0,
                                                    state='wait') for t in plan])
    for n, t in enumerate(plan):
        tid, k = t['id'], t['kind']
        item = job.live['items'][n]
        item['state'] = 'run'
        job.msg = t['title']
        if t['admin'] and not ADMIN:
            item['state'] = 'skip'
            done.append(dict(id=tid, freed=0, failed=0, skipped=B("Admin ruxsati kerak", "Needs admin rights")))
            continue
        before = sys_free()
        rec = dict(id=tid, freed=0, failed=0)
        base = freed

        def tick(stt, path, item=item, base=base):
            item['freed'] = stt['freed']
            job.live['freed'] = base + stt['freed']
            job.live['current'] = path
            job.progress = min(0.99, job.live['freed'] / total_expect)

        if k == 'clean':
            s = clean_contents(expand(t), t['age'], t['exclude'], job, tick)
            rec.update(freed=s['freed'], failed=s['failed'])
        elif k == 'recycle':
            sz, _ = recycle_info()
            empty_recycle()
            after, _ = recycle_info()
            rec['freed'] = max(0, (sz or 0) - (after or 0))
        elif k == 'hiber':
            subprocess.run(['powercfg', '/h', 'off'], capture_output=True, creationflags=0x08000000)
            time.sleep(1.0)
            rec['freed'] = max(0, sys_free() - before)
        elif k == 'dism':
            job.msg = B("DISM ishlamoqda — bir necha daqiqa…", "DISM is running — this takes a few minutes…")
            p = subprocess.run(['Dism.exe', '/Online', '/Cleanup-Image', '/StartComponentCleanup'],
                               capture_output=True, text=True, errors='ignore', creationflags=0x08000000)
            rec['freed'] = max(0, sys_free() - before)
            if p.returncode != 0:
                rec['error'] = (p.stdout or p.stderr or '').strip()[-300:]
        elif k in ('cleanmgr', 'winold'):
            subprocess.Popen(['cleanmgr.exe', '/d', SYSDRIVE[:2]])
            rec['opened'] = True
        elif k == 'storagesense':
            os.startfile('ms-settings:storagesense')
            rec['opened'] = True
        elif k == 'restore':
            subprocess.Popen(['SystemPropertiesProtection.exe'])
            rec['opened'] = True
        item['freed'] = rec['freed']
        item['state'] = 'error' if rec.get('error') else 'done'
        freed += rec['freed']
        failed += rec['failed']
        job.live['freed'] = freed
        done.append(rec)
        job.progress = min(0.99, max((n + 1) / max(1, len(plan)), freed / total_expect))
        measure_target(t)
    job.live['current'] = ''
    add_stat('freed', freed)
    titles = [t['title'] for t in plan if t['kind'] not in OPENERS]
    if freed > 0:
        add_event('clean', titles[0] if len(titles) == 1 else B(f"Aqlli tozalash · {len(titles)} ta joy",
                                                                   f"Smart cleanup · {len(titles)} places"), freed,
                  {'items': [dict(title=TMAP[r['id']]['title'], bytes=r['freed']) for r in done if r['freed']][:12]})
    rescan_after(freed)
    return dict(freed=freed, failed=failed, items=done, free_before=free_before, free_after=sys_free())


def size_of(path):
    try:
        s = os.stat(lp(path), follow_symlinks=False)
    except OSError:
        return 0, False
    if st_mod.S_ISDIR(s.st_mode):
        ns = node_size(path)
        return (ns if ns is not None else measure([path])[0]), True
    return s.st_size, False


def job_delete(job, paths, mode):
    ok, fail, items = [], [], []
    free_before = sys_free()
    job.live = dict(total=len(paths), done=0, bytes=0, current='')
    for p in paths:
        p = os.path.normpath(p)
        why = protected(p)
        if why:
            fail.append(dict(path=p, error=why))
        elif not os.path.lexists(lp(p)):
            fail.append(dict(path=p, error=B("Topilmadi", "Not found")))
        else:
            sz, isdir = size_of(p)
            items.append((p, sz, isdir))
    job.live['total'] = len(items)
    total = 0
    if mode == 'recycle':
        normal = [i for i in items if len(i[0]) < 259]
        for i in items:
            if len(i[0]) >= 259:
                fail.append(dict(path=i[0], error=B("Yoʻl juda uzun — “Butunlay oʻchirish”dan foydalaning",
                                                    "Path too long — use “Delete permanently”")))
        for c in range(0, len(normal), 25):
            chunk = normal[c:c + 25]
            job.msg = f"{c + len(chunk)}/{len(normal)}"
            job.live['current'] = chunk[0][0]
            send_to_recycle([i[0] for i in chunk])
            for p, sz, isdir in chunk:
                if os.path.lexists(p):
                    fail.append(dict(path=p, error=B("Savatga oʻtkazilmadi (band yoki ruxsat yoʻq)", "Not moved (in use or no access)")))
                else:
                    ok.append(dict(path=p, size=sz))
                    total += sz
                    if SCAN:
                        SCAN.on_deleted(p, sz, isdir)
                job.live['done'] += 1
            job.live['bytes'] = total
            job.progress = (c + len(chunk)) / max(1, len(normal))
        add_stat('recycled', total)
        if total:
            add_event('recycle-move', B(f"Savatga tashlandi · {len(ok)} ta", f"Moved to Recycle Bin · {len(ok)}"), total)
    else:
        for n, (p, sz, isdir) in enumerate(items):
            job.msg = os.path.basename(p)
            job.live['current'] = p
            if isdir:
                def onexc(func, path, exc):
                    try:
                        os.chmod(path, st_mod.S_IWRITE)
                        func(path)
                    except OSError:
                        pass
                shutil.rmtree(lp(p), onexc=onexc)
                if os.path.exists(lp(p)):
                    left = measure([p])[0]
                    gone = max(0, sz - left)
                    fail.append(dict(path=p, error=B("Qisman oʻchirildi (baʼzi fayllar band)", "Partly deleted (some files in use)"), freed=gone))
                    total += gone
                    if SCAN:
                        SCAN.on_deleted(p, gone, True, fully=False)
                    job.live.update(done=n + 1, bytes=total)
                    continue
            elif not _rm_file(lp(p)):
                fail.append(dict(path=p, error=B("Oʻchirilmadi (band yoki ruxsat yoʻq)", "Not deleted (in use or no access)")))
                job.live['done'] = n + 1
                continue
            ok.append(dict(path=p, size=sz))
            total += sz
            if SCAN:
                SCAN.on_deleted(p, sz, isdir)
            job.live.update(done=n + 1, bytes=total)
            job.progress = (n + 1) / max(1, len(items))
        add_stat('freed', total)
        if total:
            add_event('delete', os.path.basename(ok[0]['path']) if len(ok) == 1 else B(f"{len(ok)} ta fayl/papka oʻchirildi",
                                                                                         f"{len(ok)} files/folders deleted"),
                      total)
        rescan_after(total)
    job.live['current'] = ''
    return dict(ok=ok, fail=fail, bytes=total, mode=mode, free_before=free_before, free_after=sys_free())


# ---------------------------------------------------------------- history: free-space samples, events, scan snapshots
DATA_ROOT = os.path.join(LOCAL, 'Xotira')
DATA_DIR = os.path.join(DATA_ROOT, 'data')
HIST_PATH = os.path.join(DATA_DIR, 'history.json')
SCANS_PATH = os.path.join(DATA_DIR, 'scans.json')
HIST_LOCK = threading.Lock()


def _read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


HIST = _read_json(HIST_PATH, {})
for _k, _v in (('samples', []), ('events', []), ('freed_total', 0)):
    HIST.setdefault(_k, _v)


def save_hist():
    with HIST_LOCK:
        snap = json.loads(json.dumps(HIST))
    try:
        _write_json(HIST_PATH, snap)
    except OSError:
        traceback.print_exc()


def sample_free(force=False):
    try:
        u = shutil.disk_usage(SYSDRIVE)
    except OSError:
        return
    now = time.time()
    with HIST_LOCK:
        s = HIST['samples']
        if not force and s and abs(s[-1][1] - u.free) < (64 << 20) and now - s[-1][0] < 1800:
            return
        s.append([round(now), u.free, u.used, u.total])
        if len(s) > 4000:
            del s[:len(s) - 4000]
    save_hist()


def add_event(kind, title, nbytes, extra=None):
    ev = dict(ts=round(time.time()), kind=kind, title=title, bytes=int(nbytes or 0))
    if extra:
        ev.update(extra)
    with HIST_LOCK:
        HIST['events'].append(ev)
        HIST['events'] = HIST['events'][-400:]
        if kind in ('clean', 'delete') and nbytes:
            HIST['freed_total'] += int(nbytes)
    sample_free(force=True)


def sampler():
    while True:
        try:
            sample_free()
        except Exception:
            traceback.print_exc()
        time.sleep(300)


def prognosis():
    with HIST_LOCK:
        s = list(HIST['samples'])
    now = time.time()
    s = [x for x in s if now - x[0] <= 14 * 86400]
    span = s[-1][0] - s[0][0] if len(s) > 1 else 0
    if len(s) < 3 or span < 12 * 3600:
        return dict(ready=False, span_h=round(span / 3600, 1))
    grow = sum(max(0, b[2] - a[2]) for a, b in zip(s, s[1:]))   # consumption only; cleanups don't count
    per_day = grow / span * 86400
    free = s[-1][1]
    return dict(ready=True, per_day=per_day, days=(free / per_day) if per_day > (16 << 20) else None,
                span_h=round(span / 3600, 1))


def _qhash(path, size):
    h = hashlib.blake2b(digest_size=16)
    with open(lp(path), 'rb') as f:
        h.update(f.read(65536))
        if size > 131072:
            f.seek(size - 65536)
            h.update(f.read(65536))
    return h.hexdigest()


def _fhash(path, size):
    h = hashlib.blake2b(digest_size=20)
    with open(lp(path), 'rb') as f:
        if size <= 96 << 20:
            while True:
                b = f.read(1 << 20)
                if not b:
                    break
                h.update(b)
        else:
            step = size // 24
            for i in range(24):
                f.seek(i * step)
                h.update(f.read(262144))
            f.seek(size - 262144)
            h.update(f.read(262144))
    return h.hexdigest()


def _dup_candidate(pl):
    if is_sys_lower(pl):
        return False
    for part in pl.split('\\')[1:-1]:
        if part.startswith('.') or part.startswith('$') or part in JUNK:
            return False
    return True


def job_dups(job):
    sc = SCAN
    if not sc:
        raise RuntimeError(B("Avval diskni skanerlang", "Scan the disk first"))
    with sc.lock:
        data = list(sc.big)
    by_size = {}
    for b in data:
        if _dup_candidate(b[1].lower()):
            by_size.setdefault(b[0], []).append(b)
    groups = [g for g in by_size.values() if len(g) > 1]
    total = sum(len(g) for g in groups) or 1
    done = 0
    stage2 = []
    job.msg = B("Tez solishtirish…", "Quick compare…")
    for g in groups:
        if job.cancel:
            break
        hs = {}
        for b in g:
            try:
                hs.setdefault(_qhash(b[1], b[0]), []).append(b)
            except OSError:
                pass
            done += 1
            job.progress = 0.4 * done / total
        stage2 += [x for x in hs.values() if len(x) > 1]
    out = []
    total2 = sum(len(g) for g in stage2) or 1
    done = 0
    job.msg = B("Tarkibni tekshirish…", "Checking contents…")
    for g in stage2:
        if job.cancel:
            break
        hs = {}
        for b in g:
            try:
                hs.setdefault(_fhash(b[1], b[0]), []).append(b)
            except OSError:
                pass
            done += 1
            job.progress = 0.4 + 0.6 * done / total2
        for files in hs.values():
            if len(files) > 1:
                size = files[0][0]
                out.append(dict(size=size, wasted=size * (len(files) - 1), sampled=size > 96 << 20,
                                cat=cat_of(files[0][1]),
                                files=[dict(path=f[1], mtime=f[2], prot=protected(f[1])) for f in
                                       sorted(files, key=lambda f: f[2])]))
    out.sort(key=lambda g: -g['wasted'])
    return dict(groups=out[:400], total_groups=len(out), wasted=sum(g['wasted'] for g in out))


# ---------------------------------------------------------------- games (Steam / Epic)
def is_drive_root(p):
    return len(p.rstrip('\\')) == 2 and p[1] == ':'


def steam_root():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
            p = os.path.normpath(winreg.QueryValueEx(k, 'SteamPath')[0])
            if os.path.isdir(p):
                return p
    except OSError:
        pass
    p = J(PF86, 'Steam')
    return p if os.path.isdir(p) else None


def steam_libraries():
    root = steam_root()
    if not root:
        return []
    libs = [root]
    try:
        with open(J(root, 'steamapps', 'libraryfolders.vdf'), encoding='utf-8', errors='replace') as f:
            txt = f.read()
        for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
            p = os.path.normpath(m.group(1).replace('\\\\', '\\'))
            if os.path.isdir(p) and norm(p) not in {norm(x) for x in libs}:
                libs.append(p)
    except OSError:
        pass
    return libs


def _acf(path):
    out = {}
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            for m in re.finditer(r'^\s*"(\w+)"\s+"([^"]*)"', f.read(), re.M):
                out.setdefault(m.group(1).lower(), m.group(2))
    except OSError:
        pass
    return out


_COVERS = {}


def cover_path(appid):
    if not appid.isdigit():
        return None
    if appid in _COVERS:
        return _COVERS[appid]
    root = steam_root()
    found = None
    if root:
        base = J(root, 'appcache', 'librarycache')
        for name in ('library_hero.jpg', 'header.jpg', 'library_header.jpg', 'library_capsule.jpg', 'library_600x900.jpg'):
            hits = glob.glob(J(E(base), appid, '**', name), recursive=True) + glob.glob(J(E(base), f'{appid}_{name}'))
            if hits:
                found = hits[0]
                break
    _COVERS[appid] = found
    return found


# StateFlags bits: 2 update required, 256 running, 512 paused, 1024 started, 1048576 downloading, 2097152 staging, 4194304 committing
STEAM_BUSY = 2 | 256 | 512 | 1024 | 1048576 | 2097152 | 4194304


def games_info():
    games = []
    for lib in steam_libraries():
        sa = J(lib, 'steamapps')
        for mf in glob.glob(J(E(sa), 'appmanifest_*.acf')):
            a = _acf(mf)
            appid = a.get('appid') or ''
            name = a.get('name') or a.get('installdir') or appid
            if not appid or appid == '228980' or 'redistributable' in name.lower():
                continue
            inst = J(sa, 'common', a.get('installdir', ''))
            size = node_size(inst) or int(a.get('sizeondisk') or 0)
            shader = node_size(J(sa, 'shadercache', appid)) or 0
            dl = node_size(J(sa, 'downloading', appid)) or 0
            todl, dled = int(a.get('bytestodownload') or 0), int(a.get('bytesdownloaded') or 0)
            flags = int(a.get('stateflags') or 0)
            games.append(dict(id='steam:' + appid, appid=appid, store='steam', name=name, path=inst,
                              size=size + shader + dl, shader=shader, downloading=dl,
                              last_played=int(a.get('lastplayed') or 0) or None,
                              last_updated=int(a.get('lastupdated') or 0) or None,
                              updating=bool(flags & STEAM_BUSY) or (todl > 0 and dled < todl),
                              dl_total=todl, dl_done=dled, cover=bool(cover_path(appid))))
    for mf in glob.glob(J(E(PDATA), 'Epic', 'EpicGamesLauncher', 'Data', 'Manifests', '*.item')):
        try:
            with open(mf, encoding='utf-8', errors='replace') as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        loc = d.get('InstallLocation')
        if not loc or not os.path.isdir(loc):
            continue
        games.append(dict(id='epic:' + d.get('AppName', ''), appid='', store='epic', name=d.get('DisplayName') or d.get('AppName'),
                          path=loc, size=node_size(loc) or int(d.get('InstallSize') or 0), shader=0, downloading=0,
                          last_played=None, last_updated=None, updating=False, dl_total=0, dl_done=0, cover=False))
    games.sort(key=lambda g: -(g['size'] or 0))
    return games


# ---------------------------------------------------------------- semantic breakdown: "why is my disk full?"
CONTAINERS = {'local', 'roaming', 'locallow', 'packages', 'programs', 'appdata', 'common files', 'hub'}
GENERIC = {'snapshots', 'blobs', 'hub', 'data', 'common', 'models', 'cache', 'bin', 'lib', 'files', 'x64', 'default',
           'user data', 'storage', 'vms', 'engine', 'content', 'paks', 'localcache', 'localstate'}


def pretty_name(path):
    parts = path.rstrip('\\').split('\\')
    for part in reversed(parts):
        if part.startswith('models--'):                     # HuggingFace: models--Systran--faster-whisper-small
            return part[8:].replace('--', '/')
    base = parts[-1]
    if base.lower() in GENERIC and len(parts) > 1:
        return f"{parts[-2]} › {base}"
    return base


BUCKETS = ['games', 'windows', 'programs', 'appdata', 'cache', 'virtual', 'ai', 'dev', 'downloads', 'user', 'recycle', 'hidden']
VDISK_EXT = {'.vhdx', '.vhd', '.avhdx', '.vdi', '.vmdk', '.qcow2'}
MODEL_EXT = {'.safetensors', '.ckpt', '.gguf', '.onnx', '.pt', '.pth'}


def bucket_rules():
    R = {}

    def add(p, b):
        if p:
            R[norm(p).rstrip('\\')] = b

    def addg(pattern, b):
        for p in glob.glob(pattern):
            add(p, b)

    add(SYSDRIVE, 'user')
    add(HOME, 'user')
    add(WINDIR, 'windows')
    for n in ('Recovery', '$WinREAgent', 'Windows.old', '$Windows.~BT', '$Windows.~WS', '$SysReset', 'ESD',
              'pagefile.sys', 'hiberfil.sys', 'swapfile.sys', 'DumpStack.log.tmp', 'DumpStack.log'):
        add(J(SYSDRIVE, n), 'windows')
    add(J(SYSDRIVE, 'System Volume Information'), 'hidden')
    add(J(SYSDRIVE, '$Recycle.Bin'), 'recycle')
    add(PF, 'programs')
    add(PF86, 'programs')
    add(PDATA, 'appdata')
    add(J(HOME, 'AppData'), 'appdata')
    add(DOWNLOADS, 'downloads')
    # caches: every place the smart cleaner knows about (developer caches that re-download are 'dev'/'ai')
    with SMART_LOCK:
        smart = {k: list(v.get('paths') or []) for k, v in SMART.items()}
    for t in TARGETS:
        if t['kind'] != 'clean':
            continue
        b = 'ai' if t['id'] == 'hf' else 'dev' if (t['group'] == 'dev' and t['risk'] == 'care') else 'cache'
        for p in smart.get(t['id'], []):
            add(p, b)
    add(TEMP, 'cache')
    for lib in steam_libraries():
        for s in ('common', 'shadercache', 'downloading', 'workshop', 'temp', 'compatdata'):
            add(J(lib, 'steamapps', s), 'games')
    for p in (J(PF, 'Epic Games'), J(SYSDRIVE, 'Riot Games'), J(SYSDRIVE, 'XboxGames'), J(PF86, 'GOG Galaxy', 'Games'),
              J(SYSDRIVE, 'GOG Games'), J(PF, 'EA Games'), J(PF86, 'Origin Games'), J(PF86, 'Call of Duty'),
              J(PF, 'Call of Duty'), J(PF86, 'Ubisoft', 'Ubisoft Game Launcher', 'games'), J(PF86, 'Battle.net')):
        add(p, 'games')
    for g in glob.glob(J(E(PDATA), 'Epic', 'EpicGamesLauncher', 'Data', 'Manifests', '*.item')):
        try:
            with open(g, encoding='utf-8', errors='replace') as f:
                add(json.load(f).get('InstallLocation'), 'games')
        except (OSError, ValueError):
            pass
    for p in (J(PDATA, 'BlueStacks_nxt'), J(PDATA, 'BlueStacks'), J(PF, 'BlueStacks_nxt'), J(SYSDRIVE, 'LDPlayer'),
              J(SYSDRIVE, 'Nox'), J(LOCAL, 'wsl'), J(LOCAL, 'Docker'), J(PDATA, 'DockerDesktop'),
              J(ROAM, 'Claude', 'vm_bundles'), J(HOME, 'VirtualBox VMs'), J(HOME, '.android', 'avd'), J(LOCAL, 'Genymobile')):
        add(p, 'virtual')
    addg(J(E(LOCAL), 'Packages', 'CanonicalGroupLimited*'), 'virtual')
    addg(J(E(LOCAL), 'Packages', 'MicrosoftCorporationII.WindowsSubsystemForLinux*'), 'virtual')
    addg(J(E(LOCAL), 'Packages', 'Claude_*', 'LocalCache', 'Roaming', 'Claude', 'vm_bundles'), 'virtual')
    for p in (J(HOME, '.cache', 'huggingface'), J(HOME, '.cache', 'whisper'), J(HOME, '.cache', 'torch'),
              J(HOME, '.ollama'), J(HOME, '.lmstudio'), J(HOME, '.cache', 'lm-studio'), J(PDATA, 'Topaz Labs LLC')):
        add(p, 'ai')
    for p in (J(HOME, '.cache'), J(HOME, '.nuget'), J(HOME, '.gradle'), J(HOME, '.cargo'), J(HOME, '.rustup'),
              J(HOME, 'go'), J(LOCAL, 'Android'), J(HOME, '.m2'), J(HOME, '.vscode'), J(HOME, '.cursor'),
              J(HOME, '.claude'), J(HOME, '.codex'), J(LOCAL, 'ms-playwright')):
        if norm(p).rstrip('\\') not in R:
            add(p, 'dev')
    return R


def compute_breakdown(sc):
    rules = bucket_rules()
    with sc.lock:
        for kp, _ in sc.junk:
            rules.setdefault(norm(kp).rstrip('\\'), 'dev')
        sizes = dict.fromkeys(BUCKETS, 0)
        info, order = {}, []
        stack = [(sc.root, sc.root_path, rules.get(norm(sc.root_path).rstrip('\\'), 'user'), True)]
        while stack:
            node, path, inherited, is_root = stack.pop()
            rb = rules.get(norm(path).rstrip('\\'))
            b = rb or inherited
            info[id(node)] = (b, is_root or rb is not None)
            order.append(node)
            sizes[b] += node.own
            if node.kids:
                for k in node.kids:
                    stack.append((k, os.path.join(path, k.name), b, False))
        # each node's share that stays inside its own bucket (sub-boundaries counted separately)
        contrib = {}
        for node in reversed(order):
            b, _ = info[id(node)]
            c = node.own
            if node.kids:
                for k in node.kids:
                    kb, kbd = info[id(k)]
                    if kb == b and not kbd:
                        c += contrib[id(k)]
            contrib[id(node)] = c
        bnodes = {}
        for node in order:
            b, bd = info[id(node)]
            if bd:
                bnodes.setdefault(b, []).append(node)
        def kids_of(n, b):
            """A node's same-bucket children plus its loose files — what you'd see opening the folder."""
            out = [[contrib[id(k)], k, None] for k in (n.kids or ())
                   if info[id(k)][0] == b and not info[id(k)][1] and contrib[id(k)] > 0]
            if n.own > (64 << 20):
                out.append([n.own, n, 'files'])
            return out

        items = {b: [] for b in BUCKETS}
        for b, nodes in bnodes.items():
            if b in ('virtual', 'ai', 'dev', 'recycle', 'hidden', 'downloads') or len(nodes) >= 4:
                cand = [[contrib[id(n)], n, None] for n in nodes if contrib[id(n)] > 0]
            else:
                cand = [c for n in nodes for c in kids_of(n, b)]
            # "Local 33 GB" says nothing — open up any entry that dominates its bucket (up to 3 levels)
            for _ in range(3):
                tot = sum(c[0] for c in cand) or 1
                cand.sort(key=lambda c: -c[0])
                top = cand[0] if cand else None
                if not top or top[2] or top[0] / tot < 0.45:
                    break
                sub = kids_of(top[1], b)
                if len(sub) < 2:
                    break
                cand = sub + cand[1:]
            for _ in range(2):
                grow = [c for c in cand if not c[2] and c[1].name.lower() in CONTAINERS and len(kids_of(c[1], b)) >= 2]
                if not grow:
                    break
                for c in grow:
                    cand.remove(c)
                    cand += kids_of(c[1], b)
            for size, n, kind in cand:
                p = node_path(n)
                items[b].append([size, os.path.join(p, '*') if kind else p, B("Papkadagi fayllar", "Loose files in folder") if kind else None])
        big = list(sc.big)
        del info, contrib, order
    # file-level corrections: system files at the root, virtual disks and AI models wherever they live
    cache_b = {}

    def bucket_of(path):
        p = norm(path).rstrip('\\')
        trail = []
        while True:
            if p in cache_b:
                b = cache_b[p]
                break
            b = rules.get(p)
            if b:
                break
            trail.append(p)
            parent = os.path.dirname(p)
            if parent == p or not parent:
                b = 'user'
                break
            p = parent.rstrip('\\')
        for t in trail:
            cache_b[t] = b
        return b

    comp = {b: {} for b in BUCKETS}
    moved = []
    for size, path, _mt, _at in big:
        db = bucket_of(os.path.dirname(path))
        fb = rules.get(norm(path)) or db
        ext = os.path.splitext(path)[1].lower()
        if ext in VDISK_EXT and fb != 'windows':
            fb = 'virtual'
        elif ext in MODEL_EXT and fb in ('user', 'downloads', 'appdata', 'cache', 'dev'):
            fb = 'ai'
        if fb != db:
            sizes[db] -= size
            sizes[fb] += size
            moved.append((size, path, db, fb))
        c = cat_of(path)
        comp[fb][c] = comp[fb].get(c, 0) + size
    for size, path, db, fb in moved:
        pl = path.lower()
        for it in items[db]:
            ip = it[1].lower()
            if (ip.endswith('\\*') and os.path.dirname(pl).rstrip('\\') == ip[:-2].rstrip('\\')) or pl.startswith(ip.rstrip('\\') + '\\'):
                it[0] -= size
                break
        if size >= (32 << 20):
            items[fb].append([size, path, None])
    try:
        du = shutil.disk_usage(sc.root_path)
        used, total, free = du.used, du.total, du.free
    except OSError:
        used = total = free = 0
    scanned = sum(sizes.values())
    over = 0
    if is_drive_root(sc.root_path):
        if used > scanned:
            sizes['hidden'] += used - scanned
        else:
            # WinSxS hard links make Windows look bigger than the bytes really used on disk
            over = scanned - used
            sizes['windows'] = max(0, sizes['windows'] - over)
    # caches read better per cleaner target
    with SMART_LOCK:
        smart = [(v.get('size') or 0, (v.get('paths') or [''])[0], TMAP[k]['title']) for k, v in SMART.items()
                 if k in TMAP and TMAP[k]['kind'] == 'clean' and TMAP[k]['group'] != 'dev' and v.get('size')]
    if smart:
        items['cache'] = [list(x) for x in smart]
    out = []
    for b in BUCKETS:
        if sizes[b] <= 0:
            continue
        lst = sorted((i for i in items[b] if i[0] > 0), key=lambda i: -i[0])[:8]
        base_names = [i[2] or pretty_name(i[1]) or i[1] for i in lst]
        names = list(base_names)
        for n, i in enumerate(lst):
            twins = [lst[m][1] for m, nm in enumerate(base_names) if nm == base_names[n] and m != n]
            if i[2] or not twins:
                continue
            # two "vm_bundles" -> "Claude › vm_bundles (Roaming)" / "(Local)": name the first folder where they differ
            parts, other = i[1].rstrip('\\').split('\\'), twins[0].rstrip('\\').split('\\')
            k = next((x for x in range(min(len(parts), len(other))) if parts[x].lower() != other[x].lower()), 0)
            head = base_names[n] if base_names[n] != parts[-1] else (f"{parts[-2]} › {parts[-1]}" if len(parts) > 2 else parts[-1])
            names[n] = head if parts[k] in head else f"{head} ({parts[k]})"
        out.append(dict(id=b, size=sizes[b],
                        items=[dict(size=i[0], path=i[1], name=names[n], files=bool(i[2])) for n, i in enumerate(lst)],
                        comp=sorted(([c, v] for c, v in comp[b].items() if v > 0), key=lambda x: -x[1])[:6]))
    out.sort(key=lambda d: -d['size'])
    return dict(ts=time.time(), root=sc.root_path, drive=is_drive_root(sc.root_path), total=total, used=used, free=free,
                scanned=scanned, over=over, buckets=out)


def get_breakdown():
    sc = SCAN
    if not sc or sc.state != 'done':
        return None
    if getattr(sc, 'bd', None) is None or sc.bd_ver != sc.version:
        ver = sc.version
        sc.bd = compute_breakdown(sc)
        sc.bd_ver = ver
    return sc.bd


def snapshot_dirs(sc, min_size=64 << 20, max_depth=6):
    out = {}
    with sc.lock:
        stack = [(sc.root, sc.root_path, 0)]
        while stack:
            n, p, d = stack.pop()
            out[p] = n.size
            if d < max_depth and n.kids:
                for k in n.kids:
                    if k.size >= min_size:
                        stack.append((k, os.path.join(p, k.name), d + 1))
    return out


def on_scan_done(sc):
    try:
        if sc.cancelled or not is_drive_root(sc.root_path):
            return
        bd = get_breakdown()
        if bd is None:
            return
        rec = dict(ts=round(time.time()), root=sc.root_path, used=bd['used'], free=bd['free'], scanned=bd['scanned'],
                   files=sc.files, buckets={b['id']: b['size'] for b in bd['buckets']}, dirs=snapshot_dirs(sc))
        scans = _read_json(SCANS_PATH, [])
        scans.append(rec)
        _write_json(SCANS_PATH, scans[-6:])
        sample_free(force=True)
    except Exception:
        traceback.print_exc()


def growth():
    scans = _read_json(SCANS_PATH, [])
    meta = [dict(ts=s['ts'], used=s['used'], free=s['free'], scanned=s['scanned']) for s in scans]
    if len(scans) < 2:
        return dict(ready=False, scans=meta)
    a, b = scans[-2], scans[-1]
    da, db = a['dirs'], b['dirs']
    delta = {k: db.get(k, 0) - da.get(k, 0) for k in set(da) | set(db)}
    cand = {k: v for k, v in delta.items() if abs(v) >= (200 << 20)}
    low = {k: k.lower().rstrip('\\') + '\\' for k in cand}
    keep = []
    for k, v in cand.items():
        desc = [c for c in cand if c != k and low[c].startswith(low[k]) and (cand[c] > 0) == (v > 0)]
        top = [c for c in desc if not any(o != c and low[c].startswith(low[o]) for o in desc)]
        if sum(abs(cand[c]) for c in top) < 0.7 * abs(v):
            keep.append((k, v))
    keep = [(k, v) for k, v in keep if not any(o != k and low[k].startswith(low[o]) for o, _ in keep)]
    keep.sort(key=lambda x: -abs(x[1]))
    bucket_delta = {k: b['buckets'].get(k, 0) - a['buckets'].get(k, 0) for k in set(a['buckets']) | set(b['buckets'])}
    return dict(ready=True, scans=meta, from_ts=a['ts'], to_ts=b['ts'], used_delta=b['used'] - a['used'],
                items=[dict(path=k, delta=v, now=db.get(k, 0)) for k, v in keep[:16]],
                buckets=sorted(([k, v] for k, v in bucket_delta.items() if abs(v) >= (100 << 20)), key=lambda x: -abs(x[1])))


def progress_payload():
    with HIST_LOCK:
        samples = list(HIST['samples'])
        events = list(HIST['events'])
        freed_total = HIST['freed_total']
    if len(samples) > 500:     # keep the chart light: even thinning, always keep the latest point
        step = len(samples) / 500
        samples = [samples[int(i * step)] for i in range(500)] + [samples[-1]]
    return dict(samples=samples, events=events[-60:], freed_total=freed_total, session=dict(STATS),
                prognosis=prognosis(), growth=growth())


# ---------------------------------------------------------------- data endpoints
def list_children(path, limit=500):
    if not os.path.isdir(lp(path)):
        raise FileNotFoundError(path)
    sc = SCAN
    node = sc.index.get(norm(path)) if sc else None
    items = []
    if node is not None and node.kids:
        with sc.lock:
            kids = list(node.kids)
        for k in kids:
            kp = os.path.join(path, k.name)
            items.append(dict(name=k.name, path=kp, dir=True, size=k.size, files=k.nfiles, dirs=k.ndirs,
                              mtime=k.mtime, err=k.err, junk=k.junk))
    try:
        with os.scandir(lp(path)) as it:
            for e in it:
                try:
                    s = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                a = s.st_file_attributes
                isdir = bool(a & 0x10)
                if isdir:
                    if node is not None:
                        continue
                    link = bool(a & 0x400 and s.st_reparse_tag in REPARSE_LINK_TAGS)
                    items.append(dict(name=e.name, path=os.path.join(path, e.name), dir=True, size=None,
                                      mtime=s.st_mtime, link=link))
                else:
                    sz = 0 if a & CLOUD_ONLY else s.st_size
                    items.append(dict(name=e.name, path=os.path.join(path, e.name), dir=False, size=sz,
                                      mtime=s.st_mtime, cat=cat_of(e.name), cloud=bool(a & CLOUD_ONLY)))
    except OSError:
        pass
    items.sort(key=lambda i: -(i['size'] if i['size'] is not None else -1))
    more = items[limit:]
    items = items[:limit]
    for i in items:
        i['prot'] = protected(i['path'])
        i['warn'] = warn_of(i['path'])
    parent = os.path.dirname(path.rstrip('\\')) if len(path.rstrip('\\')) > 2 else None
    if parent and len(parent) == 2:
        parent += '\\'
    return dict(path=path, parent=parent, scanned=node is not None,
                size=node.size if node is not None else sum(i['size'] or 0 for i in items),
                files=node.nfiles if node is not None else None,
                items=items, more=len(more), more_size=sum(i['size'] or 0 for i in more),
                scan_state=sc.state if sc else None)


def big_files(q):
    sc = SCAN
    if not sc:
        return dict(items=[], scanned=False)
    cat = q.get('cat') or ''
    text = (q.get('q') or '').lower()
    scope = q.get('scope') or 'user'
    age = float(q.get('age') or 0)
    lim = max(1, min(int(q.get('limit') or 300), 3000))
    minsize = int(q.get('min') or 0)
    cutoff = time.time() - age * 86400 if age > 0 else None
    newer = time.time() + age * 86400 if age < 0 else None   # negative age = recently changed
    with sc.lock:
        data = list(sc.big)
    match = []
    tsize = 0
    for b in data:
        if b[0] < minsize:
            continue
        pl = b[1].lower()
        if scope == 'user' and is_sys_lower(pl):
            continue
        if cutoff and b[2] > cutoff:
            continue
        if newer and b[2] < newer:
            continue
        if cat and cat_of(pl) != cat:
            continue
        if text and text not in pl:
            continue
        match.append(b)
        tsize += b[0]
    top = heapq.nlargest(lim, match)
    items = [dict(path=b[1], name=os.path.basename(b[1]), size=b[0], mtime=b[2], cat=cat_of(b[1]),
                  prot=protected(b[1]), warn=warn_of(b[1])) for b in top]
    return dict(items=items, count=len(match), size=tsize, scanned=True, state=sc.state)


def types_summary():
    sc = SCAN
    if not sc:
        return dict(cats=[], exts=[])
    with sc.lock:
        ext = {k: list(v) for k, v in sc.ext.items()}
    cats = {}
    for x, (c, s) in ext.items():
        k = EXT2CAT.get(x, 'other')
        d = cats.setdefault(k, dict(cat=k, size=0, count=0, exts=[]))
        d['size'] += s
        d['count'] += c
        d['exts'].append((s, x, c))
    out = []
    for d in cats.values():
        d['exts'] = [dict(ext=x or '(kengaytmasiz)', size=s, count=c) for s, x, c in sorted(d['exts'], reverse=True)[:8]]
        out.append(d)
    out.sort(key=lambda d: -d['size'])
    exts = sorted(((s, x, c) for x, (c, s) in ext.items()), reverse=True)[:40]
    return dict(cats=out, exts=[dict(ext=x or '(kengaytmasiz)', size=s, count=c, cat=EXT2CAT.get(x, 'other'))
                                for s, x, c in exts], state=sc.state)


def junk_list():
    sc = SCAN
    if not sc:
        return dict(items=[], scanned=False)
    with sc.lock:
        data = list(sc.junk)
    items = []
    for kp, k in data:
        proj = os.path.dirname(kp)
        try:
            pm = os.stat(proj).st_mtime
        except OSError:
            pm = k.mtime
        items.append(dict(path=kp, kind=k.junk, size=k.size, files=k.nfiles, mtime=max(k.mtime, pm),
                          project=proj, prot=protected(kp)))
    items.sort(key=lambda i: -i['size'])
    return dict(items=items, scanned=True, state=sc.state, total=sum(i['size'] for i in items))


APPS = {}


def _qv(k, n):
    try:
        return winreg.QueryValueEx(k, n)[0]
    except OSError:
        return None


def list_apps():
    out = {}
    U = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
    hives = [(winreg.HKEY_LOCAL_MACHINE, 'HKLM', winreg.KEY_WOW64_64KEY), (winreg.HKEY_LOCAL_MACHINE, 'HKLM32', winreg.KEY_WOW64_32KEY),
             (winreg.HKEY_CURRENT_USER, 'HKCU', 0)]
    for hive, hn, flag in hives:
        try:
            root = winreg.OpenKey(hive, U, 0, winreg.KEY_READ | flag)
        except OSError:
            continue
        with root:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        name = _qv(k, 'DisplayName')
                        un = _qv(k, 'UninstallString')
                        if not name or not un or _qv(k, 'SystemComponent') == 1 or _qv(k, 'ParentKeyName'):
                            continue
                        if (_qv(k, 'ReleaseType') or '') in ('Update', 'Hotfix', 'Security Update'):
                            continue
                        est = _qv(k, 'EstimatedSize')
                        loc = (_qv(k, 'InstallLocation') or '').strip().strip('"')
                        size, src = (int(est) * 1024, 'reg') if isinstance(est, int) else (None, None)
                        if loc and len(loc) > 3 and os.path.isdir(loc) and not protected_root(loc):
                            ns = node_size(loc)
                            if ns:
                                size, src = ns, 'scan'
                        date = str(_qv(k, 'InstallDate') or '')
                        key = f'{hn}|{sub}'
                        dk = (name.lower(), str(_qv(k, 'DisplayVersion') or ''))
                        if dk in out:
                            continue
                        APPS[key] = un
                        out[dk] = dict(key=key, name=name, version=_qv(k, 'DisplayVersion') or '',
                                       publisher=_qv(k, 'Publisher') or '', size=size, src=src, location=loc,
                                       reg=int(est) * 1024 if isinstance(est, int) else None,
                                       date=f'{date[:4]}-{date[4:6]}-{date[6:8]}' if len(date) == 8 and date.isdigit() else '')
                except OSError:
                    continue
    # several apps pointing at one shared folder (e.g. Program Files\Adobe) would each claim its full size
    locs = {}
    for a in out.values():
        if a['src'] == 'scan':
            locs[norm(a['location'])] = locs.get(norm(a['location']), 0) + 1
    for a in out.values():
        if a['src'] == 'scan' and locs[norm(a['location'])] > 1:
            a['size'], a['src'] = (a['reg'], 'reg') if a['reg'] else (None, None)
    items = sorted(out.values(), key=lambda a: -(a['size'] or 0))
    return dict(items=items, total=sum(a['size'] or 0 for a in items))


def protected_root(p):
    return norm(p) in (norm(PF), norm(PF86), norm(SYSDRIVE), norm(WINDIR))


def uninstall(key):
    un = APPS.get(key)
    if not un:
        raise ValueError(B("Dastur topilmadi — roʻyxatni yangilang", "App not found — refresh the list"))
    if re.search(r'msiexec', un, re.I):
        un = re.sub(r'/I\s*\{', '/X{', un, flags=re.I)
    subprocess.Popen(un, shell=True)
    return dict(ok=True)


def downloads_info():
    d = DOWNLOADS
    files = []
    now = time.time()
    stack = [(d, 0)]
    dirs_at = {}
    while stack:
        p, depth = stack.pop()
        try:
            with os.scandir(lp(p)) as it:
                ents = list(it)
        except OSError:
            continue
        names = set()
        for e in ents:
            try:
                s = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if s.st_file_attributes & 0x10:
                names.add(e.name.lower())
                if depth < 4 and not s.st_file_attributes & 0x400:
                    stack.append((e.path, depth + 1))
            else:
                files.append((e.path, s.st_size, s.st_mtime))
        dirs_at[norm(p)] = names
    groups = {'installers': [], 'extracted': [], 'videos': [], 'old': []}
    used = set()
    for path, size, mt in files:
        name = os.path.basename(path)
        stem, ext = os.path.splitext(name)
        c = cat_of(name)
        sib = dirs_at.get(norm(os.path.dirname(path)), set())
        it = dict(path=path, name=name, size=size, mtime=mt, cat=c)
        if c == 'installer':
            groups['installers'].append(it)
            used.add(path)
        elif ext.lower() in ('.zip', '.rar', '.7z') and stem.lower() in sib:
            groups['extracted'].append(it)
            used.add(path)
        elif c == 'video' and size >= 200 << 20:
            groups['videos'].append(it)
            used.add(path)
    for path, size, mt in files:
        if path not in used and size >= 20 << 20 and now - mt > 180 * 86400:
            groups['old'].append(dict(path=path, name=os.path.basename(path), size=size, mtime=mt, cat=cat_of(path)))
    for g in groups.values():
        g.sort(key=lambda i: -i['size'])
    return dict(path=d, total=sum(f[1] for f in files), count=len(files),
                groups={k: dict(items=v[:300], size=sum(i['size'] for i in v), count=len(v)) for k, v in groups.items()})


def info():
    rb, rn = recycle_info()
    return dict(admin=ADMIN, user=os.environ.get('USERNAME', ''), home=HOME, downloads=DOWNLOADS, sysdrive=SYSDRIVE,
                drives=drives(), recycle=dict(size=rb, count=rn), stats=dict(STATS, freed_total=HIST['freed_total']),
                scan=SCAN.status() if SCAN else None, port=PORT, version=APP_VERSION)


def elevate():
    if ADMIN:
        return dict(ok=True, already=True)
    params = f'"{os.path.abspath(__file__)}" --port {PORT} --wait-port' + (' --app' if APP_MODE else '')
    r = SH32.ShellExecuteW(None, 'runas', sys.executable, params, HERE, 7)
    if r <= 32:
        return dict(ok=False, error=B("Ruxsat berilmadi (UAC bekor qilindi)", "Permission denied (UAC cancelled)"))
    threading.Timer(0.6, lambda: os._exit(0)).start()
    return dict(ok=True)


def reveal(path):
    path = os.path.normpath(path)
    if os.path.isdir(path):
        subprocess.Popen(['explorer', path])
    else:
        subprocess.Popen(f'explorer /select,"{path}"')
    return dict(ok=True)


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _host_ok(self):
        return self.headers.get('Host', '').split(':')[0] in ('127.0.0.1', 'localhost')

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        elif isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    STATIC_TYPES = {'.woff2': 'font/woff2', '.png': 'image/png', '.ico': 'image/x-icon', '.css': 'text/css; charset=utf-8',
                    '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.txt': 'text/plain; charset=utf-8',
                    '.svg': 'image/svg+xml', '.jpg': 'image/jpeg'}

    def _static(self, r):
        rel = {'/favicon.ico': 'assets/xotira.ico', '/icon.png': 'assets/icon.png'}.get(r, r.lstrip('/'))
        fp = os.path.normpath(os.path.join(HERE, rel))
        ctype = self.STATIC_TYPES.get(os.path.splitext(fp)[1].lower())
        if not ctype or not under(fp, HERE) or not os.path.isfile(fp):
            return self._send(404, {'error': 'not found'})
        with open(fp, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'max-age=86400')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        LAST_HIT[0] = time.time()
        if not self._host_ok():
            return self._send(403, {'error': 'host'})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        r = u.path
        try:
            if r in ('/', '/index.html'):
                with open(os.path.join(HERE, 'index.html'), 'rb') as f:
                    return self._send(200, f.read(), 'text/html; charset=utf-8')
            if r in ('/favicon.ico', '/icon.png') or r.startswith('/assets/') or r in ('/demo.js', '/demo.json'):
                return self._static(r)
            if r == '/api/info':
                return self._send(200, info())
            if r == '/api/status':
                jobs = [j.d() for j in JOBS.values() if j.state == 'running']
                return self._send(200, dict(scan=SCAN.status() if SCAN else None, jobs=jobs, stats=dict(STATS)))
            if r == '/api/children':
                return self._send(200, list_children(q.get('path') or SYSDRIVE))
            if r == '/api/big':
                return self._send(200, big_files(q))
            if r == '/api/types':
                return self._send(200, types_summary())
            if r == '/api/junk':
                return self._send(200, junk_list())
            if r == '/api/smart':
                return self._send(200, smart_payload())
            if r == '/api/apps':
                return self._send(200, list_apps())
            if r == '/api/downloads':
                return self._send(200, downloads_info())
            if r == '/api/overview':
                return self._send(200, dict(breakdown=get_breakdown(), scan=SCAN.status() if SCAN else None, admin=ADMIN))
            if r == '/api/games':
                return self._send(200, dict(items=games_info(), scanned=bool(SCAN and SCAN.state == 'done')))
            if r == '/api/progress':
                return self._send(200, progress_payload())
            if r == '/api/cover':
                cp = cover_path(q.get('appid', ''))
                if not cp:
                    return self._send(404, {'error': 'cover'})
                with open(cp, 'rb') as f:
                    data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'max-age=86400')
                self.end_headers()
                self.wfile.write(data)
                return
            if r == '/api/job':
                j = JOBS.get(q.get('id', ''))
                return self._send(200 if j else 404, j.d() if j else {'error': 'job'})
            return self._send(404, {'error': 'not found'})
        except FileNotFoundError:
            return self._send(404, {'error': B("Papka topilmadi", "Folder not found")})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {'error': e.args[0] if e.args and isinstance(e.args[0], dict) else str(e)})

    def do_POST(self):
        LAST_HIT[0] = time.time()
        # localhost-only + custom header => other websites can't trigger deletes (CORS preflight blocks them)
        if not self._host_ok() or self.headers.get('X-Xotira') != '1':
            return self._send(403, {'error': 'forbidden'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            b = json.loads(self.rfile.read(n) or b'{}') if n else {}
        except Exception:
            return self._send(400, {'error': 'bad json'})
        r = urlparse(self.path).path
        try:
            if r == '/api/scan':
                sc = start_scan(b.get('path') or SYSDRIVE)
                return self._send(200, sc.status())
            if r == '/api/scan/cancel':
                if SCAN:
                    SCAN.cancelled = True
                return self._send(200, {'ok': True})
            if r == '/api/smart/refresh':
                threading.Thread(target=measure_all, daemon=True).start()
                return self._send(200, {'ok': True})
            if r == '/api/clean':
                ids = [i for i in b.get('ids', []) if i in TMAP]
                return self._send(200, start_job('clean', 'Tozalash', job_clean, ids).d())
            if r == '/api/delete':
                paths = [p for p in b.get('paths', []) if isinstance(p, str) and p]
                mode = 'permanent' if b.get('mode') == 'permanent' else 'recycle'
                return self._send(200, start_job('delete', "O'chirish", job_delete, paths, mode).d())
            if r == '/api/dups':
                return self._send(200, start_job('dups', 'Dublikatlar', job_dups).d())
            if r == '/api/job/cancel':
                j = JOBS.get(b.get('id', ''))
                if j:
                    j.cancel = True
                return self._send(200, {'ok': bool(j)})
            if r == '/api/reveal':
                return self._send(200, reveal(b['path']))
            if r == '/api/open':
                os.startfile(os.path.normpath(b['path']))
                return self._send(200, {'ok': True})
            if r == '/api/uninstall':
                return self._send(200, uninstall(b.get('key', '')))
            if r == '/api/elevate':
                return self._send(200, elevate())
            if r == '/api/game/uninstall':
                appid = str(b.get('appid', ''))
                if not appid.isdigit():
                    return self._send(400, {'error': 'appid'})
                os.startfile(f'steam://uninstall/{appid}')
                return self._send(200, {'ok': True})
            if r == '/api/shutdown':
                threading.Timer(0.3, lambda: os._exit(0)).start()
                return self._send(200, {'ok': True})
            return self._send(404, {'error': 'not found'})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {'error': e.args[0] if e.args and isinstance(e.args[0], dict) else str(e)})


class Server(ThreadingHTTPServer):
    allow_reuse_address = False   # on Windows SO_REUSEADDR would let two servers share the port
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return   # browser closed the tab mid-request — not an error worth logging
        super().handle_error(request, client_address)


def make_server(wait=0):
    deadline = time.time() + wait
    while True:
        try:
            return Server(('127.0.0.1', PORT), Handler)
        except OSError:
            if time.time() >= deadline:
                return None
            time.sleep(0.5)


def ask_running_to_quit():
    import urllib.request
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{PORT}/api/shutdown', data=b'{}', method='POST',
                                     headers={'Content-Type': 'application/json', 'X-Xotira': '1'})
        urllib.request.urlopen(req, timeout=3).read()
        return True
    except Exception:
        return False


class _Tee:
    """Mirror console output into xotira.log so a crash can be diagnosed after the window closes."""

    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, s):
        for t in (self.stream, self.log):
            try:
                t.write(s)
                t.flush()
            except Exception:
                pass

    def flush(self):
        pass


def setup_log():
    os.makedirs(DATA_ROOT, exist_ok=True)
    path = os.path.join(DATA_ROOT, 'xotira.log')
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1 << 20:
            os.remove(path)
        log = open(path, 'a', encoding='utf-8')
    except OSError:
        return
    sys.stdout, sys.stderr = _Tee(sys.stdout, log), _Tee(sys.stderr, log)
    print(f'\n--- {time.strftime("%Y-%m-%d %H:%M:%S")}  v{APP_VERSION}  pid={os.getpid()}  admin={ADMIN}  argv={sys.argv[1:]}')


def idle_watch():
    """The app window polls every 1-3 s (about once a minute when minimised). Silence means it was closed."""
    while True:
        time.sleep(10)
        busy = any(j.state == 'running' for j in JOBS.values())
        if not busy and time.time() - LAST_HIT[0] > IDLE_EXIT:
            print(f"No requests for {IDLE_EXIT} s (window closed) — stopping.", flush=True)
            os._exit(0)


def main():
    setup_log()
    url = f'http://127.0.0.1:{PORT}/'
    httpd = make_server(40 if '--wait-port' in sys.argv else 0)
    if httpd is None and '--takeover' in sys.argv and ask_running_to_quit():
        # admin launcher replaces a normal-mode instance that is already running
        httpd = make_server(20)
    if httpd is None:
        print(f'Xotira is already running: {url}')
        if '--open' in sys.argv:
            webbrowser.open(url)
        return
    print(f'Xotira {APP_VERSION}: {url}   (admin: {ADMIN})', flush=True)
    print("Stops by itself after the app window is closed." if APP_MODE else "Close this window to stop Xotira.", flush=True)
    threading.Thread(target=measure_all, daemon=True).start()
    threading.Thread(target=sampler, daemon=True).start()
    if APP_MODE:
        threading.Thread(target=idle_watch, daemon=True).start()
    if '--no-scan' not in sys.argv:
        start_scan(SYSDRIVE)
    if '--open' in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
