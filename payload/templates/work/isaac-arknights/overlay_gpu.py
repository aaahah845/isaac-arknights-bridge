"""Native transparent GL window; the same painter/layout uses GPU textures."""
import ctypes as C,json
from ctypes import wintypes as W
from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGL import QOpenGLWindow
from overlay import Overlay,ROOT


class GpuOverlay(QOpenGLWindow):
    setup=Overlay.setup;tick=Overlay.tick;drawFrame=Overlay.drawFrame

    def __init__(self):
        super().__init__()
        self.setFlags(Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.WindowTransparentForInput|Qt.WindowDoesNotAcceptFocus)
        format=QSurfaceFormat();format.setAlphaBufferSize(8);format.setSamples(0);format.setSwapInterval(0);self.setFormat(format)
        self.hardware=True;self.setup()
        hwnd=W.HWND(int(self.winId()));user=C.windll.user32
        user.GetWindowLongPtrW.argtypes=[W.HWND,C.c_int];user.GetWindowLongPtrW.restype=C.c_ssize_t
        user.SetWindowLongPtrW.argtypes=[W.HWND,C.c_int,C.c_ssize_t];user.SetWindowLongPtrW.restype=C.c_ssize_t
        # WS_EX_TRANSPARENT alone only controls paint ordering. Layered +
        # transparent makes Windows route mouse input to the other process.
        style=user.GetWindowLongPtrW(hwnd,-20);user.SetWindowLongPtrW(hwnd,-20,style|0x20|0x80|0x08000000|0x80000)
        user.SetLayeredWindowAttributes.argtypes=[W.HWND,W.DWORD,C.c_ubyte,W.DWORD]
        user.SetLayeredWindowAttributes(hwnd,0,255,2)
        class Blur(C.Structure):_fields_=[('flags',W.DWORD),('enabled',W.BOOL),('region',W.HANDLE),('transition',W.BOOL)]
        class Margins(C.Structure):_fields_=[('left',C.c_int),('right',C.c_int),('top',C.c_int),('bottom',C.c_int)]
        gdi=C.windll.gdi32;gdi.CreateRectRgn.restype=W.HANDLE
        region=gdi.CreateRectRgn(0,0,-1,-1);blur=Blur(3,True,region,False)
        C.windll.dwmapi.DwmEnableBlurBehindWindow(hwnd,C.byref(blur));C.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd,C.byref(Margins(-1,-1,-1,-1)))
        gdi.DeleteObject.argtypes=[W.HANDLE];gdi.DeleteObject(region)

    def devicePixelRatioF(self):return self.devicePixelRatio()

    def initializeGL(self):
        self.context().functions().glClearColor(0,0,0,0)
        (ROOT/'gpu-overlay-status.json').write_text(json.dumps({'valid':self.isValid(),'alphaBits':self.format().alphaBufferSize(),'renderer':'native GL window'}),encoding='utf-8')

    def paintGL(self):
        self.context().functions().glClear(0x4000);self.drawFrame()
