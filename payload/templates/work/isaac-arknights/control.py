"""Lifecycle for this machine's two independent test copies."""
import base64,json,socket,subprocess,sys,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent
WORK=ROOT.parent
PYTHON=WORK/'ark-venv/Scripts/python.exe'
HIDDEN=subprocess.CREATE_NO_WINDOW
def shell(code):
    encoded=base64.b64encode(code.encode('utf-16-le')).decode('ascii')
    return subprocess.run(['powershell.exe','-NoProfile','-EncodedCommand',encoded],capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=HIDDEN,timeout=30)
def workers(name):
    marker=str(ROOT/name).replace("'","''")
    # Exact file paths distinguish these processes from other user projects.
    suffix=('isaac-arknights\\'+name.replace('/','\\')).replace("'","''")
    code="$m='"+marker+"';$s='"+suffix+"'; @(Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | Where-Object {$_.CommandLine -and ($_.CommandLine.Replace('/','\\').Contains($m))} | ForEach-Object {$_.ProcessId}) | ConvertTo-Json -Compress"
    data=shell(code).stdout.strip()
    if not data:return []
    result=json.loads(data);return result if isinstance(result,list) else [result]
def port(number):
    try:
        with socket.create_connection(('127.0.0.1',number),timeout=.3):return True
    except OSError:return False
def fresh_state():
    p=ROOT/'bridge-state.json'
    try:return time.time()-p.stat().st_mtime<2
    except OSError:return False
def launch(name):
    if workers(name):return
    with (ROOT/(name+'.log')).open('a',encoding='utf-8') as out:
        subprocess.Popen([str(PYTHON),'-u',str(ROOT/name)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,creationflags=HIDDEN)
def lua(source):
    process=subprocess.run([str(PYTHON),str(ROOT/'tools/isaac_eval.py'),source],capture_output=True,text=True,encoding='utf-8',creationflags=HIDDEN,timeout=15)
    if process.returncode:raise RuntimeError('以撒测试窗口连接失败。请先打开测试游戏。')
    result=json.loads(process.stdout)
    if result.get('status')!=0:raise RuntimeError(result.get('value','以撒操作未完成。'))
    return result
def start():
    (ROOT/'stop.flag').unlink(missing_ok=True)
    shutil.copytree(ROOT/'mod',Path(r'D:\IsaacArknights-Codex\client\mods\isaac_arknights_bridge'),dirs_exist_ok=True)
    if not port(27042):
        core=WORK.parent/'outputs/ArknightsLocal/control.py'
        p=subprocess.run([str(PYTHON),str(core),'start'],cwd=core.parent,creationflags=HIDDEN,capture_output=True,timeout=150)
        if p.returncode:raise RuntimeError('方舟本地测试服未启动，请先打开原有的 PC 测试服入口。')
    if not port(27043):
        launch('tools/isaac_boot.py')
        for _ in range(600):
            if port(27043):break
            time.sleep(.2)
        else:raise RuntimeError('REPENTOGON 测试副本启动超时，请查看启动日志。')
    # The installed mod starts normally after the user opens a run.
    if fresh_state():
        try:lua('if ArkIsaacBridge then ArkIsaacBridge.stopped=false end;ImGui.Hide();return "loaded"')
        except RuntimeError:pass
    launch('bridge_host.py')
    launch('overlay.py')
    launch('tools/isaac_audio.py')
    launch('console_overlay.py')
    return '联动已启动。以撒进入一局游戏后，在方舟测试服进入关卡即可。'
def stop():
    (ROOT/'stop.flag').touch()
    deadline=time.monotonic()+4
    while fresh_state() and time.monotonic()<deadline:time.sleep(.1)
    if port(27043):
        lua('local B=ArkIsaacBridge;if B then B.stopped=true;B.cleanup();B.bridgePaused=false;if B.udp then B.udp:close();B.udp=nil end end;return "stopped"')
    for pid in workers('overlay.py') + workers('tools/isaac_audio.py') + workers('console_overlay.py'):
        subprocess.run(['taskkill.exe','/PID',str(pid),'/F'],capture_output=True,creationflags=HIDDEN)
    return '联动已停止，方舟保持暂停。两个测试游戏可分别继续使用。'
def restart():
    lua('if ArkIsaacBridge then ArkIsaacBridge.restarting=true end;Isaac.ExecuteCommand("restart");return "restarted"')
    return '以撒测试角色已重新开始；方舟仍保留当前关卡。'

def console():
    launch('console_overlay.py')
    subprocess.run([str(PYTHON),str(WORK/'restore_pc.py')],capture_output=True,creationflags=HIDDEN,timeout=12)
    (ROOT/'console-open.request').touch()
    return '已请求打开方舟窗口上的以撒控制台，也可按 F2 打开。'
def resume_block_reason(data):
    if not data.get('state',{}).get('active'):return None
    if not data.get('isaacConnected'):return '以撒连接已断开，等待重新连接后再继续。'
    isaac=data.get('isaac',{})
    if isaac.get('player',{}).get('dead'):return '以撒已死亡：请先点击“重新开始以撒角色”，再继续作战。'
    if isaac.get('menuPaused'):return '请先关闭以撒的暂停菜单，再继续作战。'
    return None

def pause(value):
    if not value:
        try:
            if not fresh_state():return '联动未运行，请先启动／连接联动。'
            reason=resume_block_reason(json.loads((ROOT/'bridge-state.json').read_text(encoding='utf-8')))
            if reason:return reason
        except (OSError,ValueError):return '正在读取联动状态，请稍后再继续。'
    path=ROOT/'command.json';temp=ROOT/'command.tmp.json'
    temp.write_text(json.dumps({'type':'pause','value':value}),encoding='utf-8');temp.replace(path)
    return '已暂停。' if value else '已请求继续。'
if __name__=='__main__':
    action=sys.argv[1] if len(sys.argv)>1 else 'start'
    print({'start':start,'stop':stop,'restart':restart,'console':console,'pause':lambda:pause(True),'resume':lambda:pause(False)}[action]())
