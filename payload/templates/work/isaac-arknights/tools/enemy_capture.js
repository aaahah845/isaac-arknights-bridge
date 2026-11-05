// Capture the existing enemy renderer in the local test client, with a
// temporary camera. Every changed layer and render target is restored.
const getClassType=api('class_get_type','pointer',['pointer']);
const getTypeObject=api('type_get_object','pointer',['pointer']);
const newString=api('string_new','pointer',['pointer']);
function managedString(s){return newString(Memory.allocUtf8String(s));}
function specific(c,name,types){const it=Memory.alloc(8);it.writePointer(zero);let m;while(!(m=methods(c,it)).isNull())if(string(methodName(m))===name&&paramCount(m)===types.length){let good=true;for(let i=0;i<types.length;i++)if(string(typeName(paramType(m,i)))!==types[i])good=false;if(good)return m;}throw Error('Missing overload '+name+' '+types);}
function construct(c,values){const obj=allocObject(c);invoke(method(c,'.ctor',values.length),obj,values);return obj;}
function readVec(p){return [p.readFloat(),p.add(4).readFloat(),p.add(8).readFloat()];}
function captureEnemy(id){
 const enemy=unitById.get(String(id))||enemyById.get(String(id));if(!enemy)throw Error('Unit already left');
 let kind='';
 try{const charId=strObj(call(enemy,'get_characterId'));if(charId)kind='operator_'+charId;}catch(e){}
 if(!kind)kind=strObj(call(enemy,'get_id'))||strObj(call(enemy,'get_realId'));
 return captureVisual(enemy,kind,id,512);
}
function captureVisual(enemy,kind,id,resolution=512){
 const object=klass('UnityEngine.Object'),camClass=klass('UnityEngine.Camera'),goClass=klass('UnityEngine.GameObject');
 const rtClass=klass('UnityEngine.RenderTexture'),texClass=klass('UnityEngine.Texture2D');
 const main=invoke(method(camClass,'get_main',0));const root=call(enemy,'get_gameObject');
 const components=invoke(specific(goClass,'GetComponentsInChildren',['System.Type','System.Boolean']),root,[getTypeObject(getClassType(klass('UnityEngine.Renderer'))),arg(1)]);
 const saved=new Map(),created=[];let oldActive=zero;
 try{
  const n=Number(components.add(24).readU64());for(let i=0;i<n;i++){const renderer=components.add(32+i*8).readPointer();const go=call(renderer,'get_gameObject');if(saved.has(go.toString()))continue;saved.set(go.toString(),{go,layer:val(go,'get_layer')});call(go,'set_layer',[arg(30)]);}
  const camGo=construct(goClass,[managedString('IsaacBridgePreview')]);created.push(camGo);
  const cam=invoke(specific(goClass,'AddComponent',['System.Type']),camGo,[getTypeObject(getClassType(camClass))]);call(cam,'CopyFrom',[main]);
  call(cam,'set_enabled',[arg(0)]);call(cam,'set_orthographic',[arg(1)]);call(cam,'set_orthographicSize',[arg(.9,'float')]);call(cam,'set_clearFlags',[arg(2)]);call(cam,'set_cullingMask',[arg(1<<30)]);
  const color=Memory.alloc(16);color.writeByteArray(new Uint8Array(16));call(cam,'set_backgroundColor',[color]);
  const mainTransform=call(main,'get_transform'),transform=call(cam,'get_transform');
  let world;try{world=readVec(unbox(call(enemy,'get_worldPosition')));}catch(e){world=readVec(unbox(call(call(root,'get_transform'),'get_position')));}
  const forward=readVec(unbox(call(mainTransform,'get_forward'))),up=readVec(unbox(call(mainTransform,'get_up')));
  const lift=kind.startsWith('weapon_')?0:.45;
  const cameraPos=world.map((x,i)=>x+up[i]*lift-forward[i]*10);call(transform,'set_position',[vec3(...cameraPos)]);call(transform,'set_rotation',[unbox(call(mainTransform,'get_rotation'))]);
  const rt=construct(rtClass,[arg(resolution),arg(resolution),arg(24)]);created.push(rt);call(rt,'Create');call(cam,'set_targetTexture',[rt]);
  oldActive=invoke(method(rtClass,'get_active',0));invoke(method(rtClass,'set_active',1),zero,[rt]);call(cam,'Render');
  const texture=allocObject(texClass);invoke(specific(texClass,'.ctor',['System.Int32','System.Int32','UnityEngine.TextureFormat','System.Boolean']),texture,[arg(resolution),arg(resolution),arg(4),arg(0)]);created.push(texture);
  const rect=Memory.alloc(16);[0,0,resolution,resolution].forEach((v,i)=>rect.add(i*4).writeFloat(v));call(texture,'ReadPixels',[rect,arg(0),arg(0),arg(0)]);call(texture,'Apply',[arg(0),arg(0)]);
  let size=0;
  for(const matte of ['black','white']){
   if(matte==='white'){[1,1,1,1].forEach((v,i)=>color.add(i*4).writeFloat(v));call(cam,'set_backgroundColor',[color]);call(cam,'Render');call(texture,'ReadPixels',[rect,arg(0),arg(0),arg(0)]);call(texture,'Apply',[arg(0),arg(0)]);}
   const image=invoke(method(klass('UnityEngine.ImageConversion'),'EncodeToPNG',1),zero,[texture]);size+=Number(image.add(24).readU64());
   send({type:'enemy-image',kind,id,matte,resolution},image.add(32).readByteArray(Number(image.add(24).readU64())));
  }
  return {id,bytes:size,renderers:n};
 }finally{
  invoke(method(rtClass,'set_active',1),zero,[oldActive]);
  for(const {go,layer} of saved.values())call(go,'set_layer',[arg(layer)]);
  for(const obj of created.reverse())try{invoke(method(object,'Destroy',1),zero,[obj]);}catch(e){}
 }
}
rpc.exports.capture=(id)=>{requests.push({id:'capture-'+id,type:'capture',enemy:id});};
