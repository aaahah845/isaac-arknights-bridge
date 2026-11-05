"""Build a portable Windows release, with no game binaries or user profiles.

Usage: python build_release.py --workspace PATH --output PATH
Build prerequisites: Python 3.14 x64, dependencies in work/ark-venv,
the bridge source in work/isaac-arknights, official RGON launcher + source.
"""
import argparse,hashlib,json,os,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path

def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--launcher',type=Path,required=True);parser.add_argument('--arknights',type=Path,required=True);parser.add_argument('--isaac',type=Path,required=True)
    args=parser.parse_args();workspace=args.workspace.resolve();out=args.output.resolve();here=Path(__file__).resolve().parent
    if out.exists():raise RuntimeError('Build output must be a new directory')
    out.mkdir(parents=True);print('Building '+str(out),flush=True)
    for p in here.iterdir():
        if p.suffix in ('.py','.js'):copy(p,out/'setup'/p.name)
    core=workspace/'work/isaac-arknights';templates=out/'payload/templates'
    names=['assets.py','motion.py','rendering.py','placement.py','textures.py','transport.py','bridge_host.py','overlay.py','overlay_gpu.py','gpu-overlay.flag','control.py','console_commands.py','console_overlay.py','hud.py','hud-font.json']
    for name in names:copy(core/name,templates/'work/isaac-arknights'/name)
    tools=['probe.js','live.js','enemy_capture.js','status.js','graphics.js','isaac_background.js','isaac_audio.js','isaac_audio.py','isaac_eval.py','isaac_ui.py','isaac_isolation.js']
    for name in tools:copy(core/'tools'/name,templates/'work/isaac-arknights/tools'/name)
    shutil.copytree(core/'mod',templates/'work/isaac-arknights/mod',ignore=shutil.ignore_patterns('__pycache__'))
    copy(here/'isaac_boot.py',templates/'work/isaac-arknights/tools/isaac_boot.py')
    copy(here/'attach_pc.py',templates/'work/attach_pc.py')
    for name in ('pc_windows.js','restore_pc.py','stop_pc.ps1'):copy(workspace/'work'/name,templates/'work'/name)
    copy(workspace/'outputs/ArknightsLocal/control.py',templates/'outputs/ArknightsLocal/control.py')
    # Convert a legacy message without changing its control flow.
    p=templates/'outputs/ArknightsLocal/control.py';s=p.read_text(encoding='utf-8').replace('找不到 D 盘的 PC 测试副本，请勿移动或删除它。','找不到方舟联动副本，请检查安装位置。').replace('Windows 如请求管理员许可，请核对启动的是 D 盘测试副本。','Windows 如请求管理员许可，请核对启动的是联动副本。');p.write_text(s,encoding='utf-8')
    # Workers are scoped to this release, not a similarly named other install.
    p=templates/'work/isaac-arknights/control.py';s=p.read_text(encoding='utf-8').replace(" -or $_.CommandLine.Replace('/','\\\\').Contains($s)",'')
    a=s.index('    # Also reload a previously stopped mod');b=s.index("    launch('bridge_host.py')",a)
    s=s[:a]+'''    # A fresh game may still be playing its intro or be at the title screen.
    # The installed mod loads normally when a run starts; never require a Lua
    # game-thread callback before the user has opened a run.
    if fresh_state():
        try:
            lua('if ArkIsaacBridge then ArkIsaacBridge.stopped=false end;ImGui.Hide();return "loaded"')
        except RuntimeError:pass
'''+s[b:];p.write_text(s,encoding='utf-8')
    gadgets=[(workspace/'work/OpenBachelorC/frida-gadget/frida-gadget-17.9.1-windows-x86_64.dll.xz','gadget-x64.dll.xz'),(core/'frida-gadget-17.9.1-windows-x86.dll.xz','gadget-x86.dll.xz')]
    for source,name in gadgets:copy(source,out/'payload'/name)
    # Unmodified official launcher only, not its patch cache or game resources.
    for name in ('REPENTOGONLauncher.exe','launcher-data.bin','steam_appid.txt'):copy(args.launcher/name,out/'components/repentogon'/name)
    for p in (args.launcher/'launcher-data').glob('*.dll'):copy(p,out/'components/repentogon/launcher-data'/p.name)
    launcher_source=core/'reference/launcher'
    copy(launcher_source/'LICENSE',out/'licenses/REPENTOGON-launcher-LICENSE.txt')
    launcher_archive=here/'build-cache/launcher-v0.4.9-beta-source.zip'
    launcher_archive.parent.mkdir(exist_ok=True)
    if not launcher_archive.exists():
        with urllib.request.urlopen('https://codeload.github.com/TeamREPENTOGON/Launcher/zip/refs/tags/v0.4.9-beta',timeout=60) as response,launcher_archive.open('wb') as f:shutil.copyfileobj(response,f)
    copy(launcher_archive,out/'licenses/REPENTOGON-launcher-source.zip')
    print('Preparing pinned download manifest',flush=True)
    commit='86099996610c3f3b5dc133bdf090e7c3848ee0fe';url='https://codeload.github.com/pfyy/OpenBachelorS/zip/'+commit
    cache=here/'build-cache';cache.mkdir(exist_ok=True);archive=cache/'server.zip'
    if not archive.exists():
        with urllib.request.urlopen(url,timeout=60) as response,archive.with_suffix('.download').open('wb') as target:shutil.copyfileobj(response,target)
        archive.with_suffix('.download').rename(archive)
    native=workspace/'work/OpenBachelorC/rel/native.js'
    native_url='https://raw.githubusercontent.com/pfyy/OpenBachelorC/9cf2bf92249ee008e28b74f8c54d3f0d55786737/rel/native.js'
    arkfiles={name:digest(args.arknights/name) for name in ('Arknights.exe','GameAssembly.dll','hgdownloadsdk.dll')}
    rgonfiles={name:digest(args.isaac/'Repentogon'/name) for name in ('isaac-ng.exe','libzhl.dll','zhlLoader.dll','zhlREPENTOGON.dll','Lua5.3.3r.dll')}
    data={'format':1,'release':'0.4.10-installer-preview.1','arknights':{'version':'2.7.91','resourceVersion':'26-10-29-15-35-15-96278206','files':arkfiles},'isaac':{'version':'Repentance+ J273','repentogon':'1.1.3','nativeFiles':rgonfiles},'components':{'server':{'url':url,'sha256':digest(archive),'commit':commit},'native':{'url':native_url,'sha256':digest(native),'commit':'9cf2bf92249ee008e28b74f8c54d3f0d55786737'}}}
    data['isaac']['baseExeSha256']='3bdfc8bae0dc7e334b76009d0ad45dfbb16ee5f00c06ffbc3a0094e34d44616b'
    data['isaac']['patchedFiles']={n:digest(args.isaac/'Repentogon'/n) for n in ('resources/packed/afterbirthp.a','resources/scripts/enums.lua','resources/scripts/json.lua','resources/scripts/main.lua')}
    data['components']['repentogon']={'url':'https://github.com/TeamREPENTOGON/REPENTOGON/releases/download/1.1.3/REPENTOGON.zip','sha256':'80062fc262b5007d7d363455ffadbe0d7f190da1eed9fd7f05460ee7ae55ef9c'}
    (out/'payload/manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');copy(out/'payload/manifest.json',here/'manifest.lock.json')
    print('Copying portable Python and installed dependencies',flush=True)
    runtime=out/'runtime';base=Path(sys.base_prefix)
    for p in base.iterdir():
        if p.is_file() and (p.suffix.lower() in ('.dll','.exe') or p.name=='LICENSE.txt'):copy(p,runtime/p.name)
    shutil.copytree(base/'DLLs',runtime/'DLLs',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pdb'))
    shutil.copytree(base/'Lib',runtime/'Lib',ignore=shutil.ignore_patterns('__pycache__','*.pyc','site-packages','test','tests','idlelib','ensurepip','tkinter','turtledemo'))
    packages=workspace/'work/ark-venv/Lib/site-packages'
    shutil.copytree(packages,runtime/'Lib/site-packages',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pth','direct_url.json','_editable*'))
    (runtime/'python314._pth').write_text('Lib\nDLLs\nLib/site-packages\n../setup\n../work\n../work/isaac-arknights\n../work/OpenBachelorS/src\nimport site\n',encoding='ascii')
    # Existing applications log UTF-8; do not depend on the system code page.
    (runtime/'Lib/site-packages/sitecustomize.py').write_text("import sys\nfor s in (sys.stdout,sys.stderr):\n if s is not None and hasattr(s,'reconfigure'):s.reconfigure(encoding='utf-8',errors='replace')\n",encoding='utf-8')
    csc=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    for mode,name in [('arknights','01-安装方舟联动.exe'),('isaac','02-安装以撒联动.exe'),('start','03-启动联动.exe')]:
        source=out/'setup'/('Entry-'+mode+'.cs');source.write_text((here/'Entry.cs').read_text(encoding='utf-8').replace('MODE_TOKEN',mode),encoding='utf-8-sig')
        subprocess.run([str(csc),'/nologo','/target:winexe','/reference:System.Windows.Forms.dll','/out:'+str(out/name),str(source)],check=True)
    for name in ('README.md','视频简介.txt','THIRD_PARTY_NOTICES.md'):copy(here/name,out/name)
    freeze=subprocess.run([sys.executable,'-m','pip','freeze'],capture_output=True,text=True,encoding='utf-8',check=True).stdout
    (out/'setup/requirements.lock.txt').write_text('\n'.join(line for line in freeze.splitlines() if ' @ file:' not in line and not line.startswith('-e '))+'\n',encoding='utf-8')
    print(json.dumps({'output':str(out),'files':sum(1 for p in out.rglob('*') if p.is_file()),'bytes':sum(p.stat().st_size for p in out.rglob('*') if p.is_file())}),flush=True)

if __name__=='__main__':main()
