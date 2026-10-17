"""Xotira launcher: starts the hidden local server and opens Xotira in its own app window.

    pythonw launcher.pyw            # normal mode
    pythonw launcher.pyw --admin    # full access (Windows asks for administrator rights)
    pythonw launcher.pyw --quit     # stop a running Xotira (used by the installer)
"""
import ctypes
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
import winreg

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('XOTIRA_PORT', 4477))
URL = f'http://127.0.0.1:{PORT}/'
PROFILE = os.path.join(os.environ.get('LOCALAPPDATA', HERE), 'Xotira', 'window')


def pythonw():
    cand = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    return cand if os.path.exists(cand) else sys.executable


def status():
    try:
        with urllib.request.urlopen(URL + 'api/info', timeout=1.5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def close_windows():
    """Politely close Xotira app windows (WM_CLOSE), so an uninstall or upgrade can remove their profile."""
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def each(hwnd, _):
        title = ctypes.create_unicode_buffer(256)
        cls = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, title, 256)
        user32.GetClassNameW(hwnd, cls, 64)
        if title.value.startswith('Xotira — ') and cls.value == 'Chrome_WidgetWin_1':
            found.append(hwnd)
        return True

    user32.EnumWindows(each, None)
    for hwnd in found:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)          # WM_CLOSE
    return len(found)


def quit_running():
    try:
        req = urllib.request.Request(URL + 'api/shutdown', data=b'{}', method='POST',
                                     headers={'Content-Type': 'application/json', 'X-Xotira': '1'})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass
    if close_windows():
        time.sleep(2)            # let the window process exit and release its profile
    for _ in range(20):          # wait until the server has released its files
        if status() is None:
            return
        time.sleep(0.25)


def start_server(admin):
    server = os.path.join(HERE, 'server.py')
    if admin:
        r = ctypes.windll.shell32.ShellExecuteW(None, 'runas', pythonw(), f'"{server}" --app --takeover', HERE, 0)
        return r > 32
    subprocess.Popen([pythonw(), server, '--app'], cwd=HERE, creationflags=0x00000008 | 0x00000200, close_fds=True)
    return True


def find_browser():
    for exe in ('msedge.exe', 'chrome.exe'):
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, rf'Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}') as k:
                    p = winreg.QueryValueEx(k, '')[0]
                    if os.path.exists(p):
                        return p
            except OSError:
                pass
    for root in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')):
        for rel in (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe'):
            p = os.path.join(root or '', rel)
            if root and os.path.exists(p):
                return p
    return None


def open_window():
    br = find_browser()
    if not br:
        webbrowser.open(URL)
        return
    # a dedicated profile makes it a separate app window with its own taskbar entry, not a browser tab
    subprocess.Popen([br, f'--app={URL}', f'--user-data-dir={PROFILE}', '--window-size=1440,920',
                      '--no-first-run', '--no-default-browser-check', '--disable-sync',
                      '--disable-features=Translate,msEdgeSidebarV2'], close_fds=True)


def message(text):
    ctypes.windll.user32.MessageBoxW(None, text, 'Xotira', 0x40)


def main():
    if '--quit' in sys.argv:
        quit_running()
        return
    admin = '--admin' in sys.argv
    st = status()
    if st is None or (admin and not st.get('admin')):
        if not start_server(admin):
            if st is not None:            # UAC declined, but a normal-mode server is already up
                open_window()
                return
            message("Administrator ruxsati berilmadi — Xotira oddiy rejimda ochiladi.\n"
                    "Administrator rights were not granted — Xotira opens in normal mode.")
            start_server(False)
            admin = False
        deadline = time.time() + 40
        while time.time() < deadline:
            time.sleep(0.4)
            st = status()
            if st and (not admin or st.get('admin') or time.time() > deadline - 30):
                break
        if st is None:
            log = os.path.join(os.environ.get('LOCALAPPDATA', HERE), 'Xotira', 'xotira.log')
            message("Xotira ishga tushmadi. / Xotira failed to start.\n\n" + log)
            return
    open_window()


if __name__ == '__main__':
    main()
