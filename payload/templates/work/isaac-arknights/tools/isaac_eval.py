"""Evaluate our development Lua on the isolated game's own Lua thread."""
import json,sys,time
from pathlib import Path
import frida
ROOT=Path(__file__).resolve().parent.parent
qa=len(sys.argv)>1 and sys.argv[1]=='--terrain-qa'
if qa:del sys.argv[1]
device=frida.get_device_manager().add_remote_device('127.0.0.1:27044' if qa else '127.0.0.1:27043')
session=device.attach('Gadget')
guard=session.create_script('rpc.exports.path=()=>Process.mainModule.path;');guard.load()
expected=Path(r'D:\IsaacArknights-Codex\terrain-qa\client\Repentogon\isaac-ng.exe') if qa else Path(r'D:\IsaacArknights-Codex\client\Repentogon\isaac-ng.exe')
assert Path(guard.exports_sync.path()).resolve()==expected.resolve()
guard.unload()
script=session.create_script(r'''
const m=Process.getModuleByName('Lua5.3.3r.dll');
function fn(n,r,a){return new NativeFunction(m.getExportByName(n),r,a);}
const gettop=fn('lua_gettop','int',['pointer']);const settop=fn('lua_settop','void',['pointer','int']);
const load=fn('luaL_loadstring','int',['pointer','pointer']);
const pcall=fn('lua_pcallk','int',['pointer','int','int','int','int','pointer']);
const string=fn('lua_tolstring','pointer',['pointer','int','pointer']);
let request=null,result=null,busy=false;
const hook=Interceptor.attach(m.getExportByName('lua_pcallk'),{
 onEnter(args){this.L=args[0];},onLeave(){if(busy||request===null)return;busy=true;const L=this.L,n=gettop(L),text=request;request=null;
 try{const rc=load(L,Memory.allocUtf8String(text));const status=rc||pcall(L,0,1,0,0,ptr(0));let p=string(L,-1,ptr(0));result={status,value:p.isNull()?null:p.readUtf8String()};}
 catch(e){result={error:String(e)};}finally{settop(L,n);busy=false;}
 }});
rpc.exports.run=(source)=>{request=source;};rpc.exports.result=()=>result;
''')
script.on('message',lambda m,d:print(m,file=sys.stderr));script.load()
source=Path(sys.argv[2]).read_text(encoding='utf-8') if sys.argv[1]=='file' else sys.argv[1]
script.exports_sync.run(source)
for _ in range(150):
    result=script.exports_sync.result()
    if result is not None:print(json.dumps(result,ensure_ascii=False));break
    time.sleep(.05)
else:raise RuntimeError('No Lua callback reached the development hook')
session.detach()
