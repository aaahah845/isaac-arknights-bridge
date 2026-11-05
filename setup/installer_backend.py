"""Install independent copies of user-owned clients; never patch sources."""
import contextlib,hashlib,json,lzma,os,shutil,subprocess,time,urllib.request,uuid,zipfile
from pathlib import Path,PurePosixPath
from settings import ROOT,read_state,write_state,manifest,HIDDEN
from materialize import generate
MARKER='.isaac-arknights-install.json'
SERVER_COMMIT='86099996610c3f3b5dc133bdf090e7c3848ee0fe'

def sha256(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def check_hash(path,expected):
    if not Path(path).is_file() or sha256(path)!=expected:
        raise RuntimeError('版本不匹配或文件不完整：'+str(path)+'。请使用说明中列出的游戏版本。')

def validate_target(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source==destination or source in destination.parents or destination in source.parents:
        raise ValueError('联动目录必须与官方游戏目录分开，不能互相包含。')
    if destination==ROOT or destination in ROOT.parents:
        raise ValueError('请选择单独的联动子目录，不能覆盖安装包。')
    if destination.exists():raise ValueError('目标目录已经存在，请选择新的目录。已有安装可直接打开启动入口。')
    return source,destination

def safe_extract(archive,destination,prefix=''):
    destination=Path(destination).resolve()
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            raw=entry.filename.replace('\\','/')
            if prefix and not raw.startswith(prefix):continue
            relative=raw[len(prefix):] if prefix else raw
            if not relative:continue
            parts=PurePosixPath(relative)
            if parts.is_absolute() or '..' in parts.parts or ':' in relative or ((entry.external_attr>>16)&0o170000)==0o120000:
                raise ValueError('下载包包含无效路径。')
            target=destination.joinpath(*parts.parts).resolve()
            if destination not in target.parents:raise ValueError('下载包路径越界。')
            if entry.is_dir():target.mkdir(parents=True,exist_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(entry) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst)

def download(url,target,expected,report):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_file() and sha256(target)==expected:return target
    report('下载所需组件……',0);temp=target.with_suffix('.download')
    try:
        request=urllib.request.Request(url,headers={'User-Agent':'IsaacArknightsInstaller/0.1'})
        with urllib.request.urlopen(request,timeout=40) as response,temp.open('wb') as out:
            total=int(response.headers.get('Content-Length',0));done=0
            while chunk:=response.read(1048576):
                out.write(chunk);done+=len(chunk)
                report('下载所需组件：'+str(done//1048576)+' MB',int(done*100/total) if total else 0)
        check_hash(temp,expected);temp.replace(target)
    finally:temp.unlink(missing_ok=True)
    return target

@contextlib.contextmanager
def installation_lock():
    import msvcrt
    with (ROOT/'install.lock').open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('另一个安装程序正在运行，请等它完成。')
        try:yield
        finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)

def ensure_server(report):
    data=manifest();server=ROOT/'work/OpenBachelorS'
    if not (server/'.component-ready').is_file():
        comp=data['components']['server'];archive=download(comp['url'],ROOT/'cache/server.zip',comp['sha256'],report)
        if server.exists():raise RuntimeError('服务端目录不完整，请重新解压安装包到新目录后安装。')
        temporary=ROOT/'work'/('server-'+uuid.uuid4().hex);temporary.mkdir(parents=True)
        try:
            safe_extract(archive,temporary,'OpenBachelorS-'+SERVER_COMMIT+'/')
            for name in ('res_en','res_2461','.github'):
                folder=temporary/name
                if folder.is_dir():shutil.rmtree(folder)
            patch=temporary/'src/openbachelors/bp/bp_rlv2.py';text=patch.read_text(encoding='utf-8')
            old='for stage_id, stage_obj in roguelike_topic_table["details"][self.theme_id][\n            "stages"\n        ]:'
            new='stage_entries = list(roguelike_topic_table["details"][self.theme_id]["stages"])\n        config = const_json_loader[CONFIG_JSON]\n        if self.theme_id == "rogue_4" and "quilon_quick_entry" in config and config["quilon_quick_entry"]:\n            stage_entries.sort(key=lambda entry: entry[0] != "ro4_b_7")\n        for stage_id, stage_obj in stage_entries:'
            if old not in text:raise RuntimeError('固定版本服务端补丁未匹配，请保留安装日志。')
            patch.write_text(text.replace(old,new,1),encoding='utf-8')
            conf=temporary/'conf/config.json';config=json.loads(conf.read_text(encoding='utf-8'))
            config.update(host='127.0.0.1',port=read_state()['ports']['server'],use_db=False,adaptive=True,multi_user=False,redirect_asset=False,debug=False,mod=False,assist_ext=True,faketime=-1,quilon_quick_entry=True)
            conf.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
            (temporary/'.component-ready').write_text(SERVER_COMMIT);temporary.rename(server)
        finally:
            if temporary.exists():shutil.rmtree(temporary)
    comp=data['components']['native'];download(comp['url'],ROOT/'work/components/native.js',comp['sha256'],report)

def copy_client(source,target,game,report):
    excluded_ark={'sdkdata','sdklogs','mmkv','CrashSightLog','HGEventLog_Encrypted','launcher_tmp'}
    excluded_isaac={'mods','data','Repentogon','tools','savedatapath.txt'};files=[]
    for parent,dirs,names in os.walk(source):
        parent=Path(parent);relative=parent.relative_to(source)
        if relative==Path('.'):
            exclude=excluded_ark if game=='arknights' else excluded_isaac;dirs[:]=[n for n in dirs if n not in exclude]
        dirs[:]=[n for n in dirs if not (parent/n).is_symlink() and not os.path.isjunction(parent/n)]
        for name in names:
            if name.lower().endswith(('.log','.dmp','.db')) or name=='savedatapath.txt':continue
            p=parent/name
            if not p.is_symlink():files.append((p,relative/name,p.stat().st_size))
    total=sum(size for _,_,size in files);extra=0
    if game=='isaac':
        extra=sum(p.stat().st_size for p in (source/'Repentogon').rglob('*') if p.is_file()) if (source/'Repentogon').is_dir() else total
    if shutil.disk_usage(target.parent).free<total+extra+1024**3:raise RuntimeError('空间不足，副本约需要 '+format((total+extra)/1024**3,'.1f')+' GB，另需预留 1 GB。')
    done=0
    for p,relative,size in files:
        out=target/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,out);done+=size
        report('复制独立客户端：'+format(done/1024**3,'.1f')+' / '+format(total/1024**3,'.1f')+' GB',int(done*100/max(1,total)))
    return total

def patch_gadget(library,archive,name,port):
    import lief
    library=Path(library);gadget=library.parent/name
    with lzma.open(archive) as stream:gadget.write_bytes(stream.read())
    gadget.with_suffix('.config').write_text(json.dumps({'interaction':{'type':'listen','address':'127.0.0.1','port':port,'on_load':'wait','on_port_conflict':'fail'}}),encoding='utf-8')
    original=library.with_suffix('.dll.original');shutil.copy2(library,original)
    binary=lief.PE.parse(str(original));entry=binary.add_import(name)
    entry.add_entry(next(e.name for e in lief.PE.parse(str(gadget)).exported_functions if 'application_query_options_deserialize' in e.name))
    options=lief.PE.Builder.config_t();options.imports=True;options.tls=False;binary.write(str(library),config=options)

def launcher_config(destination,stealth=True):
    client=destination/'client'
    text='[General]\nIsaacExecutable = '+str(client/'isaac-ng.exe')+'\nRanWizard = 1\nHideWindow = '+str(int(stealth))+'\nStealthMode = '+str(int(stealth))+'\n[Shared]\nLaunchMode = 1\n[Repentogon]\nUpdate = 0\nConsole = 0\nSkipUpdateMods = 1\nSkipWaitModDownloads = 1\n[Vanilla]\nLuaDebug = 1\nLuaHeapSize = 1024M\n'
    (destination/'launcher.ini').write_text(text,encoding='utf-8')

def runtime_alias(destination):
    # Isaac's ANSI mod enumeration fails on some Unicode paths. Only a private
    # copied game is mounted here; official resource directories are never linked.
    if str(destination).isascii():return destination
    import base64
    root=Path(os.environ.get('PROGRAMDATA',r'C:\ProgramData'))/'IsaacArknightsBridge'
    if not str(root).isascii():raise RuntimeError('系统 ProgramData 路径含非 ASCII 字符，请把以撒联动副本装到英文路径。')
    root.mkdir(parents=True,exist_ok=True);mount=root/uuid.uuid4().hex
    quote=lambda value:"'"+str(value).replace("'","''")+"'"
    code='New-Item -ItemType Junction -Path '+quote(mount)+' -Value '+quote(destination)+' -ErrorAction Stop | Out-Null'
    encoded=base64.b64encode(code.encode('utf-16-le')).decode('ascii')
    subprocess.run(['powershell.exe','-NoProfile','-EncodedCommand',encoded],check=True,capture_output=True,creationflags=HIDDEN)
    if mount.resolve()!=destination.resolve():raise RuntimeError('以撒兼容路径创建失败。')
    return mount

def validate_rgon(native):
    data=manifest()['isaac']
    for name,digest in {**data['nativeFiles'],**data.get('patchedFiles',{})}.items():check_hash(native/name,digest)

def prepare_rgon(source,destination,report):
    native=destination/'client/Repentogon'
    if (source/'Repentogon/isaac-ng.exe').is_file():
        report('检查并复制 REPENTOGON……',0);validate_rgon(source/'Repentogon')
        shutil.copytree(source/'Repentogon',native,ignore=shutil.ignore_patterns('*.log','*.dmp','savedatapath.txt','isaac-bridge-*','*.original'))
    else:
        from official_patch import convert
        comp=manifest()['components']['repentogon'];archive=download(comp['url'],ROOT/'cache/repentogon-1.1.3.zip',comp['sha256'],report)
        convert(destination/'client',ROOT/'components/repentogon/launcher-data.bin',manifest()['isaac']['baseExeSha256'],check_hash,report)
        safe_extract(archive,native)
    validate_rgon(native)
    for name in ('Binding of Isaac Repentance+','Binding of Isaac Repentance','Binding of Isaac Afterbirth+'):
        profile=destination/'profile'/name;profile.mkdir(parents=True,exist_ok=True)
        (profile/'options.ini').write_text('[Options]\nSteamCloud=0\nFullscreen=0\nWindowWidth=1000\nWindowHeight=650\nPauseOnFocusLost=0\nEnableMods=1\nEnableDebugConsole=1\nEosCrossplay=0\nMusicVolume=0.03\nSFXVolume=0.3\n',encoding='utf-8')
    launcher_config(destination)

def install(game,executable,destination,report=lambda message,percent:None):
    with installation_lock():return _install(game,executable,destination,report)

def _install(game,executable,destination,report):
    if game not in ('arknights','isaac'):raise ValueError('无效的安装类型。')
    executable=Path(executable).resolve();expected='Arknights.exe' if game=='arknights' else 'isaac-ng.exe'
    if executable.name.lower()!=expected.lower() or not executable.is_file():raise ValueError('请选择官方游戏目录中的 '+expected+'。')
    source,destination=validate_target(executable.parent,destination)
    if game in read_state()['games']:raise ValueError('本安装包已配置该游戏，请使用启动入口。重装时请解压到新目录。')
    report('验证客户端版本……',0);digests={}
    if game=='arknights':
        for name,digest in manifest()['arknights']['files'].items():check_hash(source/name,digest);digests[name]=digest
        if not (source/'Arknights_Data/StreamingAssets').is_dir():raise ValueError('方舟资源不完整，请先通过官方启动器完成下载。')
        resource=source/'Arknights_Data/PersistentData/Bundles/hot_update_list.json'
        if not resource.is_file():resource=source/'Arknights_Data/StreamingAssets/AB/Windows/hot_update_list.json'
        if json.loads(resource.read_text(encoding='utf-8')).get('versionId')!=manifest()['arknights']['resourceVersion']:
            raise ValueError('方舟资源版本不匹配，请使用说明中列出的资源版本。')
        ensure_server(report)
    elif not (source/'resources').is_dir():raise ValueError('请选择安装完整的 Steam 以撒客户端。')
    elif not (source/'Repentogon/isaac-ng.exe').is_file():check_hash(executable,manifest()['isaac']['baseExeSha256'])
    destination.parent.mkdir(parents=True,exist_ok=True)
    old_state=read_state();runtime=destination
    staging=destination.parent/(destination.name+'.installing-'+uuid.uuid4().hex);staging.mkdir();committed=False
    (staging/MARKER).write_text(json.dumps({'game':game,'source':str(source)}),encoding='utf-8')
    try:
        size=copy_client(source,staging/'client',game,report)
        if game=='isaac':
            prepare_rgon(source,staging,report)
            patch_gadget(staging/'client/Repentogon/libcurl.dll',ROOT/'payload/gadget-x86.dll.xz','isaac-bridge-gadget.dll',read_state()['ports']['isaac'])
        else:
            (staging/'userdata/Hypergryph/Arknights').mkdir(parents=True)
            patch_gadget(staging/'client/hgdownloadsdk.dll',ROOT/'payload/gadget-x64.dll.xz','florida-17.9.1.dll',read_state()['ports']['pc'])
        staging.rename(destination);committed=True
        runtime=runtime_alias(destination) if game=='isaac' else destination
        if game=='isaac':launcher_config(runtime)
        state=read_state();state['games'][game]={'source':str(source),'destination':str(destination),'runtimeDestination':str(runtime),'sourceHashes':digests,'shared':[],'copiedBytes':size}
        write_state(state);generate()
        if game=='isaac':shutil.copytree(ROOT/'work/isaac-arknights/mod',destination/'client/mods/isaac_arknights_bridge',dirs_exist_ok=True)
        report('安装完成。两个游戏安装好后，打开“03-启动联动”。',100);return state['games'][game]
    except Exception:
        if committed:
            write_state(old_state)
            with contextlib.suppress(Exception):generate()
            if runtime!=destination and runtime.is_junction() and runtime.resolve()==destination.resolve():os.rmdir(runtime)
            if destination.parent==staging.parent and (destination/MARKER).is_file():shutil.rmtree(destination)
        raise
    finally:
        if not committed and staging.exists() and staging.parent==destination.parent and (staging/MARKER).is_file():shutil.rmtree(staging)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('game',choices=['arknights','isaac']);parser.add_argument('executable');parser.add_argument('destination')
    args=parser.parse_args();install(args.game,args.executable,args.destination,lambda m,p:print(str(p)+'% '+m,flush=True))
