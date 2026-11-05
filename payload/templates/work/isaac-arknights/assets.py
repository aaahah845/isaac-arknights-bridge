"""Complete ANM2 frames: omitted numeric attributes are unsafe in this client."""
import xml.etree.ElementTree as ET

ASSET_VERSION=4
FRAME={'XPosition':'0','YPosition':'0','Delay':'1','Visible':'true',
       'XScale':'100','YScale':'100','RedTint':'255','GreenTint':'255',
       'BlueTint':'255','AlphaTint':'255','RedOffset':'0','GreenOffset':'0',
       'BlueOffset':'0','Rotation':'0','Interpolated':'false'}

def animation(name,width,height,pivot=None):
    # Capture camera: orthographic size .9, centre lifted .45 along camera up.
    # The unit's world/hit anchor projects at 3/4 of the captured image height.
    pivot=pivot or (width/2,height*3/4)
    actor=ET.Element('AnimatedActor');ET.SubElement(actor,'Info',CreatedBy='Local Bridge')
    content=ET.SubElement(actor,'Content');sheets=ET.SubElement(content,'Spritesheets')
    ET.SubElement(sheets,'Spritesheet',Path=f'{name}.png',Id='0')
    layers=ET.SubElement(content,'Layers');ET.SubElement(layers,'Layer',Name='Image',Id='0',SpritesheetId='0')
    nulls=ET.SubElement(content,'Nulls');ET.SubElement(nulls,'Null',Name='OverlayEffect',Id='0');ET.SubElement(content,'Events')
    animations=ET.SubElement(actor,'Animations',DefaultAnimation='Idle')
    anim=ET.SubElement(animations,'Animation',Name='Idle',FrameNum='1',Loop='true')
    ET.SubElement(ET.SubElement(anim,'RootAnimation'),'Frame',**FRAME)
    layer=ET.SubElement(ET.SubElement(anim,'LayerAnimations'),'LayerAnimation',LayerId='0',Visible='true')
    ET.SubElement(layer,'Frame',**FRAME,XCrop='0',YCrop='0',Width=str(width),Height=str(height),XPivot=str(pivot[0]),YPivot=str(pivot[1]))
    null=ET.SubElement(ET.SubElement(anim,'NullAnimations'),'NullAnimation',NullId='0',Visible='true')
    ET.SubElement(null,'Frame',**dict(FRAME,YPosition=str(-height//3)))
    ET.SubElement(anim,'Triggers')
    return ET.tostring(actor,encoding='unicode')
