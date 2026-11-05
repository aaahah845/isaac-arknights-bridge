import ctypes as C,time,sys
from ctypes import wintypes as W
from pathlib import Path
import mss,mss.tools
from PIL import Image
ROOT=Path(__file__).resolve().parent.parent
pid=int((ROOT/'isaac.pid').read_text())
u=C.windll.user32;u.SetProcessDPIAware()
u.GetForegroundWindow.restype=W.HWND
u.ShowWindowAsync.argtypes=[W.HWND,C.c_int];u.SetForegroundWindow.argtypes=[W.HWND]
u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
u.GetClientRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
u.ClientToScreen.argtypes=[W.HWND,C.POINTER(W.POINT)]
windows=[]
@C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
def cb(h,p):
    found=W.DWORD();u.GetWindowThreadProcessId(h,C.byref(found))
    if found.value==pid and u.IsWindowVisible(h):
        name=C.create_unicode_buffer(128);u.GetClassNameW(h,name,128)
        if name.value=='GLFW30':windows.append(h)
    return True
u.EnumWindows(cb,0)
if not windows:raise RuntimeError('Isaac window not found')
def area(h):
    r=W.RECT();u.GetClientRect(h,C.byref(r));return r.right*r.bottom
h=max(windows,key=area);u.ShowWindowAsync(h,9);u.SetForegroundWindow(h)
time.sleep(.2)
found=W.DWORD();u.GetWindowThreadProcessId(u.GetForegroundWindow(),C.byref(found))
if found.value!=pid:raise RuntimeError('Isaac did not get focus')
import frida
session=frida.get_device_manager().add_remote_device('127.0.0.1:27043').attach('Gadget')
agent=session.create_script(r'''
if(Process.mainModule.path.toLowerCase()!=='d:\\isaacarknights-codex\\client\\repentogon\\isaac-ng.exe')throw Error('Unexpected game');
const u=Process.getModuleByName('user32.dll');
const emit=new NativeFunction(u.getExportByName('keybd_event'),'void',['uint8','uint8','uint','size_t']);
const scan=new NativeFunction(u.getExportByName('MapVirtualKeyW'),'uint',['uint','uint']);
const post=new NativeFunction(u.getExportByName('PostMessageW'),'bool',['pointer','uint','size_t','size_t']);
const window=ptr('__WINDOW__');
rpc.exports.key=(code,down)=>{const s=scan(code,0);emit(code,s,down?0:2,0);post(window,down?0x100:0x101,code,(1|(s<<16)|(down?0:0xc0000000))>>>0);};
rpc.exports.text=text=>{for(let i=0;i<text.length;i++)post(window,0x102,text.charCodeAt(i),1);};
rpc.exports.close=()=>post(window,0x10,0,0);
'''.replace('__WINDOW__',hex(h)));agent.load()
def emit(k,down):agent.exports_sync.key(k,down)
def key(k,d=.07):
    emit(k,True)
    try:time.sleep(d)
    finally:emit(k,False)
action=sys.argv[1]
if action=='close':agent.exports_sync.close()
elif action=='key':
    for code in sys.argv[2:]:key(int(code,0));time.sleep(.2)
elif action=='hold':key(int(sys.argv[2],0),float(sys.argv[3]))
elif action=='console':
    key(0xc0);time.sleep(.15)
    agent.exports_sync.text(sys.argv[2])
    time.sleep(.1)
    key(13);key(0xc0)
elif action=='capture':
    r=W.RECT();p=W.POINT();u.GetClientRect(h,C.byref(r));u.ClientToScreen(h,C.byref(p))
    with mss.MSS() as cap:
        shot=cap.grab({'left':p.x,'top':p.y,'width':r.right,'height':r.bottom})
        out=ROOT/'isaac-screen.png';mss.tools.to_png(shot.rgb,shot.size,output=str(out))
    im=Image.open(out);im.thumbnail((1100,750));im.save(ROOT/'isaac-small.png')
    print({'pid':pid,'width':r.right,'height':r.bottom})
session.detach()
