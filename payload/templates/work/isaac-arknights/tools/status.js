// Construct short-lived, native status buffs. No enemy HP or AI memory edits.
const arrayNew=api('array_new','pointer',['pointer','size_t']);
const classFromType=api('class_from_il2cpp_type','pointer',['pointer']);
const barrier=api('gc_wbarrier_set_field','void',['pointer','pointer','pointer']);
const rootNew=api('gchandle_new','uint',['pointer','bool']);
const rootFree=api('gchandle_free','void',['uint']);
function refField(obj,name,value){barrier(obj,fld(obj,name),value);}
function listField(obj,name){let value=fld(obj,name).readPointer();if(!value.isNull())return value;
 const f=getField(objectClass(obj),Memory.allocUtf8String(name));value=construct(classFromType(fieldType(f)),[]);refField(obj,name,value);return value;}
const ownedBuffs=new Map();
function makeStatus(enemy,kind,seconds=.65){
 const roots=[];function root(obj){roots.push(rootNew(obj,0));return obj;}
 try{
  const data=root(construct(klass('Torappu.BuffData'),[]));
  const attributes=root(construct(klass('Torappu.AttributeModifierData'),[]));
  refField(data,'attributes',attributes);
  const key='isaac_bridge_'+kind;refField(data,'buffKey',managedString(key));refField(data,'overrideKey',managedString(key));
  refField(data,'templateKey',managedString(key));fld(data,'overrideType').writeS32(2);fld(data,'maxStackCnt').writeS32(1);fld(data,'maxValidStackCnt').writeS32(1);
  fld(data,'lifeTimeType').writeU8(1);fld(data,'lifeTime').writeFloat(seconds);fld(data,'statusResistable').writeS32(1);
  if(kind==='slow'){
   const modifierClass=nestedClass(klass('Torappu.AttributeModifierData'),'AttributeModifier');
   const modifier=root(construct(modifierClass,[]));fld(modifier,'attributeType').writeS32(6);fld(modifier,'formulaItem').writeS32(3);fld(modifier,'value').writeFloat(.5);
   const array=root(arrayNew(modifierClass,1));barrier(array,array.add(32),modifier);refField(attributes,'attributeModifiers',array);
  }else{
   // A routed enemy cannot flee into an arbitrary Isaac room: fear becomes
   // a native stun. Charm roots/disarms it while the Lua side attacks allies.
   const flag={freeze:16,fear:0,charm:18,confusion:11}[kind];if(flag===undefined)throw Error('Unsupported status '+kind);
   const attrs=call(enemy,'get_attributes');if(unbox(call(attrs,'GetAbnormalImmune',[arg(flag)])).readU8()||(kind==='charm'&&unbox(call(attrs,'GetAbnormalImmune',[arg(0)])).readU8()))return zero;
   call(listField(attributes,'abnormalFlags'),'Add',[arg(flag)]);
   if(kind==='charm')call(listField(attributes,'abnormalFlags'),'Add',[arg(13)]);
  }
  const template=root(construct(klass('Torappu.Battle.BuffTemplate'),[]));refField(template,'templateKey',managedString(key));
  const config=root(allocObject(klass('Torappu.Battle.BuffConfig')));refField(config,'data',data);refField(config,'template',template);
  return invoke(specific(klass('Torappu.Battle.Entity'),'AddBuff',['Torappu.Battle.BuffConfig','Torappu.Battle.Entity','Torappu.Battle.Ability','Torappu.Blackboard','Torappu.Blackboard','Torappu.Battle.Projectile','System.String']),enemy,[unbox(config),zero,zero,zero,zero,zero,zero]);
 }finally{roots.forEach(h=>rootFree(h));}
}
function removeOwned(record){if(record.epoch!==snapshot.epoch)return;const enemy=enemyById.get(record.enemy);if(enemy)try{call(enemy,'RemoveBuff',[arg(record.uid)]);}catch(e){} }
function testStatus(request){
 const enemy=enemyById.get(String(request.enemy));if(!enemy)throw Error('Missing enemy');
 const before=val(enemy,'get_moveSpeed','float');const buff=makeStatus(enemy,request.kind||'slow');
 if(buff.isNull())return {id:request.id,immune:true};
 const uid=val(buff,'get_instanceUid'),after=val(enemy,'get_moveSpeed','float'),enabled=val(buff,'get_isEnabled','bool');
 const flags=Number(fld(buff,'<abnormalFlagMask>k__BackingField').readS64());
 call(enemy,'RemoveBuff',[arg(uid)]);
 return {id:request.id,buff:uid,before,after,restored:val(enemy,'get_moveSpeed','float'),enabled,flags};
}
function syncStatuses(request){
 if(request.epoch!==snapshot.epoch)return {id:request.id,rejected:'stale status stage'};
 const desired=new Map();for(const item of request.items||[])for(const kind of item.kinds||[]){if(['slow','freeze','fear','charm','confusion'].includes(kind))desired.set(String(item.enemy)+':'+kind,{enemy:String(item.enemy),kind});}
 for(const [key,record] of ownedBuffs)if(!desired.has(key)||record.epoch!==snapshot.epoch){removeOwned(record);ownedBuffs.delete(key);}
 for(const [key,item] of desired){const enemy=enemyById.get(item.enemy);if(!enemy)continue;const old=ownedBuffs.get(key);
  // Re-apply only after its native life expires. UNIQUE prevents stacking.
  if(old&&Date.now()-old.at<300)continue;
  const buff=makeStatus(enemy,item.kind);if(!buff.isNull())ownedBuffs.set(key,{...item,uid:val(buff,'get_instanceUid'),at:Date.now(),epoch:snapshot.epoch});
 }
 return {id:request.id,statuses:ownedBuffs.size};
}
