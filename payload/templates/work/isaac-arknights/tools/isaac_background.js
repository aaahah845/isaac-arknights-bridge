if(Process.mainModule.path.toLowerCase()!=='d:\\isaacarknights-codex\\client\\repentogon\\isaac-ng.exe')throw Error('Unexpected test process');
const u=Process.getModuleByName('user32.dll');
const enumerate=new NativeFunction(u.getExportByName('EnumWindows'),'bool',['pointer','pointer']);
const getPid=new NativeFunction(u.getExportByName('GetWindowThreadProcessId'),'uint',['pointer','pointer']);
const visible=new NativeFunction(u.getExportByName('IsWindowVisible'),'bool',['pointer']);
const getClass=new NativeFunction(u.getExportByName('GetClassNameW'),'int',['pointer','pointer','int']);
let own=ptr(0),enabled=false;
const ownAddress=Memory.alloc(Process.pointerSize);ownAddress.writePointer(ptr(0));
const activeAddress=Memory.alloc(4);activeAddress.writeU32(0);
const callback=new NativeCallback((h,p)=>{const id=Memory.alloc(4);getPid(h,id);if(id.readU32()===Process.id&&visible(h)){const cls=Memory.alloc(256);getClass(h,cls,128);if(cls.readUtf16String()==='GLFW30')own=h;}return 1;},'int',['pointer','pointer']);
enumerate(callback,ptr(0));
function stop(){enabled=false;activeAddress.writeU32(0);}
// Window queries also run on graphics-driver threads. Keep those callbacks in
// native code so they cannot wait for the JavaScript runtime during rendering.
const focusFilter=new CModule(`
#include <gum/guminterceptor.h>
extern void *own_window;
extern unsigned int bridge_active;
void leave(GumInvocationContext *ic) {
 if(bridge_active && own_window)gum_invocation_context_replace_return_value(ic,own_window);
}
`,{own_window:ownAddress,bridge_active:activeAddress});
for(const name of ['GetActiveWindow','GetFocus','GetForegroundWindow'])Interceptor.attach(u.getExportByName(name),{onLeave:focusFilter.leave});
const restore=new NativeFunction(u.getExportByName('ShowWindowAsync'),'bool',['pointer','int']);
const post=new NativeFunction(u.getExportByName('PostMessageW'),'bool',['pointer','uint','pointer','pointer']);
rpc.exports.background=(value)=>{if(own.isNull())enumerate(callback,ptr(0));ownAddress.writePointer(own);enabled=value;activeAddress.writeU32(value?1:0);if(value&&!own.isNull()){restore(own,4);post(own,6,ptr(1),ptr(0));post(own,7,ptr(0),ptr(0));}};
rpc.exports.path=()=>Process.mainModule.path;
rpc.exports.info=()=>{if(own.isNull())enumerate(callback,ptr(0));ownAddress.writePointer(own);return {window:own.toString(),enabled,pid:Process.id};};
rpc.exports.stop=stop;
