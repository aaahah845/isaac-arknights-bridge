"""Attach the copied PC client, isolate writes, then load the pinned adapter."""
import json
import time
from pathlib import Path
import frida
from settings import ROOT,read_state
from bootstrap_common import load_guard

state=read_state();game=Path(state['games']['arknights']['destination'])/'client/Arknights.exe'
device=frida.get_device_manager().add_remote_device('127.0.0.1:'+str(state['ports']['pc']))
session=None
for _ in range(300):
    try:session=device.attach('Gadget');break
    except frida.TransportError:time.sleep(.2)
    except frida.ServerNotRunningError:time.sleep(.2)
if session is None:raise RuntimeError('方舟测试副本连接超时。')
guard=session.create_script('rpc.exports.info=()=>({pid:Process.id,path:Process.mainModule.path})');guard.load()
target=guard.exports_sync.info();guard.unload()
if Path(target['path']).resolve()!=game.resolve():
    session.detach();raise RuntimeError('连接的不是安装器创建的方舟副本。')
isolation=load_guard(session,'arknights')
window_script=session.create_script((ROOT/'work/pc_windows.js').read_text(encoding='utf-8'));window_script.load()
native=session.create_script((ROOT/'work/components/native.js').read_text(encoding='utf-8'))
native.on('message',lambda message,data:print(message,flush=True));native.load()
for key,value in {'proxy_url':'http://127.0.0.1:'+str(state['ports']['server']),'no_proxy':False,'native_delay':2000}.items():
    native.post({'type':'conf','k':key,'v':value})
(ROOT/'work/pc-game.pid').write_text(str(target['pid']))
device.resume(target['pid'])
print('LOCAL_CLIENT_READY',flush=True)
try:
    while not native.is_destroyed:time.sleep(.5)
finally:session.detach()
