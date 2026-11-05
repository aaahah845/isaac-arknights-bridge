// Only loaded into our child Isaac process before its entry point.
const cfg=__GUARD_CONFIG__;
if(Process.mainModule.path.toLowerCase()!==cfg.executable.toLowerCase())throw Error('Unexpected isolation target');
console.log('Installing profile isolation');
const keep=[];
function mapPath(p){
 p=p.replaceAll('/','\\');const lower=p.toLowerCase();
 for(const map of cfg.profiles){const offset=lower.startsWith('\\??\\')?4:0,root=map.source.toLowerCase();
 if(lower.substring(offset).startsWith(root)&&(lower.length===offset+root.length||lower[offset+root.length]==='\\'))
 return p.slice(0,offset)+map.target+p.slice(offset+root.length);}
 return null;
}
const kb=Process.getModuleByName('kernelbase.dll'),ps=Process.pointerSize;
function ntRedirect(attrs){
 const name=attrs.add(ps*2).readPointer();if(name.isNull())return attrs;
 const buf=name.add(ps===8?8:4).readPointer();const value=buf.readUtf16String(name.readU16()/2),p=mapPath(value);if(!p)return attrs;
 const ctx={};ctx.text=Memory.allocUtf16String(p);ctx.name=Memory.alloc(ps===8?16:8);ctx.name.writeU16(p.length*2);ctx.name.add(2).writeU16(p.length*2+2);ctx.name.add(ps===8?8:4).writePointer(ctx.text);
 ctx.attrs=Memory.alloc(ps===8?48:24);ctx.attrs.writeByteArray(attrs.readByteArray(ps===8?48:24));ctx.attrs.add(ps*2).writePointer(ctx.name);keep.push(ctx);return ctx.attrs;
}
// File IO is frequent during resource loading. Filter unrelated paths in native
// code so that only profile operations need to enter JavaScript.
const mapper=new NativeCallback(ntRedirect,'pointer',['pointer']);
const nativeFilter=new CModule(`
#include <gum/guminterceptor.h>
extern void * map_profile(void *attrs);
static void check(GumInvocationContext *ic, unsigned index) {
 void **attrs=(void**)gum_invocation_context_get_nth_argument(ic,index);
 if(!attrs || !attrs[2])return;
 unsigned short *name=(unsigned short*)attrs[2];
 unsigned len=name[0]/2;
 unsigned short *s=*(unsigned short**)((char*)name+${ps===8?8:4});
 if(!s)return;
 for(unsigned i=0;i+8<len;i++)if(((s[i]=='M'||s[i]=='m')&&(s[i+1]=='Y'||s[i+1]=='y')&&s[i+2]==' ')||((s[i]=='H'||s[i]=='h')&&(s[i+1]=='Y'||s[i+1]=='y')&&(s[i+2]=='P'||s[i+2]=='p'))){
   gum_invocation_context_replace_nth_argument(ic,index,map_profile(attrs));return;
 }
}
void file_enter(GumInvocationContext *ic){check(ic,2);}
void query_enter(GumInvocationContext *ic){check(ic,0);}
`,{map_profile:mapper});
console.log('Native profile filter ready');
for(const name of ['NtCreateFile','NtOpenFile','NtQueryAttributesFile','NtQueryFullAttributesFile']){
 Interceptor.attach(Process.getModuleByName('ntdll.dll').getExportByName(name),{onEnter:name.startsWith('NtQuery')?nativeFilter.query_enter:nativeFilter.file_enter});
}

for(const name of ['CreateDirectoryW','GetFileAttributesW','GetFileAttributesExW','FindFirstFileExW']){
 const address=kb.findExportByName(name);if(address)Interceptor.attach(address,{onEnter(args){
 try{const p=mapPath(args[0].readUtf16String());if(p!==null){this.path=Memory.allocUtf16String(p);args[0]=this.path;}}catch(e){}
 }});
}
rpc.exports.info=()=>({pid:Process.id,path:Process.mainModule.path,profiles:cfg.profiles});
