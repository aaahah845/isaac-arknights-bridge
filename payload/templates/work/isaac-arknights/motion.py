"""Render native 30 Hz poses smoothly without changing gameplay positions."""
from collections import deque
import math


class Motion:
    def __init__(self, delay=.055, extrapolation=.05):
        self.delay=delay
        self.extrapolation=extrapolation
        self.client=None
        self.tracks={}
        self.frames=deque(maxlen=8)
        self.visual_revision=None

    @staticmethod
    def key(actor):
        if actor.get('part'):return actor.get('type'),actor.get('id'),actor['part']
        if actor.get('costume'):return actor.get('type'),actor.get('id'),'costume',actor.get('costumeIndex',0)
        return actor.get('type'),actor.get('id')

    def ingest(self, packet):
        if packet.get('client')!=self.client:
            self.client=packet.get('client');self.tracks.clear();self.frames.clear()
        stamp=packet.get('visualPoseAt',packet.get('poseAt',packet.get('sentAt',0)))
        if self.frames and stamp<=self.frames[-1][0]:
            if stamp==self.frames[-1][0] and (packet.get('paused') or (packet.get('visualRevision') is not None and packet['visualRevision']!=self.visual_revision)):
                self.frames[-1]=(stamp,packet.get('entities',[]))
                self.visual_revision=packet.get('visualRevision')
                for actor in packet.get('entities',[]):
                    track=self.tracks.setdefault(self.key(actor),deque(maxlen=8))
                    pose=(stamp,actor['x'],actor['y'],actor.get('vx',0),actor.get('vy',0),actor)
                    if track and track[-1][0]==stamp:track[-1]=pose
                    elif not track:track.append(pose)
            return
        self.visual_revision=packet.get('visualRevision')
        self.frames.append((stamp,packet.get('entities',[])))
        for actor in packet.get('entities',[]):
            key=self.key(actor)
            track=self.tracks.setdefault(key,deque(maxlen=8))
            if track and stamp<=track[-1][0]:continue
            x,y=actor['x'],actor['y']
            if track and math.hypot(x-track[-1][1],y-track[-1][2])>3:track.clear()
            track.append((stamp,x,y,actor.get('vx',0),actor.get('vy',0),actor))
        retained={self.key(a) for _,actors in self.frames for a in actors}
        for key in self.tracks.keys()-retained:del self.tracks[key]

    def actors(self, now, paused=False):
        """Delay appearance/disappearance by the same amount as movement."""
        if not self.frames:return []
        if paused:return self.frames[-1][1]
        target=now-self.delay;chosen=self.frames[0][1]
        for stamp,actors in self.frames:
            if stamp>target:break
            chosen=actors
        return chosen

    def offsets(self, actor, now, paused=False):
        values=actor.get('offsetX',0),actor.get('height',0)
        if paused:return values
        track=self.tracks.get(self.key(actor))
        if not track:return values
        target=now-self.delay;left=track[0]
        for right in list(track)[1:]:
            if target<=right[0]:
                ratio=max(0,min(1,(target-left[0])/(right[0]-left[0])))
                return tuple(left[5].get(k,0)+(right[5].get(k,0)-left[5].get(k,0))*ratio for k in ('offsetX','height'))
            left=right
        return left[5].get('offsetX',0),left[5].get('height',0)

    def presentation(self,actor,now,paused=False):
        """Keep weapon angles and owner-relative mounts on the pose timeline."""
        if paused:return actor
        track=self.tracks.get(self.key(actor))
        if not track:return actor
        target=now-self.delay;left=track[0];right=left;ratio=0
        for right in list(track)[1:]:
            if target<=right[0]:
                ratio=max(0,min(1,(target-left[0])/(right[0]-left[0])));break
            left=right
        else:
            right=left
            if len(track)>1 and target>left[0]:
                left=track[-2];right=track[-1]
                ratio=1+min(self.extrapolation,target-right[0])/(right[0]-left[0])
        a,b=left[5],right[5];result=dict(actor)
        start,end=a.get('rotation',0),b.get('rotation',0)
        result['rotation']=start+((end-start+180)%360-180)*ratio
        for key in ('scaleX','scaleY','renderDepth'):
            if key in a and key in b:result[key]=a[key]+(b[key]-a[key])*min(1,ratio)
        aa,bb=a.get('attachment'),b.get('attachment')
        if aa and bb and (aa['id'],aa['type'])==(bb['id'],bb['type']):
            result['attachment']=dict(aa)
            for key in ('x','y','localX','localY','travelX','travelY'):
                result['attachment'][key]=aa.get(key,0)+(bb.get(key,0)-aa.get(key,0))*ratio
        return result

    def position(self, actor, now, paused=False):
        if paused:return actor['x'],actor['y']
        track=self.tracks.get(self.key(actor))
        if not track:return actor['x'],actor['y']
        target=now-self.delay
        left=track[0]
        if target<=left[0]:return left[1:3]
        for right in list(track)[1:]:
            if target<=right[0]:
                ratio=(target-left[0])/(right[0]-left[0])
                return left[1]+(right[1]-left[1])*ratio,left[2]+(right[2]-left[2])*ratio
            left=right
        age=min(self.extrapolation,max(0,target-left[0]))
        return left[1]+left[3]*age,left[2]+left[4]*age
