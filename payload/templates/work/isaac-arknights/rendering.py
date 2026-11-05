"""Draw exported native sprite pixels and textured laser paths."""
from collections import OrderedDict
import math
from pathlib import Path
from PIL import Image
from PySide6.QtCore import QPointF,QRectF,Qt
from PySide6.QtGui import QImage,QPolygonF,QTransform,QPainterPath

STAGE_DISPLAY_SCALE=.55
NATIVE_STAGE_TYPES={1,2,3,4,5,7,8,9,1000}


def stage_actor(actor):
    """Use one stage scale for Isaac characters, pickups, weapons and effects."""
    result=dict(actor)
    if actor.get('type') in NATIVE_STAGE_TYPES and not actor.get('nativeWeapon'):
        result['scaleX']=actor.get('scaleX',actor.get('scale',1))*STAGE_DISPLAY_SCALE
        result['scaleY']=actor.get('scaleY',actor.get('scale',1))*STAGE_DISPLAY_SCALE
        result['height']=actor.get('height',0)*STAGE_DISPLAY_SCALE
        result['offsetX']=actor.get('offsetX',0)*STAGE_DISPLAY_SCALE
        beam=actor.get('beam');unit=actor.get('beamWorldUnitsPerTile')
        if beam and unit and not actor.get('beamClosed'):
            # The native body begins ahead of its cap. Its mounting distance
            # must shrink with the cap, while the far end keeps its hit point.
            dx,dy=beam[0]['x']-actor['x'],beam[0]['y']-actor['y']
            lead=math.hypot(dx,dy)*unit
            if lead>1e-6:
                result['beam']=[];distance=0;last=None
                for sample in beam:
                    blend=max(0,1-sample.get('d',0)/lead)*(1-STAGE_DISPLAY_SCALE)
                    x,y=sample['x']-dx*blend,sample['y']-dy*blend
                    if last:distance+=math.hypot(x-last[0],y-last[1])*unit
                    result['beam'].append(dict(sample,x=x,y=y,d=distance));last=x,y
    return result


def render_order(actor):
    return actor.get('renderDepth',-actor.get('y',0)*30),actor.get('renderOrder',1 if actor.get('costume') else 0)


def tinted(picture,color=(1,1,1,1,0,0,0),colorize=(0,0,0,0)):
    """Native multiplicative tint, additive offset, alpha and colorization."""
    values=list(color)+[0]*7;r,g,b,a,ro,go,bo=values[:7]
    picture=picture.convert('RGBA');channels=picture.split()
    if colorize[3]:
        gray=picture.convert('L');amount=max(0,min(1,colorize[3]))
        channels=tuple(Image.blend(channels[i],gray.point(lambda v,i=i:round(v*colorize[i])),amount) for i in range(3))+(channels[3],)
    result=[channel.point([max(0,min(255,round(v*factor+255*offset))) for v in range(256)]) for channel,factor,offset in zip(channels,(r,g,b,a),(ro,go,bo,0))]
    return Image.merge('RGBA',result)


class SpriteImages:
    def __init__(self,root):
        self.root=Path(root);self.originals=OrderedDict();self.cache=OrderedDict();self.trimmed={}

    def clear(self):self.originals.clear();self.cache.clear();self.trimmed.clear()

    def image(self,layer):
        identity=layer['image'];color=tuple(layer.get('color',(1,1,1,1,0,0,0)))
        colorize=tuple(layer.get('colorize',(0,0,0,0)))
        crop=layer.get('sourceX',0),layer.get('sourceY',0),layer.get('w'),layer.get('h')
        key=identity,crop,color,colorize
        if key in self.cache:self.cache.move_to_end(key);return self.cache[key]
        if identity not in self.originals:
            path=self.root/f'{int(identity)}.png'
            if not path.exists():return None
            with Image.open(path) as source:self.originals[identity]=source.convert('RGBA')
            if len(self.originals)>512:self.originals.popitem(last=False)
        original=self.originals[identity]
        if crop[2] is not None:original=original.crop((crop[0],crop[1],crop[0]+crop[2],crop[1]+crop[3]))
        pic=tinted(original,color,colorize);raw=pic.tobytes()
        result=QImage(raw,pic.width,pic.height,pic.width*4,QImage.Format_RGBA8888).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        box=pic.getchannel('A').getbbox()
        self.trimmed[result.cacheKey()]=(result.copy(box[0],box[1],box[2]-box[0],box[3]-box[1]),box[0],box[1]) if box else (None,0,0)
        self.cache[key]=result
        if len(self.cache)>512:
            _,old=self.cache.popitem(last=False);self.trimmed.pop(old.cacheKey(),None)
        return result

    def layers(self,painter,layers):
        for layer in layers:
            image=self.image(layer)
            if image is None:continue
            image,x,y=self.trimmed.get(image.cacheKey(),(image,0,0))
            if image is None:continue
            painter.save();painter.translate(layer.get('x',0),layer.get('y',0));painter.rotate(layer.get('rotation',0))
            painter.scale(layer.get('sx',1)*(-1 if layer.get('flipX') else 1),layer.get('sy',1)*(-1 if layer.get('flipY') else 1))
            painter.drawImage(QPointF(x-layer.get('px',0),y-layer.get('py',0)),image);painter.restore()


def laser_body(layers):
    return next((layer for layer in layers if layer.get('name','').lower() in ('laser','body')),None)


def laser_quads(points,period,widths):
    """Continuous arc-length UVs; adjacent quads share their edge vertices."""
    if len(points)<2 or period<=0 or not math.isfinite(period):return []
    if len(widths)!=len(points) or not all(math.isfinite(v) for p in points for v in p) or not all(math.isfinite(v) and v>=0 for v in widths):return []
    normals=[]
    closed=len(points)>2 and math.hypot(points[0][0]-points[-1][0],points[0][1]-points[-1][1])<.01
    for i,p in enumerate(points):
        a=points[-2] if closed and i==0 else points[max(0,i-1)]
        b=points[1] if closed and i==len(points)-1 else points[min(len(points)-1,i+1)]
        dx,dy=b[0]-a[0],b[1]-a[1];length=max(1e-6,math.hypot(dx,dy))
        normals.append((dy/length,-dx/length))
    quads=[]
    for i,(a,b) in enumerate(zip(points,points[1:])):
        span=b[2]-a[2]
        if span<=1e-6:continue
        # Integer wrap boundaries avoid a zero-progress floating-point loop
        # when a long segment lands just below the next texture period.
        cuts=[0]+[k*period-a[2] for k in range(math.floor(a[2]/period)+1,math.ceil(b[2]/period))]+[span]
        for offset,end in zip(cuts,cuts[1:]):
            length=end-offset
            if length<=1e-8:continue
            phase=(a[2]+offset)%period
            if phase<1e-7 or period-phase<1e-7:phase=0
            ends=[]
            for d in (offset,offset+length):
                t=d/span;x=a[0]+(b[0]-a[0])*t;y=a[1]+(b[1]-a[1])*t
                nx=normals[i][0]+(normals[i+1][0]-normals[i][0])*t;ny=normals[i][1]+(normals[i+1][1]-normals[i][1])*t
                half=(widths[i]+(widths[i+1]-widths[i])*t)/2
                ends.append(((x+nx*half,y+ny*half),(x-nx*half,y-ny*half)))
            quads.append((phase,length,[ends[0][0],ends[0][1],ends[1][1],ends[1][0]]))
    return quads


def draw_strip(painter,picture,phase,length,quad,source_per_unit):
    """Use bounded convex patches or clipped affine triangles for tight folds."""
    w,h=picture.width(),length*source_per_unit
    if w<=0 or h<=1e-8:return
    source=[(0,0),(w,0),(w,h),(0,h)]
    turns=[]
    for i in range(4):
        a,b,c=quad[i],quad[(i+1)%4],quad[(i+2)%4]
        turns.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
    if all(v>1e-8 for v in turns) or all(v<-1e-8 for v in turns):
        warp=QTransform()
        if QTransform.quadToQuad(QPolygonF([QPointF(*v) for v in source]),QPolygonF([QPointF(*v) for v in quad]),warp):
            den=[warp.m13()*x+warp.m23()*y+warp.m33() for x,y in source]
            # A convex patch whose denominator keeps its sign has no pole.
            if min(den)>1e-7 or max(den)<-1e-7:
                xs=[p[0] for p in quad];ys=[p[1] for p in quad]
                painter.save();painter.setClipRect(QRectF(min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)),Qt.IntersectClip)
                painter.setWorldTransform(warp,True)
                painter.drawImage(QRectF(0,0,w,h),picture,QRectF(0,phase*source_per_unit,w,h));painter.restore();return
    for indices in ((0,1,2),(0,2,3)):
        a,b,c=[source[i] for i in indices];p,q,r=[quad[i] for i in indices]
        ax,ay=b[0]-a[0],b[1]-a[1];bx,by=c[0]-a[0],c[1]-a[1];det=ax*by-ay*bx
        px,py=q[0]-p[0],q[1]-p[1];qx,qy=r[0]-p[0],r[1]-p[1]
        if abs(det)<1e-8 or abs(px*qy-py*qx)<1e-8:continue
        xx,yx=(px*by-qx*ay)/det,(qx*ax-px*bx)/det
        xy,yy=(py*by-qy*ay)/det,(qy*ax-py*bx)/det
        warp=QTransform(xx,xy,yx,yy,p[0]-xx*a[0]-yx*a[1],p[1]-xy*a[0]-yy*a[1])
        clip=QPainterPath();clip.addPolygon(QPolygonF([QPointF(*v) for v in (p,q,r)]));clip.closeSubpath()
        painter.save();painter.setClipPath(clip,Qt.IntersectClip);painter.setWorldTransform(warp,True)
        painter.drawImage(QRectF(0,0,w,h),picture,QRectF(0,phase*source_per_unit,w,h));painter.restore()


def draw_laser(painter,actor,transform,pixels_per_tile,images):
    layers=actor.get('beamLayers',[]);body=laser_body(layers)
    if not body or len(actor.get('beam',[]))<2:return False
    picture=images.image(body)
    if picture is None:return False
    if body.get('flipX') or body.get('flipY'):
        picture=picture.flipped((Qt.Horizontal if body.get('flipX') else Qt.Orientation(0))|(Qt.Vertical if body.get('flipY') else Qt.Orientation(0)))
    horizontal=actor.get('laserVariant')==4
    if horizontal:picture=picture.transformed(QTransform().rotate(90))
    points=[];widths=[]
    sx=abs(actor.get('scaleX',actor.get('scale',1))*body.get('sx',1))
    sy=abs(actor.get('scaleY',actor.get('scale',1))*body.get('sy',1))
    for sample in actor['beam']:
        pos=transform.map(QPointF(sample['x']+.5,sample['y']+.5));other=transform.map(QPointF(sample['x']+1.5,sample['y']+.5))
        scale=math.hypot(other.x()-pos.x(),other.y()-pos.y())/pixels_per_tile
        points.append((pos.x()+actor.get('offsetX',0)*scale,pos.y()+actor.get('height',0)*scale,sample.get('d',0)))
        widths.append(picture.width()*sx*scale)
    # Texture coordinates are screen pixels; sample arc lengths are world
    # units. WorldToScreen's scale is independent of room and stage scaling.
    period=picture.height()*max(.001,sy)/max(.001,actor.get('beamPixelScale',1))
    if horizontal:period=max(1,points[-1][2]-points[0][2])
    source_per_unit=picture.height()/period
    for phase,length,quad in laser_quads(points,period,widths):
        draw_strip(painter,picture,phase,length,quad,source_per_unit)
    caps=[layer for layer in layers if layer is not body]
    if caps and not actor.get('beamClosed'):
        origin=transform.map(QPointF(actor['x']+.5,actor['y']+.5));other=transform.map(QPointF(actor['x']+1.5,actor['y']+.5))
        scale=math.hypot(other.x()-origin.x(),other.y()-origin.y())/pixels_per_tile
        target=points[0];dx=target[0]-origin.x()-actor.get('offsetX',0)*scale;dy=target[1]-origin.y()-actor.get('height',0)*scale
        if math.hypot(dx,dy)<.01:dx=points[1][0]-points[0][0];dy=points[1][1]-points[0][1]
        painter.save();painter.translate(origin.x()+actor.get('offsetX',0)*scale,origin.y()+actor.get('height',0)*scale)
        painter.rotate(math.degrees(math.atan2(dy,dx))-90);painter.scale(scale*actor.get('scaleX',1),scale*actor.get('scaleY',1))
        images.layers(painter,caps);painter.restore()
    return True
