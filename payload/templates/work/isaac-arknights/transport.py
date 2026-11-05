"""Bounded assembly and ordering of complete native visual snapshots."""
import json,struct


class SnapshotCache:
    """A transient replace/read failure keeps the last complete picture."""
    def __init__(self):self.data={};self.stamp=None;self.read_at=0

    def refresh(self,path,now):
        try:
            stamp=path.stat().st_mtime_ns
            if stamp==self.stamp:return False
            data=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):return False
        self.data=data;self.stamp=stamp;self.read_at=now;return True

    def fresh(self,now):return bool(self.data) and now-self.read_at<2


class FrameReceiver:
    def __init__(self):
        self.parts={};self.latest={};self.visuals={}

    def decode(self,raw,address,now):
        for key,value in list(self.parts.items()):
            if now-value['at']>.5:del self.parts[key]
        if raw.startswith(b'IAFR'):
            if len(raw)<17:return None
            session,sequence,index,total=struct.unpack_from('<IIHH',raw,4)
            if not (0<=index<total<=128 and len(raw)-16<=48000):return None
            key=address,session,sequence
            record=self.parts.setdefault(key,{'at':now,'total':total,'chunks':{}})
            if record['total']!=total:return None
            record['chunks'].setdefault(index,raw[16:])
            if len(self.parts)>8:
                oldest=min(self.parts,key=lambda k:self.parts[k]['at']);del self.parts[oldest]
                if oldest==key:return None
            if len(record['chunks'])!=total:return None
            raw=b''.join(record['chunks'][i] for i in range(total));del self.parts[key]
        try:packet=json.loads(raw)
        except (ValueError,UnicodeError):return None
        if not isinstance(packet,dict) or packet.get('protocol')!=1:return None
        if packet.get('type')=='frame':
            sequence=packet.get('wireSequence',packet.get('frame'))
            key=address,packet.get('client')
            old=self.latest.get(key)
            if isinstance(sequence,int):
                if old is not None and ((sequence-old)&0xffffffff)>=0x80000000:return None
                if old==sequence:return None
            if 'entityStyles' in packet:
                styles=packet.pop('entityStyles');expanded=[]
                if not isinstance(styles,list) or not isinstance(packet.get('entities'),list):return None
                for actor in packet['entities']:
                    index=actor.get('s')
                    if not isinstance(index,int) or not 1<=index<=len(styles):return None
                    expanded.append(dict(styles[index-1],**{k:v for k,v in actor.items() if k!='s'}))
                packet['entities']=expanded
            if 'visualReference' in packet:
                cached=self.visuals.get(key)
                if not cached or cached[0]!=packet['visualReference']:return None
                packet['entities']=cached[1]
            elif 'entities' in packet:
                self.visuals[key]=(packet.get('visualRevision'),packet['entities'])
            if isinstance(sequence,int):
                self.latest[key]=sequence
            if len(self.latest)>32:
                self.latest={key:sequence};self.visuals={key:self.visuals[key]} if key in self.visuals else {}
        return packet
