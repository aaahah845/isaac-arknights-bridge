function projectileObjects(){
 const type=klass('Torappu.Battle.Projectile');
 const all=invoke(specific(klass('UnityEngine.Resources'),'FindObjectsOfTypeAll',['System.Type']),zero,[getTypeObject(getClassType(type))]);
 const items=[];for(let i=0;i<Number(all.add(24).readU64());i++){
  const p=all.add(32+i*8).readPointer();try{const go=call(p,'get_gameObject');items.push({object:p,ptr:p.toString(),key:strObj(call(p,'get_key')),effect:strObj(fld(p,'_mainEffect').readPointer()),name:strObj(call(go,'get_name')),active:val(go,'get_activeInHierarchy','bool')});}catch(e){}
 }
 return items;
}
function visualProbe(){
 const items=projectileObjects().map(({object,...info})=>info);
 const effects=invoke(specific(klass('UnityEngine.Resources'),'FindObjectsOfTypeAll',['System.Type']),zero,[getTypeObject(getClassType(klass('Torappu.Battle.Effects.Effect')))]),names=[];
 for(let i=0;i<Number(effects.add(24).readU64());i++){const effect=effects.add(32+i*8).readPointer(),name=strObj(call(call(effect,'get_gameObject'),'get_name'));if(/mocock/i.test(name))names.push({ptr:effect.toString(),name});}
 return {id:'visual-probe',effects:names,projectiles:items.filter(p=>/enemy|enm|mocock/i.test(p.key+' '+p.name)).slice(0,80),characters:snapshot.characters||[],enemyWeapons:snapshot.enemies.map(e=>{const enemy=enemyById.get(e.id);let key='';try{key=strObj(fld(call(enemy,'get_attack'),'_projectileKey').readPointer());}catch(e){}return {id:e.id,kind:e.kind,key};})};
}
// Copy only rendered geometry. Cached projectile scripts and combat actions
// remain inactive, so capturing their art cannot cause another native hit.
function captureProjectile(key){
 const type=klass('Torappu.Battle.Projectile');const all=invoke(specific(klass('UnityEngine.Resources'),'FindObjectsOfTypeAll',['System.Type']),zero,[getTypeObject(getClassType(type))]);
 let source=zero;
 for(let i=0;i<Number(all.add(24).readU64());i++){const p=all.add(32+i*8).readPointer();const name=strObj(call(call(p,'get_gameObject'),'get_name'));if(name===key||name.startsWith(key+'(')){source=p;break;}}
 if(source.isNull())throw Error('Projectile prefab not loaded: '+key);
 const goClass=klass('UnityEngine.GameObject'),object=klass('UnityEngine.Object');let srcRoot=call(source,'get_gameObject');
 const effectName=strObj(fld(source,'_mainEffect').readPointer());
 if(effectName){
  const effects=invoke(specific(klass('UnityEngine.Resources'),'FindObjectsOfTypeAll',['System.Type']),zero,[getTypeObject(getClassType(klass('Torappu.Battle.Effects.Effect')))]);
  for(let i=0;i<Number(effects.add(24).readU64());i++){const effect=effects.add(32+i*8).readPointer(),go=call(effect,'get_gameObject'),name=strObj(call(go,'get_name'));if(name===effectName){srcRoot=go;break;}}
 }
 const renderers=invoke(specific(goClass,'GetComponentsInChildren',['System.Type','System.Boolean']),srcRoot,[getTypeObject(getClassType(klass('UnityEngine.Renderer'))),arg(1)]);
 const root=construct(goClass,[managedString('BridgeWeaponGeometry')]);const children=[];let copied=0;
 try{
  const rootTransform=call(root,'get_transform');call(rootTransform,'set_position',[unbox(call(call(srcRoot,'get_transform'),'get_position'))]);
  for(let i=0;i<Number(renderers.add(24).readU64());i++){
   const renderer=renderers.add(32+i*8).readPointer(),go=call(renderer,'get_gameObject');
   const meshFilter=invoke(specific(goClass,'GetComponent',['System.Type']),go,[getTypeObject(getClassType(klass('UnityEngine.MeshFilter')))]);
   if(meshFilter.isNull()){
    // Projectile prefabs commonly use a pure ParticleSystem subtree. Clone
    // only a subtree with no MonoBehaviours or audio; never the combat root.
    const systems=invoke(specific(goClass,'GetComponent',['System.Type']),go,[getTypeObject(getClassType(klass('UnityEngine.ParticleSystem')))]);
    if(!systems.isNull()){
     const scripts=invoke(specific(goClass,'GetComponentsInChildren',['System.Type','System.Boolean']),go,[getTypeObject(getClassType(klass('UnityEngine.MonoBehaviour'))),arg(1)]);
     const audio=invoke(specific(goClass,'GetComponentsInChildren',['System.Type','System.Boolean']),go,[getTypeObject(getClassType(klass('UnityEngine.AudioSource'))),arg(1)]);
     if(Number(scripts.add(24).readU64())||Number(audio.add(24).readU64()))continue;
     const ghost=invoke(specific(object,'Instantiate',['UnityEngine.Object']),zero,[go]);children.push(ghost);
     call(call(ghost,'get_transform'),'set_parent',[rootTransform]);call(ghost,'SetActive',[arg(1)]);
     const ps=invoke(specific(goClass,'GetComponent',['System.Type']),ghost,[getTypeObject(getClassType(klass('UnityEngine.ParticleSystem')))]);
     call(ps,'Simulate',[arg(.05,'float'),arg(1),arg(1),arg(0)]);copied++;
    }
    continue;
   }
   const mesh=call(meshFilter,'get_sharedMesh');if(mesh.isNull())continue;
   const ghost=construct(goClass,[managedString('WeaponMesh')]);children.push(ghost);const tf=call(ghost,'get_transform'),original=call(go,'get_transform');
   call(tf,'set_parent',[rootTransform]);call(tf,'set_position',[unbox(call(original,'get_position'))]);call(tf,'set_rotation',[unbox(call(original,'get_rotation'))]);call(tf,'set_localScale',[unbox(call(original,'get_lossyScale'))]);
   const filter=invoke(specific(goClass,'AddComponent',['System.Type']),ghost,[getTypeObject(getClassType(klass('UnityEngine.MeshFilter')))]);call(filter,'set_sharedMesh',[mesh]);
   const copy=invoke(specific(goClass,'AddComponent',['System.Type']),ghost,[getTypeObject(getClassType(klass('UnityEngine.MeshRenderer')))]);call(copy,'set_sharedMaterials',[call(renderer,'get_sharedMaterials')]);copied++;
  }
  if(!copied)throw Error('Projectile has no baked mesh: '+key);
  // Transform is a Component and supplies get_gameObject for captureVisual.
  const result=captureVisual(rootTransform,'weapon_'+key,key,512);return {...result,meshes:copied};
 }finally{invoke(method(object,'Destroy',1),zero,[root]);}
}
