"""Click-through local overlay using the live sprite pixels exported by Isaac."""
import ctypes as C,json,math,os,sys,time,cProfile
from ctypes import wintypes as W
from pathlib import Path
from motion import Motion
from rendering import SpriteImages,draw_laser,render_order,stage_actor,STAGE_DISPLAY_SCALE
from placement import Placements
from transport import SnapshotCache
from hud import draw_hud
os.environ.setdefault('QT_SCALE_FACTOR','1')
from PySide6.QtCore import Qt,QTimer,QPointF,QRectF
from PySide6.QtGui import QPainter,QImage,QTransform,QPolygonF,QColor,QFont,QPen,QPainterPath
from PySide6.QtWidgets import QApplication,QWidget

ROOT=Path(__file__).resolve().parent
u=C.windll.user32;u.SetProcessDPIAware()
u.GetForegroundWindow.restype=W.HWND
u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
u.GetClientRect.argtypes=[W.HWND,C.POINTER(W.RECT)];u.ClientToScreen.argtypes=[W.HWND,C.POINTER(W.POINT)]
u.GetWindow.argtypes=[W.HWND,W.UINT];u.GetWindow.restype=W.HWND

class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.WindowTransparentForInput|Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground);self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.hardware=False;self.setup()
    def setup(self):
        self.data={};self.images={};self.sprites=SpriteImages(ROOT/'textures');self.client=None;self.snapshots=SnapshotCache();self.motion=Motion();self.measuring=False;self.measurements=[];self.paintSamples=[];self.worldBuffer=None;self.lowResolutionWorld=False;self.profiler=None
        self.pid=int((ROOT.parent/'pc-game.pid').read_text());self.window=None
        @C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        def cb(h,p):
            pid=W.DWORD();u.GetWindowThreadProcessId(h,C.byref(pid))
            if pid.value==self.pid:
                name=C.create_unicode_buffer(256);u.GetClassNameW(h,name,256)
                if name.value=='UnityWndClass':self.window=h
            return True
        u.EnumWindows(cb,0)
        self.timer=QTimer(self);self.timer.setTimerType(Qt.PreciseTimer);self.timer.timeout.connect(self.tick);self.timer.start(16)
    def tick(self):
        try:
            measuring=(ROOT/'measure-overlay.flag').exists()
            if self.measuring and not measuring:
                if self.profiler:self.profiler.disable();self.profiler.dump_stats(str(ROOT/'overlay-profile.stats'));self.profiler=None
                (ROOT/'overlay-samples.json').write_text(json.dumps(self.measurements),encoding='utf-8')
                (ROOT/'overlay-paint-samples.json').write_text(json.dumps(self.paintSamples),encoding='utf-8')
            if measuring and not self.measuring:
                self.measurements=[];self.paintSamples=[]
                if (ROOT/'profile-overlay.flag').exists():self.profiler=cProfile.Profile();self.profiler.enable()
            self.measuring=measuring
            state_file=ROOT/'bridge-state.json'
            if self.snapshots.refresh(state_file,time.time()):
                self.data=self.snapshots.data;self.motion.ingest(self.data.get('isaac',{}))
            foreground=u.GetForegroundWindow();pid=W.DWORD();u.GetWindowThreadProcessId(foreground,C.byref(pid))
            owner_pid=W.DWORD();owner=u.GetWindow(foreground,4)
            if owner:u.GetWindowThreadProcessId(owner,C.byref(owner_pid))
            visible=(pid.value==self.pid or owner_pid.value==self.pid) and self.data.get('state',{}).get('active') and self.data.get('isaacConnected') and self.snapshots.fresh(time.time())
            if not visible:self.hide();return
            r=W.RECT();p=W.POINT();u.GetClientRect(self.window,C.byref(r));u.ClientToScreen(self.window,C.byref(p))
            ratio=self.devicePixelRatioF();self.setGeometry(round(p.x/ratio),round(p.y/ratio),round(r.right/ratio),round(r.bottom/ratio))
            self.show();self.update()
        except (OSError,ValueError,KeyError):self.hide()
    def paintEvent(self,event):
        self.drawFrame()
    def drawFrame(self):
        started=time.perf_counter() if self.measuring else 0
        state=self.data.get('state',{});isaac=self.data.get('isaac',{})
        if 'corners' not in state:return
        source=QPolygonF([QPointF(0,0),QPointF(state['width'],0),QPointF(state['width'],state['height']),QPointF(0,state['height'])])
        destination=QPolygonF([QPointF(c['x'],c['y']) for c in state['corners']]);transform=QTransform()
        if not QTransform.quadToQuad(source,destination,transform):return
        identity=isaac.get('client'),self.data.get('textureNamespace')
        if self.client!=identity:
            self.client=identity;self.images.clear();self.sprites=SpriteImages(ROOT/'textures'/self.data.get('textureNamespace',''))
        render_at=time.time()
        paused=state.get('paused') or isaac.get('paused')
        actors=[self.motion.presentation(a,render_at,paused) for a in self.motion.actors(render_at,paused)]
        if len(actors)>=80:self.lowResolutionWorld=True
        elif len(actors)<48:self.lowResolutionWorld=False
        factor=.5 if self.lowResolutionWorld and not self.hardware else 1
        w=max(1,round(self.width()*self.devicePixelRatioF()*factor));h=max(1,round(self.height()*self.devicePixelRatioF()*factor))
        if self.hardware:painter=QPainter(self);painter.scale(self.width()/state['screenWidth'],self.height()/state['screenHeight'])
        else:
            if self.worldBuffer is None or self.worldBuffer.width()!=w or self.worldBuffer.height()!=h:self.worldBuffer=QImage(w,h,QImage.Format_ARGB32_Premultiplied)
            self.worldBuffer.fill(0);painter=QPainter(self.worldBuffer);painter.scale(w/state['screenWidth'],h/state['screenHeight'])
        painter.setRenderHint(QPainter.SmoothPixmapTransform,False)
        placements=Placements(actors,lambda a:self.motion.position(a,render_at,paused),STAGE_DISPLAY_SCALE)
        laser_ms=0;knife_rotations=[];draw_started=time.perf_counter() if self.measuring else 0
        for actor in sorted(actors,key=render_order):
            offset_x,height=self.motion.offsets(actor,render_at,paused)
            actor=stage_actor(dict(placements.actor(actor),offsetX=offset_x,height=height));x,y=actor['x'],actor['y'];offset_x=actor.get('offsetX',0);height=actor.get('height',0)
            if self.measuring and actor.get('type')==8:knife_rotations.append(round(actor.get('rotation',0),3))
            if self.measuring and actor.get('type')==1 and not actor.get('costume') and not actor.get('part') and len(self.measurements)<3000:
                self.measurements.append({'t':render_at,'x':x,'y':y,'rawX':actor['x'],'rawY':actor['y'],'paused':state.get('paused',False)})
            x+=.5;y+=.5;pos=transform.map(QPointF(x,y));other=transform.map(QPointF(x+1,y))
            scale=math.hypot(other.x()-pos.x(),other.y()-pos.y())/max(1,isaac.get('spritePixelsPerTile',isaac.get('pixelsPerTile',30)))
            if actor.get('nativeWeapon'):
                kind='weapon_'+actor['nativeWeapon'];meta=state.get('skinMeta',{}).get(kind)
                if meta:
                    identity='weapon:'+meta['file'];picture=self.images.get(identity)
                    if picture is None:
                        path=ROOT/'enemy-images'/f'{kind}.png'
                        if path.exists():picture=QImage(str(path));self.images[identity]=picture
                    if picture is not None and not picture.isNull():
                        size=math.hypot(other.x()-pos.x(),other.y()-pos.y())/meta.get('pixelsPerUnit',meta['width']*.78)
                        painter.save();painter.setRenderHint(QPainter.SmoothPixmapTransform,True);painter.translate(pos.x()+offset_x*scale,pos.y()+height*scale);painter.scale(size,size);painter.drawImage(QPointF(-picture.width()/2,-picture.height()/2),picture);painter.restore()
                else:
                    painter.save();painter.setPen(Qt.NoPen);painter.setBrush(QColor(255,153,38));painter.drawRect(QRectF(pos.x()+(offset_x-2)*scale,pos.y()+(height-2)*scale,4*scale,4*scale));painter.restore()
                continue
            if len(actor.get('beam',[]))>=2:
                laser_started=time.perf_counter() if self.measuring else 0
                draw_laser(painter,dict(actor,height=height,offsetX=offset_x),transform,max(1,isaac.get('spritePixelsPerTile',isaac.get('pixelsPerTile',30))),self.sprites)
                if self.measuring:laser_ms+=(time.perf_counter()-laser_started)*1000
                continue
            painter.save();painter.translate(pos.x()+offset_x*scale,pos.y()+height*scale)
            painter.scale(scale*actor.get('scaleX',actor.get('scale',1))*(-1 if actor.get('flipX') else 1),scale*actor.get('scaleY',actor.get('scale',1))*(-1 if actor.get('flipY') else 1));painter.rotate(actor.get('rotation',0))
            self.sprites.layers(painter,actor.get('layers',[]))
            painter.restore()
        if not self.hardware:
            painter.end();painter=QPainter(self);painter.setRenderHint(QPainter.SmoothPixmapTransform,False)
            painter.drawImage(QRectF(0,0,self.width(),self.height()),self.worldBuffer)
            painter.scale(self.width()/state['screenWidth'],self.height()/state['screenHeight'])
        reference=isaac.get('screenSize',[640,480]);screen_scale=min(state['screenWidth']/max(1,reference[0]),state['screenHeight']/max(1,reference[1]))
        for effect in isaac.get('screenEffects',[]):
            painter.save();painter.translate(state['screenWidth']/2+effect.get('offsetX',0)*screen_scale,state['screenHeight']/2+effect.get('offsetY',0)*screen_scale)
            painter.scale(screen_scale*effect.get('scaleX',1),screen_scale*effect.get('scaleY',1));painter.rotate(effect.get('rotation',0))
            self.sprites.layers(painter,effect.get('layers',[]));painter.restore()
        draw_hud(painter,isaac,self.sprites,state['screenWidth'],state['screenHeight'])
        if self.measuring:self.paintSamples.append({'t':render_at,'ms':(time.perf_counter()-started)*1000,'drawMs':(time.perf_counter()-draw_started)*1000,'laserMs':laser_ms,'actors':len(actors),'worldScale':factor,'knifeRotations':knife_rotations})

if __name__=='__main__':
    app=QApplication(sys.argv)
    if (ROOT/'gpu-overlay.flag').exists():
        from overlay_gpu import GpuOverlay
        overlay=GpuOverlay()
    else:overlay=Overlay()
    sys.exit(app.exec())
