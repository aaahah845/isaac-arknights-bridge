"""Reposition native Isaac HUD artwork; no replacement fonts or panels."""
import json
import math
from pathlib import Path
from PySide6.QtCore import QRectF

FONT=json.loads(Path(__file__).with_name('hud-font.json').read_text(encoding='utf-8'))


def hud_scale(width,height):
    return max(.35,min(2.2,width/1600,height/1000))


def stat_rows(player):
    tears=30/max(.01,player.get('fireDelay',10)+1)
    return [('移速',player.get('speed',0)),('射速',tears),('伤害',player.get('damage',0)),
            ('射程',player.get('range',0)/40),('弹速',player.get('shotSpeed',0)),('幸运',player.get('luck',0))]


def draw_hud(painter,isaac,sprites,width,height):
    player=isaac.get('player',{})
    if not player:return
    hud=isaac.get('hud') or {};scale=hud_scale(width,height)
    painter.save();painter.scale(scale,scale)
    h=height/scale;x,y=20,max(180,h*.20)

    def picture(layers,rect):
        for layer in layers or []:
            image=sprites.image(layer)
            if image is None or image.isNull():continue
            target=QRectF(*rect);ratio=min(target.width()/image.width(),target.height()/image.height())
            iw,ih=image.width()*ratio,image.height()*ratio
            painter.drawImage(QRectF(target.center().x()-iw/2,target.center().y()-ih/2,iw,ih),image)

    font_layers=hud.get('font') or []
    atlas=sprites.image(dict(font_layers[0],sourceX=0,sourceY=0,w=FONT['atlasWidth'],h=FONT['atlasHeight'])) if font_layers else None

    def number(value,xx,yy,size=2):
        if atlas is None:return
        for char in str(value):
            glyph=FONT['glyphs'].get(char)
            if not glyph:continue
            painter.drawImage(QRectF(xx+glyph['ox']*size,yy+glyph['oy']*size,glyph['w']*size,glyph['h']*size),
                              atlas,QRectF(glyph['x'],glyph['y'],glyph['w'],glyph['h']))
            xx+=glyph['advance']*size

    hearts=hud.get('hearts',[])
    for i,heart in enumerate(hearts):
        rect=(x+(i%8)*24,y+(i//8)*25,24,24)
        for part in ('layers','gold','eternal'):picture(heart.get(part),rect)
    resource_y=y+max(1,math.ceil(len(hearts)/8))*25+12
    pickup_icons=hud.get('pickups',[])
    for i,key in enumerate(('coins','bombs','keys')):
        yy=resource_y+i*27
        if i<len(pickup_icons):picture(pickup_icons[i],(x,yy,24,24))
        number(f'{player.get(key,0):02d}',x+36,yy+2)
    row_y=resource_y+3*27+12
    icons=hud.get('icons',[])
    for i,(_,value) in enumerate(stat_rows(player)):
        yy=row_y+i*34
        if i<len(icons):picture(icons[i],(x,yy,25,25))
        shown=f'{value:.2f}' if math.isfinite(value) else '-'
        if math.isfinite(value) and abs(value)>=100000:shown=f'{value:.1e}'
        number(shown,x+37,yy+3)

    actives=hud.get('actives',[])
    block_height=64+max(0,len(actives)-1)*54
    ay=h-20-block_height
    for i,item in enumerate(actives):
        primary=i==0;iy=ay if primary else ay+76+(i-1)*54
        size=64 if primary else 42
        picture(item.get('layers'),(x,iy,size,size))
        maximum=max(0,item.get('maxCharge',0));charge=max(0,item.get('charge',0));battery=max(0,item.get('battery',0))
        if maximum:
            rect=(x+size+2,iy,32 if primary else 22,size)
            picture(hud.get('chargeEmpty'),rect)
            ratio=min(1,charge/maximum)
            painter.save();painter.setClipRect(QRectF(rect[0],rect[1]+rect[3]*(1-ratio),rect[2],rect[3]*ratio))
            picture(hud.get('chargeFull'),rect);painter.restore()
            picture((hud.get('chargeDividers') or {}).get(str(int(maximum))),rect)
            if battery:number('+'+f'{battery:g}',rect[0]+rect[2]+4,iy+size/2-10,1.5)
    painter.restore()
