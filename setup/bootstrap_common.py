import ctypes as C
from ctypes import wintypes as W
import json
import os
import time
from pathlib import Path
from settings import ROOT,read_state


def documents():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
            return Path(os.path.expandvars(winreg.QueryValueEx(key,'Personal')[0]))
    except OSError:return Path.home()/'Documents'


def aliases(path):
    path=str(Path(path).resolve()).rstrip('\\')
    result=[path]
    if len(path)>2 and path[1]==':':
        buffer=C.create_unicode_buffer(32768)
        if C.windll.kernel32.QueryDosDeviceW(path[:2],buffer,len(buffer)):
            result.append(buffer.value+path[2:])
    return result


def guard_config(game):
    state=read_state();info=state['games'][game];dest=Path(info.get('runtimeDestination',info['destination']))
    exe=dest/'client/Arknights.exe' if game=='arknights' else dest/'client/Repentogon/isaac-ng.exe'
    profiles=[]
    if game=='arknights':
        source=Path(os.environ['USERPROFILE'])/'AppData/LocalLow/Hypergryph'
        for path in aliases(source):profiles.append({'source':path,'target':str(dest/'userdata/Hypergryph')})
    else:
        roots={documents()/'My Games',Path.home()/'Documents/My Games'}
        for source in roots:
            for path in aliases(source):profiles.append({'source':path,'target':str(dest/'profile')})
    protected=[]
    for entry in info.get('shared',[]):
        protected.extend(aliases(entry['source']));protected.extend(aliases(entry['mount']))
    return {'executable':str(exe),'profiles':profiles,'protected':list(dict.fromkeys(protected)),'hideWorkshop':game=='isaac'}


def load_guard(session,game):
    config=guard_config(game)
    source=(ROOT/'setup/guard.js').read_text(encoding='utf-8').replace('__GUARD_CONFIG__',json.dumps(config,ensure_ascii=False))
    if game=='isaac':
        old=(ROOT/'work/isaac-arknights/tools/isaac_isolation.js').read_text(encoding='utf-8')
        source+='\n{\n'+old[old.index('const seen=new Set();'):old.index('rpc.exports.info=')]+'\n}'
    else:
        source+=r'''
const adv=Process.getModuleByName('advapi32.dll');
for(const name of ['RegOpenKeyExW','RegCreateKeyExW','RegGetValueW','RegSetKeyValueW']){
 const address=adv.findExportByName(name);if(!address)continue;
 Interceptor.attach(address,{onEnter(args){try{const old=args[1].readUtf16String(),prefix='Software\\Hypergryph\\Arknights';
 if(old.toLowerCase().startsWith(prefix.toLowerCase())){this.name=Memory.allocUtf16String('Software\\IsaacArknightsBridge\\Arknights'+old.substring(prefix.length));args[1]=this.name;}}catch(e){}}});}
'''
    script=session.create_script(source)
    script.on('message',lambda message,data:print(message,flush=True) if message.get('type')=='error' else None)
    script.load()
    print('Filesystem isolation:',json.dumps(script.exports_sync.info(),ensure_ascii=False),flush=True)
    return script
