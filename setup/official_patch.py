"""Apply the official launcher's BSDIFF40 delta to a private client copy.

No game program or resource is supplied here; inputs are the user's supported
Steam files and the unmodified delta already shipped by the official launcher.
"""
import bz2,io,mmap,os,shutil,zipfile,json
from pathlib import Path
import numpy as np

def number(data):
    if len(data)!=8:raise ValueError('Truncated BSDIFF number')
    value=int.from_bytes(data,'little')&0x7fffffffffffffff
    return -value if data[7]&0x80 else value

def exact(stream,length):
    data=stream.read(length)
    if len(data)!=length:raise ValueError('Truncated BSDIFF stream')
    return data

def bspatch(source,delta,target):
    if len(delta)<32 or delta[:8]!=b'BSDIFF40':raise ValueError('Unsupported official delta format')
    control_length,diff_length,new_size=[number(delta[i:i+8]) for i in (8,16,24)]
    if min(control_length,diff_length,new_size)<0 or new_size>2**31 or 32+control_length+diff_length>len(delta):raise ValueError('Invalid official delta size')
    control=bz2.BZ2File(io.BytesIO(delta[32:32+control_length]));diff=bz2.BZ2File(io.BytesIO(delta[32+control_length:32+control_length+diff_length]));extra=bz2.BZ2File(io.BytesIO(delta[32+control_length+diff_length:]))
    position=0;old_position=0
    with Path(source).open('rb') as old,Path(target).open('wb') as out:
        old_size=os.fstat(old.fileno()).st_size
        mapping=mmap.mmap(old.fileno(),0,access=mmap.ACCESS_READ) if old_size else b''
        try:
            while position<new_size:
                add,insert,seek=[number(exact(control,8)) for _ in range(3)]
                if min(add,insert)<0 or position+add+insert>new_size or (add==insert==0 and seek==0):raise ValueError('Invalid delta control')
                remaining=add
                while remaining:
                    count=min(remaining,4*1024**2);array=np.frombuffer(exact(diff,count),dtype=np.uint8).copy()
                    a=max(0,-old_position);b=min(count,old_size-old_position)
                    if a<b:array[a:b]+=np.frombuffer(mapping,dtype=np.uint8,count=b-a,offset=old_position+a)
                    out.write(array.tobytes());old_position+=count;position+=count;remaining-=count
                remaining=insert
                while remaining:
                    count=min(remaining,4*1024**2);out.write(exact(extra,count));position+=count;remaining-=count
                old_position+=seek
        finally:
            if old_size:mapping.close()

def convert(client,launcher_data,expected_base_hash,check_hash,report):
    client=Path(client);check_hash(client/'isaac-ng.exe',expected_base_hash)
    # Capture the input list before creating its child so copytree cannot recurse.
    entries=[p for p in client.iterdir() if p.name not in ('Repentogon','mods','savedatapath.txt')]
    native=client/'Repentogon';native.mkdir()
    for p in entries:
        if p.is_dir():shutil.copytree(p,native/p.name)
        else:shutil.copy2(p,native/p.name)
    with zipfile.ZipFile(launcher_data) as z:
        manifest=json.loads(z.read('patch/manifest.json'))
        # Only the expected official conversion targets are accepted.
        allowed={'isaac-ng.exe','resources/packed/afterbirthp.a','resources/scripts/enums.lua','resources/scripts/json.lua','resources/scripts/main.lua'}
        paths={p.replace('\\','/').replace('//','/') for p in manifest['patch']}
        if paths!=allowed:raise ValueError('Official launcher delta manifest changed')
        for i,name in enumerate(sorted(paths)):
            report('应用官方 REPENTOGON 兼容补丁：'+name,int(i*100/len(paths)))
            target=native/name;temporary=target.with_name(target.name+'.patched')
            bspatch(target,z.read('patch/patches/'+name+'.patch'),temporary);temporary.replace(target)
        for name in manifest.get('delete',[]):
            if name!='EOSSDK-Win32-Shipping.dll':raise ValueError('Unexpected official deletion target')
            (native/name).unlink(missing_ok=True)
    (native/'.repentogon').touch();(native/'DONT RUN THE EXE DIRECTLY.txt').write_text('1');(native/'steam_appid.txt').write_text('250900')
    return native
