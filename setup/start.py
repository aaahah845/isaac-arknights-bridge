"""Validate an installed release and start the existing bridge lifecycle."""
import json,os,socket,subprocess,sys,traceback
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QLockFile,QTimer
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel,QPushButton,QMessageBox
from settings import ROOT,read_state,python,HIDDEN
from installer_backend import check_hash

def preflight():
    state=read_state()
    if not all(k in state['games'] for k in ('arknights','isaac')):raise RuntimeError('请先分别完成“01-安装方舟联动”和“02-安装以撒联动”。')
    for game,info in state['games'].items():
        dest=Path(info['destination'])
        if not (dest/'.isaac-arknights-install.json').is_file():raise RuntimeError('找不到已安装的联动副本：'+str(dest))
    # Check identity before reusing a listening Gadget. Never attach another game.
    import frida
    for key,game,relative in [('pc','arknights','client/Arknights.exe'),('isaac','isaac','client/Repentogon/isaac-ng.exe')]:
        number=state['ports'][key]
        try:
            with socket.create_connection(('127.0.0.1',number),timeout=.2):pass
        except OSError:continue
        try:
            device=frida.get_device_manager().add_remote_device('127.0.0.1:'+str(number));session=device.attach('Gadget')
            script=session.create_script('rpc.exports.path=()=>Process.mainModule.path;');script.load();actual=Path(script.exports_sync.path()).resolve();session.detach()
            if actual!= (Path(state['games'][game]['destination'])/relative).resolve():raise ValueError('other client')
        except Exception:raise RuntimeError('端口 '+str(number)+' 被其他程序或旧版联动占用，请先退出它。')
    # The copied program is the pinned version; later official-client updates do
    # not invalidate or trigger patches against the separate copied program.
    number=state['ports']['server']
    try:
        with socket.create_connection(('127.0.0.1',number),timeout=.2):pass
    except OSError:pass
    else:
        import psutil
        try:
            pid=int((ROOT/'work/server.pid').read_text());process=psutil.Process(pid)
            if Path(process.exe()).resolve()!=python().resolve() or 'openbachelors.app:app' not in process.cmdline():raise ValueError('other server')
        except Exception:raise RuntimeError('端口 '+str(number)+' 被其他本地服务占用，请先退出旧服务。')
    steam=subprocess.run(['tasklist.exe','/FI','IMAGENAME eq steam.exe','/FO','CSV','/NH'],capture_output=True,creationflags=HIDDEN)
    if b'steam.exe' not in steam.stdout.lower():raise RuntimeError('请先打开 Steam 并登录拥有以撒的账号，再启动联动。')

class Job(QThread):
    done=Signal(str);failed=Signal(str)
    def run(self):
        try:
            preflight()
            process=subprocess.run([str(python()),'-u',str(ROOT/'work/isaac-arknights/control.py'),'start'],cwd=ROOT/'work/isaac-arknights',capture_output=True,creationflags=HIDDEN,text=True,encoding='utf-8',errors='replace',timeout=240)
            with (ROOT/'launch.log').open('a',encoding='utf-8') as out:out.write(process.stdout+'\n'+process.stderr+'\n')
            if process.returncode:raise RuntimeError('启动未完成，请查看 launch.log 和 work 下的日志。\n'+process.stderr[-1000:])
            self.done.emit('联动已启动。\n以撒新开一局，方舟进入关卡即可。\nWASD 移动，方向键射击，空格使用主动，F2 打开控制台。')
        except Exception as error:
            with (ROOT/'launch.log').open('a',encoding='utf-8') as out:out.write(traceback.format_exc()+'\n')
            self.failed.emit(str(error))

class Start(QWidget):
    def __init__(self):
        super().__init__();self.job=None;self.setWindowTitle('以撒 × 明日方舟');self.resize(500,230)
        box=QVBoxLayout(self);self.label=QLabel('启动两个联动客户端，连接本地服务。\n请先保持 Steam 登录。');self.label.setWordWrap(True);box.addWidget(self.label)
        self.button=QPushButton('启动 / 连接联动');self.button.setMinimumHeight(42);self.button.clicked.connect(self.begin);box.addWidget(self.button)
    def begin(self):
        self.button.setEnabled(False);self.label.setText('正在启动，请等待游戏窗口出现……');self.job=Job();self.job.done.connect(self.done);self.job.failed.connect(self.fail);self.job.start()
    def done(self,message):self.label.setText(message);self.button.setText('已启动');self.button.setEnabled(True)
    def fail(self,message):self.label.setText('启动未完成。');self.button.setEnabled(True);QMessageBox.warning(self,'启动未完成',message)
    def closeEvent(self,event):
        if self.job and self.job.isRunning():event.ignore()
        else:event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv);lock=QLockFile(str(ROOT/'start.lock'))
    if not lock.tryLock(0):sys.exit(0)
    window=Start();window.show();QTimer.singleShot(150,window.begin);sys.exit(app.exec())
