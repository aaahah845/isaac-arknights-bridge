// Read-only metadata probe, restricted by the Python host to the local test copy.
const mod = Process.getModuleByName('GameAssembly.dll');
function api(name, ret, args) { return new NativeFunction(mod.getExportByName('il2cpp_' + name), ret, args); }
const domainGet=api('domain_get','pointer',[]), assemblies=api('domain_get_assemblies','pointer',['pointer','pointer']);
const assemblyImage=api('assembly_get_image','pointer',['pointer']), imageName=api('image_get_name','pointer',['pointer']);
const classCount=api('image_get_class_count','size_t',['pointer']), classAt=api('image_get_class','pointer',['pointer','size_t']);
const className=api('class_get_name','pointer',['pointer']), classNamespace=api('class_get_namespace','pointer',['pointer']);
const methods=api('class_get_methods','pointer',['pointer','pointer']), methodName=api('method_get_name','pointer',['pointer']);
const methodReturn=api('method_get_return_type','pointer',['pointer']), typeName=api('type_get_name','pointer',['pointer']);
const paramCount=api('method_get_param_count','uint',['pointer']), paramType=api('method_get_param','pointer',['pointer','uint']);
const paramName=api('method_get_param_name','pointer',['pointer','uint']);
const fields=api('class_get_fields','pointer',['pointer','pointer']), fieldName=api('field_get_name','pointer',['pointer']);
const fieldType=api('field_get_type','pointer',['pointer']), fieldOffset=api('field_get_offset','int',['pointer']);
const parent=api('class_get_parent','pointer',['pointer']);
const attach=api('thread_attach','pointer',['pointer']); attach(domainGet());
function string(p) {return p.isNull()?'':p.readUtf8String();}
function allImages() {
 const size=Memory.alloc(8);const p=assemblies(domainGet(),size);let out=[];
 for(let i=0;i<size.readU64().toNumber();i++){const image=assemblyImage(p.add(i*8).readPointer());out.push({image,name:string(imageName(image))});} return out;
}
const imgs=allImages();const classes=new Map();
function scan(pattern, imagePattern) { const rx=new RegExp(pattern,'i');let out=[];
 for(const {image,name} of imgs){if(imagePattern&&!new RegExp(imagePattern,'i').test(name))continue;
 for(let i=0,n=Number(classCount(image));i<n;i++){const c=classAt(image,i);const full=string(classNamespace(c))+'.'+string(className(c));classes.set(full,c);if(rx.test(full))out.push({name:full,image:name});}}
 return out;
}
function detail(name) {if(!classes.has(name))scan('^$');let c=classes.get(name);if(name.includes('::')){const [base,child]=name.split('::');c=nestedClass(classes.get(base),child);}if(!c)throw Error('Class missing: '+name);
 const ms=[],fs=[],it=Memory.alloc(8);it.writePointer(ptr(0));let m;
 while(!(m=methods(c,it)).isNull()) {let params=[];for(let i=0;i<paramCount(m);i++)params.push(string(typeName(paramType(m,i)))+' '+string(paramName(m,i)));ms.push({name:string(methodName(m)),returns:string(typeName(methodReturn(m))),params,address:m.readPointer().toString()});}
 it.writePointer(ptr(0));let f;while(!(f=fields(c,it)).isNull())fs.push({name:string(fieldName(f)),type:string(typeName(fieldType(f))),offset:fieldOffset(f)});
 const p=parent(c);return {name,parent:p.isNull()?null:string(classNamespace(p))+'.'+string(className(p)),fields:fs,methods:ms};
}
const nestedTypes=api('class_get_nested_types','pointer',['pointer','pointer']);
function nestedClass(c,name){const it=Memory.alloc(8);it.writePointer(ptr(0));let n;while(!(n=nestedTypes(c,it)).isNull())if(string(className(n))===name)return n;throw Error('Nested class missing '+name);}
function enums(name,child){if(!classes.has(name))scan('^$');let c=classes.get(name);if(name.includes('::')){const parts=name.split('::');c=classes.get(parts.shift());for(const part of parts)c=nestedClass(c,part);}if(child)c=nestedClass(c,child);const output={};const it=Memory.alloc(8);it.writePointer(ptr(0));let f;const read=api('field_static_get_value','void',['pointer','pointer']);
 while(!(f=fields(c,it)).isNull()){const name=string(fieldName(f));if(name==='value__')continue;const buf=Memory.alloc(16);read(f,buf);output[name]=buf.readS32();}return output;}
function bases(name){if(!classes.has(name))scan('^$');const out=[];for(let c=classes.get(name);!c.isNull();c=parent(c)){let fs=[],it=Memory.alloc(8);it.writePointer(ptr(0));let f;while(!(f=fields(c,it)).isNull())if(/instance/i.test(string(fieldName(f))))fs.push({name:string(fieldName(f)),type:string(typeName(fieldType(f))),offset:fieldOffset(f)});out.push({name:string(classNamespace(c))+'.'+string(className(c)),fields:fs});}return out;}
rpc.exports={images:()=>imgs.map(i=>i.name),scan,detail,enums,bases};
