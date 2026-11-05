"""Isaac console panel anchored to the local Arknights PC window."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault('QT_SCALE_FACTOR', '1')
from PySide6.QtCore import Qt, QTimer, QProcess, QLockFile, Signal, QObject, QThread, Slot
from PySide6.QtGui import QFontDatabase, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QPlainTextEdit, QCompleter)
from console_commands import console_source, decode_response
from control import pause, resume_block_reason

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT.parent/'ark-venv/Scripts/python.exe'
REQUEST = ROOT/'console-open.request'
user = C.windll.user32
user.GetForegroundWindow.restype = W.HWND
user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
user.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
user.SetForegroundWindow.argtypes = [W.HWND]
user.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user.IsIconic.argtypes = [W.HWND]
user.GetAsyncKeyState.argtypes = [C.c_int]
user.GetAsyncKeyState.restype = C.c_short
user.SetWindowLongPtrW.argtypes = [W.HWND, C.c_int, C.c_ssize_t]
user.SetWindowLongPtrW.restype = C.c_ssize_t


def window_pid(window):
    pid = W.DWORD()
    user.GetWindowThreadProcessId(window, C.byref(pid))
    return pid.value


def game_window():
    try:
        pid = int((ROOT.parent/'pc-game.pid').read_text())
        # Verify the executable as well as the PID before anchoring any UI.
        kernel = C.windll.kernel32
        kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        kernel.OpenProcess.restype = W.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        kernel.CloseHandle.argtypes = [W.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            path = C.create_unicode_buffer(32768)
            length = W.DWORD(len(path))
            if not kernel.QueryFullProcessImageNameW(handle, 0, path, C.byref(length)):
                return None
            if path.value.lower() != r'd:\arknightslocal-codex-20261103\client\arknights.exe':
                return None
        finally:
            kernel.CloseHandle(handle)
        windows = []
        @C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        def callback(window, unused):
            if window_pid(window) == pid:
                name = C.create_unicode_buffer(128)
                user.GetClassNameW(window, name, len(name))
                if name.value == 'UnityWndClass':
                    windows.append(window)
            return True
        user.EnumWindows(callback, 0)
        return (windows[0], pid) if windows else None
    except (OSError, ValueError):
        return None


class CommandInput(QLineEdit):
    def __init__(self):
        super().__init__()
        self.history = []
        self.index = 0
        self.draft = ''
        self.setMaxLength(2048)

    def remember(self, command):
        if not self.history or self.history[-1] != command:
            self.history.append(command)
        self.history = self.history[-100:]
        self.index = len(self.history)
        self.draft = ''

    def keyPressEvent(self, event):
        popup = self.completer().popup()
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if popup:
                popup.hide()
            self.returnPressed.emit()
            return
        if event.key() in (Qt.Key_Up, Qt.Key_Down) and not (popup and popup.isVisible()):
            if self.index == len(self.history):
                self.draft = self.text()
            self.index = max(0, min(len(self.history), self.index + (-1 if event.key() == Qt.Key_Up else 1)))
            self.setText(self.history[self.index] if self.index < len(self.history) else self.draft)
            return
        super().keyPressEvent(event)


class ConsoleWindow(QWidget):
    closed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowTitle('以撒控制台 · 方舟联动')
        self.setStyleSheet('''QWidget{background:#182127;color:#e9f3ee;font:14px "Microsoft YaHei";}
QPushButton{background:#30463f;border:1px solid #648578;border-radius:4px;padding:7px 12px;}
QPushButton:disabled{color:#78837f;} QLineEdit,QPlainTextEdit{background:#10171c;border:1px solid #49645a;padding:8px;}
QLineEdit{font:16px Consolas,"Microsoft YaHei";} QPlainTextEdit{font:13px Consolas,"Microsoft YaHei";}''')
        box = QVBoxLayout(self)
        row = QHBoxLayout()
        title = QLabel('以撒控制台')
        title.setStyleSheet('font-size:20px;font-weight:bold;')
        row.addWidget(title)
        row.addStretch()
        close = QPushButton('关闭 · F2 / Esc')
        close.clicked.connect(lambda: self.closed.emit(False))
        row.addWidget(close)
        box.addLayout(row)
        self.status = QLabel('正在连接……')
        box.addWidget(self.status)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(1200)
        box.addWidget(self.output)
        row = QHBoxLayout()
        self.input = CommandInput()
        self.input.setPlaceholderText('输入原版指令，例如 giveitem c118；回车执行')
        completion = QCompleter(['giveitem ', 'remove ', 'spawn ', 'debug ',
            'help ', 'lua ', 'luamod ', 'goto ', 'stage ', 'restart', 'clear'], self.input)
        completion.setCompletionMode(QCompleter.InlineCompletion)
        self.input.setCompleter(completion)
        row.addWidget(self.input)
        self.execute = QPushButton('执行 ↵')
        row.addWidget(self.execute)
        box.addLayout(row)
        row = QHBoxLayout()
        hint = QLabel('↑ ↓ 历史指令 · 输出来自以撒原生控制台')
        row.addWidget(hint)
        row.addStretch()
        self.refresh_button = QPushButton('刷新输出')
        row.addWidget(self.refresh_button)
        self.resume = QPushButton('关闭并继续作战')
        self.resume.clicked.connect(lambda: self.closed.emit(True))
        row.addWidget(self.resume)
        box.addLayout(row)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_F2):
            self.closed.emit(False)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        event.ignore()
        self.closed.emit(False)

    def append(self, text):
        self.output.appendPlainText(text)
        self.output.moveCursor(QTextCursor.End)


class ConsoleHotkey(QThread):
    toggled = Signal()

    def suppress_until_release(self):
        script = getattr(self, 'script', None)
        if script and not script.is_destroyed:
            try: script.exports_sync.suppress()
            except Exception: pass

    def grant_foreground(self):
        script = getattr(self, 'script', None)
        if script and not script.is_destroyed:
            try: script.exports_sync.grant()
            except Exception: pass

    def run(self):
        import frida
        while not self.isInterruptionRequested():
            session = None
            try:
                session = frida.get_remote_device().attach('Gadget')
                script = session.create_script(r'''
if(Process.mainModule.path.toLowerCase()!=='d:\\arknightslocal-codex-20261103\\client\\arknights.exe')throw Error('Unexpected test client');
const u=Process.getModuleByName('user32.dll');
const key=new NativeFunction(u.getExportByName('GetAsyncKeyState'),'int16',['int']);
const foreground=new NativeFunction(u.getExportByName('GetForegroundWindow'),'pointer',[]);
const windowPid=new NativeFunction(u.getExportByName('GetWindowThreadProcessId'),'uint',['pointer','pointer']);
const allow=new NativeFunction(u.getExportByName('AllowSetForegroundWindow'),'bool',['uint']);
const pid=Memory.alloc(4);let previous=false,suppressed=false;
rpc.exports.suppress=()=>{suppressed=true;};
rpc.exports.grant=()=>allow(__CONSOLE_PID__);
setInterval(()=>{const down=!!(key(0x71)&0x8000);windowPid(foreground(),pid);
 if(!down)suppressed=false;
 if(down&&!previous&&!suppressed&&pid.readU32()===Process.id)send('toggle');previous=down;},20);
'''.replace('__CONSOLE_PID__', str(os.getpid())))
                script.on('message', lambda message, data: self.toggled.emit()
                    if message.get('type') == 'send' and message.get('payload') == 'toggle' else None)
                script.load()
                self.script = script
                while not self.isInterruptionRequested() and not script.is_destroyed:
                    self.msleep(100)
            except Exception as error:
                print('Console hotkey: '+str(error), flush=True)
                self.msleep(1000)
            finally:
                self.script = None
                if session:
                    try: session.detach()
                    except Exception: pass


class ConsoleOverlay(QObject):
    def __init__(self):
        super().__init__()
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
        self.game = None
        self.game_check = 0
        self.opened = False
        self.data = {}
        self.online = False
        self.process = None
        self.pending_command = None
        self.pause_epoch = None
        self.window = ConsoleWindow()
        self.window.closed.connect(self.close)
        self.window.execute.clicked.connect(self.execute)
        self.window.input.returnPressed.connect(self.execute)
        self.window.refresh_button.clicked.connect(lambda: self.evaluate(None))
        self.button = QPushButton('以撒控制台 · F2')
        self.button.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.button.setAttribute(Qt.WA_ShowWithoutActivating)
        self.button.setStyleSheet('QPushButton{background:#213c35;color:#d8ffdf;border:1px solid #6b9d83;border-radius:4px;font:14px "Microsoft YaHei";padding:5px 10px;}')
        self.button.clicked.connect(self.toggle)
        self.hotkey = ConsoleHotkey(self.window)
        self.hotkey.toggled.connect(self.toggle)
        self.hotkey.start()
        self.history_path = ROOT/'console-history.json'
        try:
            history = json.loads(self.history_path.read_text(encoding='utf-8'))
            if isinstance(history, list):
                self.window.input.history = [x for x in history[-100:] if isinstance(x, str) and len(x) <= 2048]
                self.window.input.index = len(self.window.input.history)
        except (OSError, ValueError):
            pass
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(25)
        self.last_state = 0
        self.tick()

    def tick(self):
        now = time.monotonic()
        if now - self.game_check > 2:
            self.game_check = now
            game = game_window()
            if game and game != self.game:
                for widget in (self.button, self.window):
                    user.SetWindowLongPtrW(W.HWND(int(widget.winId())), -8, game[0])
            self.game = game
        if now - self.last_state > .15:
            self.last_state = now
            try:
                path = ROOT/'bridge-state.json'
                self.data = json.loads(path.read_text(encoding='utf-8'))
                self.online = time.time() - path.stat().st_mtime < 3 and self.data.get('isaacConnected', False)
            except (OSError, ValueError):
                self.online = False
        if not self.game or not self.online:
            self.button.hide()
            self.window.hide()
            return
        handle, pid = self.game
        foreground = window_pid(user.GetForegroundWindow())
        here = foreground in (pid, os.getpid())
        if REQUEST.exists():
            REQUEST.unlink(missing_ok=True)
            self.open()
        if not here or user.IsIconic(handle):
            self.button.hide()
            self.window.hide()
            return
        rect = W.RECT()
        origin = W.POINT()
        user.GetClientRect(handle, C.byref(rect))
        user.ClientToScreen(handle, C.byref(origin))
        ratio = self.button.devicePixelRatioF()
        left, top = round(origin.x/ratio), round(origin.y/ratio)
        width, height = round(rect.right/ratio), round(rect.bottom/ratio)
        self.button.setGeometry(left+20, top+round(250/ratio), 180, 32)
        self.button.hide()
        if self.opened:
            panel_top = round(310/ratio)
            w, h = min(800, max(320, width-40)), min(490, max(250, height-panel_top-16))
            self.window.setGeometry(left+20, top+panel_top, w, h)
            self.window.show()
            state = self.data.get('state', {})
            ready = not state.get('active') or state.get('paused', False)
            busy = self.process and self.process.state() != QProcess.NotRunning
            self.window.execute.setEnabled(bool(ready and not busy))
            self.window.refresh_button.setEnabled(not busy)
            self.window.resume.setEnabled(bool(state.get('active') and state.get('paused') and not busy and not resume_block_reason(self.data)))
            if not busy:
                self.window.status.setText('作战已暂停 · 关闭后保持暂停，可点“关闭并继续作战”返回。' if state.get('active') and ready else
                    ('正在暂停作战，暂停后可执行指令……' if not ready else '已连接以撒 · 回车执行指令'))

    @Slot()
    def toggle(self):
        self.close(False) if self.opened else self.open()

    def open(self):
        print('Console opened', flush=True)
        self.hotkey.grant_foreground()
        self.window.input.index = len(self.window.input.history)
        self.window.input.draft = self.window.input.text()
        self.opened = True
        state = self.data.get('state', {})
        self.pause_epoch = state.get('epoch')
        if state.get('active') and not state.get('paused'):
            pause(True)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.window.input.setFocus()
        if not self.window.output.toPlainText():
            self.evaluate(None)

    def close(self, resume=False):
        print('Console closed', flush=True)
        # The closing F2 may still be physically held when focus returns to AK.
        # Suppress its native edge until release, before returning foreground.
        self.hotkey.suppress_until_release()
        if resume:
            state = self.data.get('state', {})
            reason = resume_block_reason(self.data)
            if reason or state.get('epoch') != self.pause_epoch:
                self.window.append(reason or '关卡已经变化，请在方舟窗口确认后继续作战。')
                return
            pause(False)
        self.opened = False
        self.window.hide()
        if self.game:
            user.SetForegroundWindow(self.game[0])

    def execute(self):
        if not self.window.execute.isEnabled():
            return
        command = self.window.input.text().strip()
        if not command:
            return
        self.evaluate(command)

    def evaluate(self, command):
        if self.process and self.process.state() != QProcess.NotRunning:
            return
        try:
            source = console_source(command)
        except ValueError as error:
            self.window.append(str(error))
            return
        if command is not None:
            self.window.append('> '+command)
            self.window.input.remember(command)
            self.window.input.clear()
            try:
                temporary = self.history_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(self.window.input.history, ensure_ascii=False), encoding='utf-8')
                temporary.replace(self.history_path)
            except OSError:
                pass
        self.pending_command = command
        self.process = QProcess()
        self.process.setProgram(str(PYTHON))
        self.process.setArguments(['-X', 'utf8', str(ROOT/'tools/isaac_eval.py'), source])
        self.process.finished.connect(self.done)
        self.process.errorOccurred.connect(self.failed)
        self.window.status.setText('正在读取控制台……' if command is None else '正在执行……')
        self.window.execute.setEnabled(False)
        self.process.start()

    def failed(self, error):
        if self.process.error() == QProcess.FailedToStart:
            self.window.append('控制台连接程序未启动，请检查联动环境。')

    def done(self, code, status):
        try:
            if code:
                raise RuntimeError('以撒控制台连接失败，请确认测试副本和联动正在运行。')
            result = decode_response(bytes(self.process.readAllStandardOutput()).decode('utf-8'))
            if self.pending_command is None:
                lines = result.get('lines', [])
                if isinstance(lines, list):
                    self.window.output.setPlainText('\n'.join(str(line) for line in lines))
                    self.window.output.moveCursor(QTextCursor.End)
                if not self.window.input.history:
                    commands = result.get('commands', [])
                    if isinstance(commands, list):
                        self.window.input.history = [str(c) for c in commands][-100:]
                        self.window.input.index = len(self.window.input.history)
            else:
                self.window.append(result.get('output') or ('执行完成。' if result.get('ok') else '指令执行失败。'))
                (ROOT/'console-last-result.json').write_text(json.dumps({
                    'command':self.pending_command, 'result':result,
                    'finishedAt':time.time(), 'pid':os.getpid()}, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            self.window.append(str(error))
        self.window.input.setFocus()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(ROOT/'console-overlay.lock'))
    if not lock.tryLock(0):
        REQUEST.touch()
        return 0
    controller = ConsoleOverlay()
    if '--show' in sys.argv:
        REQUEST.touch()
    try:
        return app.exec()
    finally:
        controller.hotkey.requestInterruption()
        controller.hotkey.wait(3000)


if __name__ == '__main__':
    sys.exit(main())
