// Only loaded into our child Isaac process before its entry point.
const cfg=__CONFIG__;
console.log('Installing profile isolation');
const keep=[];
function mapPath(p){
 p=p.replaceAll('/','\\');const lower=p.toLowerCase();
 for(const root of cfg.roots){const index=lower.indexOf(root.toLowerCase());if(index>=0)return p.slice(0,index)+cfg.profile+p.slice(index+root.length);}
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
 for(unsigned i=0;i+8<len;i++)if((s[i]=='M'||s[i]=='m')&&(s[i+1]=='Y'||s[i+1]=='y')&&s[i+2]==' '){
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
// Hide Workshop subscriptions from this test process only. This does not change
// subscriptions, ownership checks, or the Steam account's actual preferences.
const seen=new Set();
function hideWorkshop(iface){if(iface.isNull())return;const table=iface.readPointer();for(const offset of [0x128,0x12c]){const p=table.add(offset).readPointer();if(seen.has(p.toString()))continue;seen.add(p.toString());Interceptor.attach(p,{onLeave(ret){ret.replace(0);}});}}
const steam=Process.findModuleByName('steam_api.dll');
if(steam){
 const ugc=steam.findExportByName('SteamAPI_SteamUGC_v020');if(ugc)Interceptor.attach(ugc,{onLeave(ret){hideWorkshop(ret);}});
 const find=steam.findExportByName('SteamInternal_FindOrCreateUserInterface');
 if(find)Interceptor.attach(find,{onEnter(args){this.ugc=false;try{this.ugc=args[1].readUtf8String()==='STEAMUGC_INTERFACE_VERSION020';}catch(e){}},onLeave(ret){if(this.ugc)hideWorkshop(ret);}});
}
rpc.exports.info=()=>({pid:Process.id,path:Process.mainModule.path,profile:cfg.profile});
console.log('Isolated Isaac profile enabled');
