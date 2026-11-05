"""Run the official REPENTOGON launcher for the private installed copy."""
import json
import os
import socket
import subprocess
import time
from pathlib import Path
import frida
from settings import ROOT,read_state,HIDDEN
from bootstrap_common import load_guard

state=read_state();info=state['games']['isaac'];dest=Path(info.get('runtimeDestination',info['destination']));game=dest/'client'
launcher=ROOT/'components/repentogon/REPENTOGONLauncher.exe'
config=dest/'launcher.ini'
environment=dict(os.environ,SteamAppId='250900',SteamGameId='250900')
process=subprocess.Popen([str(launcher),'--configuration-file='+str(config),'--isaac='+str(game/'isaac-ng.exe'),
                         '--skip-wizard','--skip-repentogon-update','--stealth-mode','--skip-unique','--luadebug'],
                        cwd=launcher.parent,env=environment,creationflags=HIDDEN)
device=frida.get_device_manager().add_remote_device('127.0.0.1:'+str(state['ports']['isaac']))
session=None
for _ in range(300):
    try:session=device.attach('Gadget');break
    except (frida.TransportError,frida.ServerNotRunningError):time.sleep(.2)
    if process.poll() is not None:raise RuntimeError('以撒未启动，请查看 REPENTOGON 启动日志。')
if session is None:raise RuntimeError('以撒测试副本连接超时。')
isolation=load_guard(session,'isaac');info=isolation.exports_sync.info()
(ROOT/'work/isaac-arknights/isaac.pid').write_text(str(info['pid']))
device.resume(info['pid'])
print('ISAAC_LOCAL_READY',flush=True)
try:
    while not isolation.is_destroyed:time.sleep(.5)
finally:session.detach()
