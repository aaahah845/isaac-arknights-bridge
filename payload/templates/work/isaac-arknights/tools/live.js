// Appended to probe.js. All managed calls below run on BattleController.Update.
const invokeApi=api('runtime_invoke','pointer',['pointer','pointer','pointer','pointer']);
const unbox=api('object_unbox','pointer',['pointer']);
const objectClass=api('object_get_class','pointer',['pointer']);
const getField=api('class_get_field_from_name','pointer',['pointer','pointer']);
const staticField=api('field_static_get_value','void',['pointer','pointer']);
const allocObject=api('object_new','pointer',['pointer']);
scan('^$');
const zero=ptr(0), methodCache=new Map();
function method(c,name,count) {
 const key=c+':'+name+':'+count;if(methodCache.has(key))return methodCache.get(key);
 let cur=c;while(!cur.isNull()) {const it=Memory.alloc(8);it.writePointer(zero);let m;
 while(!(m=methods(cur,it)).isNull())if(string(methodName(m))===name&&(count===undefined||paramCount(m)===count)){methodCache.set(key,m);return m;}
 cur=parent(cur);} throw Error('Method missing '+string(className(c))+'.'+name+'/'+count);
}
function klass(name){const c=classes.get(name);if(!c)throw Error('Missing class '+name);return c;}
function arg(value,kind='int') {if(value instanceof NativePointer)return value;const p=Memory.alloc(16);if(kind==='float')p.writeFloat(value);else if(kind==='fp')p.writeS64(Math.round(value*fpScale));else p.writeS32(value);return p;}
function invoke(m,obj=zero,values=[]) {const args=Memory.alloc(Math.max(8,values.length*8));values.forEach((p,i)=>args.add(i*8).writePointer(p));const ex=Memory.alloc(8);ex.writePointer(zero);const ret=invokeApi(m,obj,args,ex);if(!ex.readPointer().isNull())throw Error('Managed exception in '+string(methodName(m)));return ret;}
function call(obj,name,values=[]) {return invoke(method(objectClass(obj),name,values.length),obj,values);}
function val(obj,name,kind='int') {const box=call(obj,name);if(box.isNull())return null;const p=unbox(box);if(kind==='fp')return p.readS64().toNumber()/fpScale;if(kind==='float')return p.readFloat();if(kind==='bool')return !!p.readU8();return p.readS32();}
function strObj(o) {return o.isNull()?'':o.add(20).readUtf16String(o.add(16).readS32());}
function fld(obj,name){let c=objectClass(obj);while(!c.isNull()){let f=getField(c,Memory.allocUtf8String(name));if(!f.isNull())return obj.add(fieldOffset(f));c=parent(c);}throw Error('Field missing '+name);}
function objectInfo(obj) {const c=objectClass(obj);return {name:string(classNamespace(c))+'.'+string(className(c)),fields:detailClass(c)};}
function detailClass(c){let fs=[],it=Memory.alloc(8);it.writePointer(zero);let f;while(!(f=fields(c,it)).isNull())if(!string(fieldName(f)).startsWith('__Hotfix'))fs.push({name:string(fieldName(f)),type:string(typeName(fieldType(f))),offset:fieldOffset(f)});return fs;}
const fpClass=klass('Torappu.FP');
const fpScale=unbox(invoke(method(fpClass,'FromFloat',1),zero,[arg(1,'float')])).readS64().toNumber();
const bcClass=klass('Torappu.Battle.BattleController');
let singletonField=zero;
for(let base=parent(bcClass);!base.isNull();base=parent(base)){
 const it=Memory.alloc(8);it.writePointer(zero);let field;
 while(!(field=fields(base,it)).isNull())if(/instance/i.test(string(fieldName(field)))&&string(typeName(fieldType(field))).includes('BattleController'))singletonField=field;
}
let last=0,controller=zero,snapshot={active:false},requests=[],diagnostics=[],enemyById=new Map(),resultQueue=[];
let lastMap='',mapCache=null,lastTileScan=0,mapRevision=0,isaacPlayer=null,unitById=new Map(),lastUnits=new Map();
const mapGeneration=Date.now().toString(36);
const enemyLives=new Map();let lifeEpoch=null;
function observeLife(id,address,hp){
 let record=enemyLives.get(id);
 if(!record)record={address,life:1,hp};
 else if(record.address!==address||(record.hp<=0&&hp>0))record={address,life:record.life+1,hp};
 record.hp=hp;enemyLives.set(id,record);return mapGeneration+':'+record.life;
}
let finishedStage=null;
const battleCounterField=getField(bcClass,Memory.allocUtf8String('s_battleUidCounter'));
const stageMarkers=new Map();
function stageEpoch(bc,playing,level){const key=Process.id+':'+bc;
 let record=stageMarkers.get(key);
 if(!record){const value=Memory.alloc(8);staticField(battleCounterField,value);const prior=typeof priorStageEpoch==='string'&&priorStageEpoch.startsWith(key+':')&&(typeof priorStageId!=='string'||priorStageId===level)?priorStageEpoch:null;record={epoch:prior||key+':'+value.readU32(),playing:null,level};stageMarkers.set(key,record);}
 if(playing&&(record.playing===false||record.level!==level))record.epoch=key+':'+Date.now();
 record.playing=playing;record.level=level;return record.epoch;}
const lifecycleHooks=[];
lifecycleHooks.push(Interceptor.attach(method(bcClass,'Awake',0).readPointer(),{onEnter(args){finishedStage=null;stageMarkers.set(Process.id+':'+args[0],{epoch:Process.id+':'+args[0]+':'+Date.now(),playing:null,level:null});}}));
lifecycleHooks.push(Interceptor.attach(method(bcClass,'FinishGame',3).readPointer(),{onEnter(args){finishedStage={...snapshot,active:false,paused:false,enemies:[],gameResult:args[1].toInt32()};}}));
const inputHooks=[];
const user=Process.getModuleByName('user32.dll');
const asyncKey=new NativeFunction(user.getExportByName('GetAsyncKeyState'),'int16',['int']);
const foregroundWindow=new NativeFunction(user.getExportByName('GetForegroundWindow'),'pointer',[]);
const windowPid=new NativeFunction(user.getExportByName('GetWindowThreadProcessId'),'uint',['pointer','pointer']);
const inputDown={},inputPresses={};let nativeInput=null,inputSequence=0;
function readInput(){
 const pid=Memory.alloc(4);windowPid(foregroundWindow(),pid);
 const out={focus:pid.readU32()===Process.id,foregroundPid:pid.readU32(),edgeSession:mapGeneration,sequence:++inputSequence,presses:{}};
 const keys={left:65,right:68,up:87,down:83,shootLeft:37,shootRight:39,shootUp:38,shootDown:40,bomb:69,item:32,card:81,drop:17};
 for(const [index,[key,code]] of Object.entries(Object.entries(keys))){
  const i=Number(index);const down=!!(asyncKey(code)&0x8000);out[key]=down;
  if(out.focus&&down&&!inputDown[key])inputPresses[key]=(inputPresses[key]||0)+1;
  inputDown[key]=down;out.presses[key]=Math.max(inputPresses[key]||0,nativeInput?nativeInput.presses.add(i*4).readU32():0);
 }
 out.windowItemPresses=nativeInput?nativeInput.presses.add(9*4).readU32():0;return out;
}
try{
 const presses=Memory.alloc(24*4);const ownPid=Memory.alloc(4);ownPid.writeU32(Process.id);
 // A queued window event survives a short press/release. Run the interceptor
 // in native code so game window dispatch never waits for the JS runtime.
 const sampler=new CModule(`
#include <gum/guminterceptor.h>
extern volatile unsigned int press_counts[];
extern unsigned int own_pid;
extern void *foreground_window(void);
extern unsigned long window_pid(void *window,unsigned long *pid);
void enter(GumInvocationContext *ic){
 unsigned char *msg=gum_invocation_context_get_nth_argument(ic,0);
 if(!msg)return;
 unsigned int message=*(unsigned int *)(msg+8);
 if(message!=0x100&&message!=0x104)return;
 unsigned long long flags=*(unsigned long long *)(msg+24);
 if(flags&(1ULL<<30))return;
 unsigned long pid=0;window_pid(foreground_window(),&pid);if(pid!=own_pid)return;
 unsigned int code=*(unsigned int *)(msg+16);
 const int keys[12]={65,68,87,83,37,39,38,40,69,32,81,17};
 unsigned int time=*(unsigned int *)(msg+32);
 for(int i=0;i<12;i++)if(code==keys[i]){if(press_counts[12+i]!=time){press_counts[12+i]=time;press_counts[i]++;}break;}
}
`,{press_counts:presses,own_pid:ownPid,foreground_window:user.getExportByName('GetForegroundWindow'),window_pid:user.getExportByName('GetWindowThreadProcessId')});
 const hooks=['DispatchMessageW','DispatchMessageA'].map(name=>Interceptor.attach(user.getExportByName(name),{onEnter:sampler.enter}));
 nativeInput={presses,sampler,stop:()=>hooks.forEach(h=>h.detach())};
 console.log('Native window input edges installed');
}catch(e){console.log('Window input edges unavailable; using relay sampling: '+e);}
try{
 const inputClass=klass('UnityEngine.Input'),iter=Memory.alloc(8);iter.writePointer(zero);let m;
 while(!(m=methods(inputClass,iter)).isNull())if(['GetKeyDown','GetKeyUp','GetKey'].includes(string(methodName(m)))&&paramCount(m)===1&&string(typeName(paramType(m,0)))==='UnityEngine.KeyCode'){
  inputHooks.push(Interceptor.attach(m.readPointer(),{onEnter(args){this.block=isaacPlayer&&Date.now()-isaacPlayer.updated<2000&&snapshot.active&&[32,97,100,101,113,115,119,273,274,275,276,306].includes(args[0].toInt32());},onLeave(ret){if(this.block)ret.replace(0);}}));
 }
}catch(e){console.log('Input filter unavailable: '+e);}
function vec2(x,y){const p=Memory.alloc(8);p.writeFloat(x);p.add(4).writeFloat(y);return p;}
function vec3(x,y,z){const p=Memory.alloc(12);p.writeFloat(x);p.add(4).writeFloat(y);p.add(8).writeFloat(z);return p;}
function project(camera,world,height) {const p=unbox(call(camera,'WorldToScreenPoint',[world]));return {x:p.readFloat(),y:height-p.add(4).readFloat()};}
function tilesOf(map,width,height){
 const output=[];for(let y=0;y<height;y++)for(let x=0;x<width;x++){
  const tile=call(map,'GetTile',[arg(y),arg(x)]);
  if(tile.isNull()){output.push({x,y,tileKey:'tile_forbidden',heightType:1,passableMask:0,walkable:false,flyable:false});continue;}
  const data=call(tile,'get_data');let buildableType=0;try{buildableType=fld(data,'buildableType').readS32();}catch(e){}
  output.push({x,y,tileKey:strObj(call(tile,'get_tileKey')),heightType:val(tile,'get_heightType'),buildableType,
   passableMask:val(tile,'get_passableMask'),walkable:!!unbox(call(tile,'IsPassable',[arg(0)])).readU8(),flyable:!!unbox(call(tile,'IsPassable',[arg(1)])).readU8()});
 }return output;
}
function sample(bc) {
 const active=val(bc,'get_isPlaying','bool');const map=call(bc,'get_map');
 const level=strObj(call(bc,'get_levelId'));
 let result={active,paused:val(bc,'get_isPaused','bool'),gameResult:val(bc,'get_gameResult'),stage:level,epoch:stageEpoch(bc,active,level),enemies:[],characters:[],fpScale,time:Date.now()};
 if(lifeEpoch!==result.epoch){enemyLives.clear();lifeEpoch=result.epoch;}
 if(finishedStage&&!active&&finishedStage.epoch===result.epoch&&finishedStage.stage===level)return {...finishedStage,time:Date.now()};
 if(map.isNull())return result;
 result.width=val(map,'get_width');result.height=val(map,'get_height');
 const screen=klass('UnityEngine.Screen');result.screenWidth=unbox(invoke(method(screen,'get_width',0))).readS32();result.screenHeight=unbox(invoke(method(screen,'get_height',0))).readS32();
 const camera=invoke(method(klass('UnityEngine.Camera'),'get_main',0));
 if(!camera.isNull())result.corners=[[-.5,-.5],[result.width-.5,-.5],[result.width-.5,result.height-.5],[-.5,result.height-.5]].map(([x,y])=>project(camera,unbox(call(map,'MapToWorldPosition',[vec2(x,y)])),result.screenHeight));
 const mapKey=result.epoch+':'+result.stage+':'+map+':'+result.width+'x'+result.height;
 if(lastMap!==mapKey||Date.now()-lastTileScan>1000){
  try{const current=tilesOf(map,result.width,result.height);if(lastMap!==mapKey||JSON.stringify(current)!==JSON.stringify(mapCache)){mapCache=current;mapRevision++;}lastMap=mapKey;lastTileScan=Date.now();}
  catch(e){diagnostics.push({tilesError:String(e)});if(lastMap!==mapKey)mapCache=[];}
 }result.tiles=mapCache;result.mapToken=result.epoch+':'+mapGeneration+':'+mapRevision;
 const manager=fld(bc,'<unitManager>k__BackingField').readPointer();if(manager.isNull())return result;
 const collection=call(manager,'get_enemies');if(collection.isNull())return result;
 if(diagnostics.length===0)diagnostics.push(objectInfo(collection));
 const c=objectClass(collection);let array=zero,count=0;
 for(const f of detailClass(c)){if(f.type.endsWith('[]'))array=collection.add(f.offset).readPointer();if(f.type==='System.Int32'&&/count|size|length/i.test(f.name))count=collection.add(f.offset).readS32();}
 if(array.isNull())return result;
 // count=0 means empty, not the backing array's capacity.
 const newEnemies=new Map();
 for(let i=0;i<Math.min(count,512);i++){const enemy=array.add(32+i*8).readPointer();if(enemy.isNull())continue;
 let actualEnemy=false;for(let cls=objectClass(enemy);!cls.isNull();cls=parent(cls))if(cls.equals(klass('Torappu.Battle.Enemy'))){actualEnemy=true;break;}if(!actualEnemy)continue;
 if(!val(enemy,'get_isAlive','bool'))continue;
 const id=String(fld(enemy,'<instanceUid>k__BackingField').readU32());newEnemies.set(id,enemy);const world=call(enemy,'get_worldPosition'),pos=unbox(call(map,'WorldToMapPosition',[unbox(world)]));
 const item={id,kind:strObj(call(enemy,'get_id'))||strObj(call(enemy,'get_realId')),hp:val(enemy,'get_hp','fp'),maxHp:val(enemy,'get_maxHp','fp'),def:val(enemy,'get_def','fp'),resist:val(enemy,'get_magicResistance','fp'),atk:val(enemy,'get_atk','fp'),attackTime:val(enemy,'get_attackTime','fp'),x:pos.readFloat(),y:pos.add(4).readFloat(),hidden:val(enemy,'get_isHidden','bool')};
 item.life=observeLife(id,enemy.toString(),item.hp);
 if(!camera.isNull())item.screen=project(camera,unbox(world),result.screenHeight);
 item.colliderRadius=val(enemy,'get_ColliderRadius','fp');
 item.moveSpeed=val(enemy,'get_moveSpeed','float');item.stunned=val(enemy,'get_isStunned','bool');
 item.frozen=val(enemy,'get_isFrozen','bool');item.disarmed=val(enemy,'get_isDisarmed','bool');item.invincible=val(enemy,'get_isInvincible','bool');
 const attrs=call(enemy,'get_attributes');item.controlImmunes={};for(const [kind,flag] of Object.entries({freeze:16,fear:0,charm:0,confusion:11}))item.controlImmunes[kind]=!!unbox(call(attrs,'GetAbnormalImmune',[arg(flag)])).readU8();
 const data=call(enemy,'get_data');if(!data.isNull()){item.name=strObj(fld(data,'name').readPointer());item.rangeRadius=fld(data,'rangeRadius').readFloat();item.flying=fld(data,'motion').readS32()===1;}
 try{item.projectileKey=strObj(fld(call(enemy,'get_attack'),'_projectileKey').readPointer());}catch(e){}
 result.enemies.push(item);}
 enemyById=newEnemies;unitById=new Map(newEnemies);
 const characters=call(manager,'get_characters');
 if(!characters.isNull()){
  const arr=characters.add(16).readPointer(),count=characters.add(32).readS32();
  for(let i=0;i<Math.min(count,64);i++){const unit=arr.add(32+i*8).readPointer();if(unit.isNull()||!val(unit,'get_isAlive','bool'))continue;
   let isCharacter=false;for(let cls=objectClass(unit);!cls.isNull();cls=parent(cls))if(cls.equals(klass('Torappu.Battle.Character'))){isCharacter=true;break;}if(!isCharacter)continue;
   const id=String(fld(unit,'<instanceUid>k__BackingField').readU32()),kind='operator_'+strObj(call(unit,'get_characterId'));
   const pos=unbox(call(map,'WorldToMapPosition',[unbox(call(unit,'get_worldPosition'))]));unitById.set(id,unit);
   result.characters.push({id,kind,x:pos.readFloat(),y:pos.add(4).readFloat(),hp:val(unit,'get_hp','fp'),maxHp:val(unit,'get_maxHp','fp')});
  }
 }
 const nextUnits=new Map();for(const item of [...result.enemies,...result.characters]){
  const previous=lastUnits.get(item.id),dt=previous?(result.time-previous.time)/1000:0;
  item.vx=dt>0&&!result.paused?(item.x-previous.x)/dt:0;item.vy=dt>0&&!result.paused?(item.y-previous.y)/dt:0;
  nextUnits.set(item.id,{x:item.x,y:item.y,time:result.time});
 }lastUnits=nextUnits;
 return result;
}
function damage(request){
 const enemy=enemyById.get(String(request.enemy));
 if(request.epoch!==snapshot.epoch||!snapshot.active||snapshot.paused||!enemy)return {id:request.id,rejected:'inactive, stale, paused, or missing enemy'};
 const before=val(enemy,'get_hp','fp');const amount=Math.min(100000000,Math.max(0,Number(request.amount)||0));
 const life=observeLife(String(request.enemy),enemy.toString(),before);
 if(request.life!==undefined&&request.life!==life)return {id:request.id,rejected:'stale enemy life'};
 const klassModifier=klass('Torappu.Battle.Modifier');const object=allocObject(klassModifier),buffer=unbox(object);
 invoke(method(klassModifier,'.ctor',6),buffer,[arg(0),arg(2),arg(amount,'fp'),zero,enemy,arg(0)]);
 invoke(method(klassModifier,'set_damageType',1),buffer,[arg(request.damageType||1)]);
 // Honor the native shield, immunity, rebirth and defeat handling.
 const applied=call(enemy,'ApplyModifier',[buffer,arg(0)]);
 const after=val(enemy,'get_hp','fp');enemyLives.get(String(request.enemy)).hp=after;
 return {id:request.id,enemy:request.enemy,life,before,after,applied:!applied.isNull()&&!!unbox(applied).readU8()};
}
function dispatch(request){
 if(request.type==='visualProbe')return visualProbe();
 if(request.type==='captureProjectile')return captureProjectile(request.key);
 if(request.type==='buffTest')return testStatus(request);
 if(request.type==='statuses')return syncStatuses(request);
 if(request.type==='release'){
  syncStatuses({epoch:snapshot.epoch,items:[]});call(controller,'SetPaused',[arg(0),arg(5)]);call(controller,'SetPaused',[arg(1),arg(0)]);return {id:request.id,released:true};
 }
 if(request.type==='capture')return captureEnemy(request.enemy);
 if(request.type==='pause'){call(controller,'SetPaused',[arg(request.value?1:0),arg(request.key||0)]);return {id:request.id,paused:request.value,key:request.key||0};}
 return damage(request);
}
let busy=false;
function pump(bc){
 if(busy)return;const now=Date.now();if(now-last<30)return;last=now;
 if(!singletonField.isNull()){const p=Memory.alloc(8);staticField(singletonField,p);controller=p.readPointer();}else if(bc)controller=bc;
 if(controller.isNull()||controller.add(16).readPointer().isNull()){snapshot={...(finishedStage||snapshot),active:false,time:now,enemies:[]};enemyById.clear();return;}
 busy=true;
 try{snapshot=sample(controller);for(const request of requests.splice(0)){try{resultQueue.push(dispatch(request));}catch(e){resultQueue.push({id:request.id,error:String(e),stack:e.stack});}}}catch(e){snapshot={active:false,error:String(e),stack:e.stack};}
 finally{busy=false;}
}
const hook=Interceptor.attach(method(bcClass,'Update',0).readPointer(),{onEnter(args){this.bc=args[0];},onLeave(){pump(this.bc);}});
let canvasHook=null;
try{canvasHook=Interceptor.attach(method(klass('UnityEngine.Canvas'),'SendWillRenderCanvases',0).readPointer(),{onLeave(){pump();}});}catch(e){console.log('Canvas pump unavailable: '+e);}
rpc.exports={state:()=>snapshot,diagnostics:()=>diagnostics,metadata:()=>({fpScale}),info:()=>({controller:controller.toString(),snapshot,diagnostics}),
 player:(data)=>{isaacPlayer={...data,updated:Date.now()};},
 inputs:readInput,
 exchange:(batch,player)=>{if(player)isaacPlayer={...player,updated:Date.now()};requests.push(...batch);return {state:snapshot,results:resultQueue.splice(0),input:readInput()};},
 enqueue:(batch)=>{if(batch.length>100)throw Error('Too many events');requests.push(...batch);},
 pause:(value,key=0)=>requests.push({id:'pause-'+Date.now(),type:'pause',value,key}),
 hits:(batch)=>{if(batch.length>100)throw Error('Too many events');requests.push(...batch);return resultQueue.splice(0);},results:()=>resultQueue.splice(0),
 detailObject:(address)=>objectInfo(ptr(address)),
 stop:()=>{if(nativeInput)nativeInput.stop();hook.detach();if(canvasHook)canvasHook.detach();inputHooks.forEach(h=>h.detach());lifecycleHooks.forEach(h=>h.detach());}};
console.log('Local battle bridge ready; fixed-point scale='+fpScale);
