"""Loopback-only bridge. Arknights owns enemies; Isaac owns its player and items."""
import collections,json,math,socket,time,uuid,struct,hashlib
from PIL import Image
from pathlib import Path
import frida
from assets import animation as make_animation,ASSET_VERSION
from textures import texture_namespace
from transport import FrameReceiver

ROOT=Path(__file__).resolve().parent
TOOLS=ROOT/'tools'
EXPECTED=Path(r'D:\ArknightsLocal-Codex-20261103\client\Arknights.exe')
SKINS={}

def wire_snapshot(state,map_epoch,skin_token=None):
    """Repeat the static map until the client acknowledges this battle."""
    result=dict(state)
    token=state.get('mapToken',state.get('epoch'))
    if token and token==map_epoch:result.pop('tiles',None)
    if state.get('skinToken') and skin_token==state['skinToken']:
        result.pop('skinMeta',None);result.pop('skins',None)
    return result


def current_skins(state,isaac,skins):
    kinds={e['kind'] for e in [*state.get('enemies',[]),*state.get('characters',[])]}
    kinds.update('weapon_'+e['projectileKey'] for e in state.get('enemies',[]) if e.get('projectileKey'))
    kinds.update('weapon_'+a['nativeWeapon'] for a in isaac.get('entities',[]) if a.get('nativeWeapon'))
    return {kind:skins[kind] for kind in sorted(kinds) if kind in skins}

def install_art(kind,image):
    art=Path(r'D:\IsaacArknights-Codex\client\mods\isaac_arknights_bridge\resources\gfx\ark_enemies')
    art.mkdir(parents=True,exist_ok=True);w,h=image.size;name=f'{kind}_v{ASSET_VERSION}_{w}'
    image.save(art/f'{name}.png')
    pivot=(w/2,h/2) if kind.startswith('weapon_') else None
    (art/f'{name}.anm2').write_text(make_animation(name,w,h,pivot),encoding='utf-8')
    SKINS[kind]={'width':w,'height':h,'file':name,'pixelsPerUnit':h/1.8}

def damage_amount(amount,kind,defense,resistance,scale=100):
    amount=float(amount);defense=float(defense);resistance=float(resistance)
    if not all(math.isfinite(x) for x in (amount,defense,resistance,scale)) or amount<0:return 0
    raw=min(amount*scale,100_000_000)
    if kind=='arts':return raw*(1-min(95,max(0,resistance))/100)
    if kind=='true':return raw
    return max(raw*.05,raw-max(0,defense))

def recent_results(path,epoch):
    """Recover unacknowledged hits across a relay restart in the same battle."""
    try:
        with path.open('rb') as stream:
            stream.seek(0,2);length=stream.tell();stream.seek(max(0,length-2_000_000))
            records=stream.read().decode('utf-8',errors='replace').splitlines()
    except OSError:return collections.OrderedDict()
    result=collections.OrderedDict()
    for line in records:
        try:record=json.loads(line)
        except ValueError:continue
        if record.get('epoch')==epoch and record.get('id') and ('before' in record or 'rejected' in record):result[record['id']]=record
    while len(result)>4096:result.popitem(last=False)
    return result

def attach():
    session=frida.get_remote_device().attach('Gadget')
    guard=session.create_script('rpc.exports.path=()=>Process.mainModule.path;');guard.load()
    if Path(guard.exports_sync.path()).resolve()!=EXPECTED.resolve():
        session.detach();raise RuntimeError('Local Arknights copy not found')
    guard.unload()
    try:previous=json.loads((ROOT/'bridge-state.json').read_text(encoding='utf-8')).get('state',{})
    except (OSError,ValueError):previous={}
    agent=session.create_script('const priorStageEpoch='+json.dumps(previous.get('epoch'))+';const priorStageId='+json.dumps(previous.get('stage'))+';\n'+'\n'.join((TOOLS/name).read_text(encoding='utf-8') for name in ('probe.js','live.js','enemy_capture.js','status.js','graphics.js')))
    def message(m,data):
        if m.get('type')=='send' and m.get('payload',{}).get('type')=='enemy-image' and data:
            import re
            kind=re.sub('[^a-zA-Z0-9_-]','_',m['payload']['kind']);dest=ROOT/'enemy-images';dest.mkdir(exist_ok=True)
            matte=m['payload'].get('matte','black');(dest/f'{kind}.{matte}.png').write_bytes(data)
            if matte=='white':
                black=Image.open(dest/f'{kind}.black.png').convert('RGBA');white=Image.open(dest/f'{kind}.white.png').convert('RGBA')
                pixels=[]
                for b,w in zip(black.getdata(),white.getdata()):
                    alpha=max(0,min(255,255-round(sum(max(0,w[i]-b[i]) for i in range(3))/3)))
                    if alpha<5:pixels.append((0,0,0,0));continue
                    rgb=[min(1,max(0,b[i]/alpha)) for i in range(3)]
                    rgb=[round(255*(12.92*v if v<.0031308 else 1.055*v**(1/2.4)-.055)) for v in rgb]
                    pixels.append((*rgb,alpha))
                image=Image.new('RGBA',black.size);image.putdata(pixels);image.save(dest/f'{kind}.png')
                install_art(kind,image);print('Captured HD artwork:',kind,image.size,flush=True)
        else:print(m,flush=True)
    agent.on('message',message)
    agent.load();return session,agent

def main():
    for image_path in (ROOT/'enemy-images').glob('*.png'):
        if '.black' not in image_path.stem and '.white' not in image_path.stem:
            with Image.open(image_path) as image:install_art(image_path.stem,image)
    session,agent=attach()
    texture_dir=ROOT/'textures';texture_dir.mkdir(exist_ok=True);chunks={}
    udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',18731));udp.setblocking(False)
    udp.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,4_194_304);udp.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,4_194_304)
    if hasattr(socket,'SIO_UDP_CONNRESET'):udp.ioctl(socket.SIO_UDP_CONNRESET,False)
    session_id=uuid.uuid4().hex
    seen=collections.OrderedDict();pending={};peer=None;last_isaac=0;isaac={};last_save=0;last_send=0;last_epoch=None;isaac_native=None;isaac_session=None;last_attach=0;auto_paused=set()
    log=(ROOT/'events.jsonl').open('a',encoding='utf-8',buffering=1)
    last_status=0;owned_pause=None;capture_attempts={};last_connected=False;wire_frame=0;wire_session=int(session_id[:8],16);recovered=False
    state=agent.exports_sync.state();texture_acks=set();current_client=None;last_background=None;isaac_pid=0;native_info={};last_native_info=0
    last_input_key=None;last_input_send=0;frames=FrameReceiver();last_world_time=None;last_world_peer=None;last_ack_count=-1
    print('Bridge listening on loopback port 18731',flush=True)
    try:
        while not (ROOT/'stop.flag').exists():
            now=time.monotonic()
            if isaac_native is None and now-last_attach>1:
                last_attach=now
                try:
                    device=frida.get_device_manager().add_remote_device('127.0.0.1:27043');isaac_session=device.attach('Gadget')
                    native=isaac_session.create_script((TOOLS/'isaac_background.js').read_text(encoding='utf-8'));native.load()
                    if Path(native.exports_sync.path()).resolve()!=Path(r'D:\IsaacArknights-Codex\client\Repentogon\isaac-ng.exe').resolve():isaac_session.detach();raise RuntimeError('Unexpected Isaac process')
                    isaac_native=native;native_info=native.exports_sync.info();isaac_pid=native_info['pid'];last_background=None
                except Exception as error:isaac_native=None;native_info={'error':str(error)}
            epoch=state.get('epoch')
            if epoch!=last_epoch:
                seen.clear();pending.clear();last_epoch=epoch
                if epoch and not recovered:seen.update(recent_results(ROOT/'events.jsonl',epoch));recovered=True
            enemies={e['id']:e for e in state.get('enemies',[])}
            for e in [*state.get('characters',[]),*enemies.values()]:
                kind=e['kind'];dest=ROOT/'enemy-images'/f'{kind}.png'
                if SKINS.get(kind,{}).get('width',0)<512 and now-capture_attempts.get(kind,-100)>10:
                    capture_attempts[kind]=now;agent.exports_sync.capture(e['id']);break
            for e in enemies.values():
                key=e.get('projectileKey');kind='weapon_'+key if key else ''
                if key and kind not in SKINS and now-capture_attempts.get(kind,-100)>10:
                    capture_attempts[kind]=now;agent.exports_sync.enqueue([{'id':'weapon-'+key,'type':'captureProjectile','key':key}]);break
            if (ROOT/'pause-new-stages.flag').exists() and epoch and enemies and epoch not in auto_paused:
                auto_paused.add(epoch);agent.exports_sync.pause(True)
            batch=[];repeat_acks=[];new_player=None
            for _ in range(200):
                try:raw,address=udp.recvfrom(65507)
                except BlockingIOError:break
                except ConnectionResetError:continue
                if address[0]!='127.0.0.1':continue
                if raw.startswith(b'IAIM') and len(raw)>=16:
                    if current_client is None or address!=peer:continue
                    image_id,w,h,index,total=struct.unpack_from('<IHHHH',raw,4)
                    if not (0<image_id<100000 and 0<w<=512 and 0<h<=512 and 0<=index<total<=132):continue
                    key=(address,current_client,image_id,w,h,total);parts=chunks.setdefault(key,{})
                    parts[index]=raw[16:]
                    if len(parts)==total:
                        pixels=b''.join(parts[i] for i in range(total));chunks.pop(key,None)
                        if len(pixels)==w*h*4:
                            try:
                                folder=texture_dir/texture_namespace(current_client);folder.mkdir(exist_ok=True)
                                image=Image.frombytes('RGBA',(w,h),pixels);tmp=folder/f'{image_id}.tmp.png';image.save(tmp);tmp.replace(folder/f'{image_id}.png');texture_acks.add(image_id)
                            except OSError:pass
                    if len(chunks)>512:chunks.clear()
                    continue
                packet=frames.decode(raw,address,now)
                if packet is None:continue
                peer=address;last_isaac=now
                if packet.get('type')=='frame':
                    if current_client!=packet.get('client'):current_client=packet.get('client');texture_acks.clear();chunks.clear()
                    isaac=packet;new_player=packet.get('player',{})
                for event in packet.get('hits',[])[:100]:
                    if not isinstance(event,dict) or not isinstance(event.get('id'),str):continue
                    key=event['id']
                    if key in seen:repeat_acks.append(seen[key]);continue
                    if key in pending:continue
                    enemy=enemies.get(str(event.get('enemy')))
                    if not enemy or event.get('epoch')!=epoch:
                        seen[key]={'id':key,'rejected':'stale enemy or stage'};repeat_acks.append(seen[key]);continue
                    if event.get('life') is not None and event['life']!=enemy.get('life'):
                        seen[key]={'id':key,'rejected':'stale enemy life'};repeat_acks.append(seen[key]);continue
                    kind=event.get('kind','physical')
                    if kind not in ('physical','arts','true'):kind='physical'
                    try:amount=damage_amount(event.get('amount',0),kind,enemy['def'],enemy['resist'])
                    except (TypeError,ValueError):continue
                    req={'id':key,'enemy':enemy['id'],'epoch':epoch,'amount':amount,'damageType':{'physical':1,'arts':2,'true':3}[kind]}
                    if event.get('life') is not None:req['life']=event['life']
                    batch.append(req);pending[key]=now
            connected=now-last_isaac<2
            # The independent pause reason never clears the user's pause button.
            need_pause=bool(state.get('active') and peer and (not connected or isaac.get('player',{}).get('dead') or isaac.get('menuPaused')))
            pause_state=(epoch,need_pause)
            if pause_state!=owned_pause and epoch:
                agent.exports_sync.pause(need_pause,5);owned_pause=pause_state
            if connected and now-last_status>.2:
                last_status=now;agent.exports_sync.enqueue([{'type':'statuses','id':'statuses-'+str(time.time_ns()),'epoch':epoch,'items':isaac.get('statuses',[]) if state.get('active') else []}])
            elif not connected and last_connected:
                agent.exports_sync.enqueue([{'type':'statuses','id':'statuses-clear','epoch':epoch,'items':[]}])
            last_connected=connected
            exchange=agent.exports_sync.exchange(batch,new_player);state=exchange['state'];results=exchange['results'];current_input=exchange['input'];current_input['isaacFocus']=current_input.get('foregroundPid')==isaac_pid
            if peer:
                # Button edges bypass map fragmentation and slow picture/state
                # parsing. Sequence numbers stop older snapshots replacing them.
                input_key={k:v for k,v in current_input.items() if k!='sequence'}
                if input_key!=last_input_key or now-last_input_send>.05:
                    try:udp.sendto(json.dumps({'protocol':1,'input':current_input},separators=(',',':')).encode(),peer)
                    except OSError:pass
                    last_input_key=input_key;last_input_send=now
            state['skinMeta']=current_skins(state,isaac,SKINS);state['skins']=list(state['skinMeta'])
            state['skinToken']=hashlib.sha256(json.dumps(state['skinMeta'],sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]
            fresh_acks=[]
            for result in results:
                pending.pop(result['id'],None)
                if result['id'].startswith('statuses-') and 'error' not in result:continue
                result['epoch']=epoch;seen[result['id']]=result;fresh_acks.append(result);log.write(json.dumps(result,ensure_ascii=False)+'\n')
            if peer:
                # Receipts are sent when produced or explicitly retried. Repeating
                # 128 old hits in every state made Lua decoding dominate a frame.
                receipts=repeat_acks+fresh_acks
                for start in range(0,len(receipts),100):
                    try:udp.sendto(json.dumps({'protocol':1,'acks':receipts[start:start+100]},separators=(',',':')).encode(),peer)
                    except OSError:pass
            while len(seen)>4096:seen.popitem(last=False)
            # Development commands stay inside the same guarded local test copy.
            command=ROOT/'command.json'
            if command.exists():
                try:
                    event=json.loads(command.read_text(encoding='utf-8'))
                    if event.get('type')=='hit':
                        req={'id':'dev-'+uuid.uuid4().hex,'enemy':event['enemy'],'epoch':epoch,'amount':event['amount'],'damageType':1}
                        agent.exports_sync.hits([req])
                    elif event.get('type')=='capture':agent.exports_sync.capture(str(event['enemy']))
                    elif event.get('type')=='pause':agent.exports_sync.pause(bool(event['value']),event.get('key',0))
                    elif event.get('type')=='buffTest':agent.exports_sync.enqueue([dict(event,id='bufftest-'+uuid.uuid4().hex)])
                    elif event.get('type')=='visualProbe':agent.exports_sync.enqueue([dict(event,id='visual-probe')])
                    elif event.get('type')=='captureProjectile':agent.exports_sync.enqueue([dict(event,id='weapon-'+event['key'])])
                except (ValueError,KeyError,OSError) as error:log.write(json.dumps({'commandError':str(error)})+'\n')
                finally:command.unlink(missing_ok=True)
            if peer and now-last_send>.015 and (state.get('time')!=last_world_time or peer!=last_world_peer or len(texture_acks)!=last_ack_count or now-last_send>.1):
                last_send=now
                last_world_time=state.get('time');last_world_peer=peer;last_ack_count=len(texture_acks)
                if isaac_native:
                    try:
                        background=bool(state.get('active',False))
                        if background!=last_background:isaac_native.exports_sync.background(background);last_background=background
                    except Exception:isaac_native=None
                output={'protocol':1,'session':session_id,'state':wire_snapshot(state,isaac.get('mapToken',isaac.get('mapEpoch')),isaac.get('skinToken')),'input':current_input,'textureAcks':sorted(texture_acks)[-512:]}
                payload=json.dumps(output,separators=(',',':')).encode()
                try:
                    if len(payload)<=60000:udp.sendto(payload,peer)
                    else:
                        wire_frame=(wire_frame+1)&0xffffffff;count=math.ceil(len(payload)/48000)
                        if count<=128:
                            for i in range(count):udp.sendto(b'IAST'+struct.pack('<IIHH',wire_session,wire_frame,i,count)+payload[i*48000:(i+1)*48000],peer)
                except OSError:pass
            if now-last_save>.03:
                last_save=now
                if isaac_native and now-last_native_info>1:
                    last_native_info=now
                    try:native_info=isaac_native.exports_sync.info()
                    except Exception as error:
                        native_info={'error':str(error)};isaac_native=None;isaac_pid=0;last_background=None
                tmp=ROOT/'bridge-state.tmp.json'
                try:
                    tmp.write_text(json.dumps({'state':state,'textureNamespace':texture_namespace(current_client),'isaacConnected':now-last_isaac<2,'isaac':isaac,'isaacNative':native_info,'pending':len(pending),'results':list(seen.values())[-10:]},ensure_ascii=False),encoding='utf-8')
                    tmp.replace(ROOT/'bridge-state.json')
                except OSError:pass  # A Windows reader may briefly hold the file.
            time.sleep(.006)
    finally:
        try:
            if state.get('active'):
                agent.exports_sync.enqueue([{'type':'release','id':'bridge-release'}]);time.sleep(.15)
            if isaac_native:isaac_native.exports_sync.stop()
        except Exception:pass
        (ROOT/'stop.flag').unlink(missing_ok=True)
        udp.close();log.close();session.detach()
        if isaac_session:
            try:isaac_session.detach()
            except Exception:pass

if __name__=='__main__':main()
