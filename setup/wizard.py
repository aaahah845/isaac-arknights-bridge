"""Two separately named entry points share this installation wizard."""
import os,sys,traceback
from pathlib import Path
from PySide6.QtCore import QThread,Signal,QLockFile
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QFileDialog,QProgressBar,QPlainTextEdit,QMessageBox
from settings import ROOT,read_state
from installer_backend import install

class Job(QThread):
    progress=Signal(str,int);finished_ok=Signal();failed=Signal(str)
    def __init__(self,game,source,target):super().__init__();self.args=(game,source,target)
    def run(self):
        try:install(*self.args,report=self.progress.emit);self.finished_ok.emit()
        except Exception as error:
            with (ROOT/'installation.log').open('a',encoding='utf-8') as out:out.write(traceback.format_exc()+'\n')
            self.failed.emit(str(error))

def detect_isaac():
    import winreg,re
    roots=[]
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam') as key:roots.append(Path(winreg.QueryValueEx(key,'SteamPath')[0]))
    except OSError:pass
    for root in list(roots):
        config=root/'steamapps/libraryfolders.vdf'
        if config.is_file():roots.extend(Path(p.replace('\\\\','\\')) for p in re.findall(r'"path"\s+"([^"]+)"',config.read_text(encoding='utf-8')))
    return next((str(root/'steamapps/common/The Binding of Isaac Rebirth/isaac-ng.exe') for root in roots if (root/'steamapps/common/The Binding of Isaac Rebirth/isaac-ng.exe').is_file()),'')

class Wizard(QWidget):
    def __init__(self,game):
        super().__init__();self.game=game;self.job=None
        name='明日方舟' if game=='arknights' else '以撒';self.setWindowTitle('安装'+name+'联动组件');self.resize(680,470)
        box=QVBoxLayout(self);title=QLabel('安装'+name+'联动组件');title.setStyleSheet('font-size:24px;font-weight:600;margin:8px 0');box.addWidget(title)
        text='选择已完整下载的国服 PC 客户端（2.7.91）。' if game=='arknights' else '选择 Steam 以撒根目录的 isaac-ng.exe（含忏悔+）。将自动安装所需 REPENTOGON。'
        intro=QLabel(text+'\n安装器会创建独立副本和新存档。');intro.setWordWrap(True);box.addWidget(intro)
        self.source=QLineEdit(detect_isaac() if game=='isaac' else '');self.target=QLineEdit(str(ROOT/'games'/('Arknights' if game=='arknights' else 'Isaac')))
        for label,edit,callback in [('官方游戏程序',self.source,self.choose_source),('联动版安装位置（新目录）',self.target,self.choose_target)]:
            box.addWidget(QLabel(label));row=QHBoxLayout();row.addWidget(edit);button=QPushButton('选择…');button.clicked.connect(callback);row.addWidget(button);box.addLayout(row)
        self.note=QLabel('首次安装需联网下载组件。请为客户端副本留足磁盘空间。');self.note.setWordWrap(True);box.addWidget(self.note)
        self.bar=QProgressBar();box.addWidget(self.bar);self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(120);box.addWidget(self.log)
        self.button=QPushButton('开始安装');self.button.setMinimumHeight(40);self.button.clicked.connect(self.begin);box.addWidget(self.button)
        info=read_state()['games'].get(game)
        if info:self.button.setEnabled(False);self.note.setText('已安装到 '+info['destination']+'。请打开“03-启动联动”。')
    def choose_source(self):
        expected='Arknights.exe' if self.game=='arknights' else 'isaac-ng.exe'
        value,_=QFileDialog.getOpenFileName(self,'选择官方游戏程序',self.source.text(),'游戏程序 ('+expected+')')
        if value:self.source.setText(value)
    def choose_target(self):
        value=QFileDialog.getExistingDirectory(self,'选择保存联动副本的父目录',str(Path(self.target.text()).parent))
        if value:self.target.setText(str(Path(value)/('ArknightsBridge' if self.game=='arknights' else 'IsaacBridge')))
    def begin(self):
        self.button.setEnabled(False);self.source.setEnabled(False);self.target.setEnabled(False)
        self.job=Job(self.game,self.source.text(),self.target.text());self.job.progress.connect(self.progress);self.job.finished_ok.connect(self.success);self.job.failed.connect(self.fail);self.job.start()
    def progress(self,message,percent):
        self.bar.setValue(percent);self.note.setText(message)
        # File copies emit many updates; keep the log useful and bounded.
        if not message.startswith('复制独立客户端') or percent//10!=getattr(self,'last_copy_decile',-1):
            if getattr(self,'last_message',None)!=message:self.log.appendPlainText(message);self.last_message=message
        if message.startswith('复制独立客户端'):self.last_copy_decile=percent//10
    def success(self):self.note.setText('安装完成。两端安装好后打开“03-启动联动”。');self.button.setText('已完成');self.bar.setValue(100)
    def fail(self,message):
        self.log.appendPlainText(message);self.note.setText('安装未完成，详细信息见 installation.log。');self.button.setEnabled(True);self.source.setEnabled(True);self.target.setEnabled(True)
        QMessageBox.warning(self,'安装未完成',message)
    def closeEvent(self,event):
        if self.job and self.job.isRunning():
            QMessageBox.information(self,'安装进行中','请等待当前安装结束；如弹出了 REPENTOGON 安装器，请先在其中完成或取消安装。');event.ignore()
        else:event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv);game=sys.argv[1] if len(sys.argv)>1 else 'arknights'
    lock=QLockFile(str(ROOT/('wizard-'+game+'.lock')))
    if not lock.tryLock(0):sys.exit(0)
    window=Wizard(game);window.show();sys.exit(app.exec())
