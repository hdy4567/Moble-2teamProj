"""One camera owner: HSV recognition, live MJPEG preview and queued inspection.
No physical stock confirmation is implied by camera color matching.
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2
from color_inspection import detect_color, get_roi

class InspectionFailure(RuntimeError):
    pass

class CameraInspector:
    def __init__(self, index=0, full_frame=False, video_host='0.0.0.0', video_port=8080):
        self.index=int(index)
        self.full_frame=bool(full_frame)
        self.video_host=video_host
        self.video_port=int(video_port)
        self.condition=threading.Condition()
        self.sequence=0
        self.detected='NONE'
        self.jpeg=None
        self.expected=None
        self.result=None
        self.result_at=0
        self.active=False
        self.error=None
        self.stopping=False
        self.camera=None
        self.http=None
        self.thread=None

    def start(self):
        if self.thread is not None: return
        self.camera=cv2.VideoCapture(self.index, cv2.CAP_V4L2)
        if not self.camera.isOpened():
            self.camera.release()
            self.camera=None
            raise InspectionFailure('CAMERA_NOT_AVAILABLE')
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH,640)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
        self.camera.set(cv2.CAP_PROP_BUFFERSIZE,1)
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    data=b'<!doctype html><title>MobleKurly Inspection</title><img src="/video_feed" style="max-width:100%">'
                    self.send_response(200)
                    self.send_header('Content-Type','text/html; charset=utf-8')
                    self.send_header('Content-Length',str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if self.path != '/video_feed':
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                last=-1
                try:
                    while True:
                        with owner.condition:
                            owner.condition.wait_for(lambda: owner.sequence!=last or owner.stopping,timeout=3)
                            if owner.stopping: break
                            if owner.jpeg is None or owner.sequence==last: continue
                            last=owner.sequence
                            jpg=owner.jpeg
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(jpg)).encode()+b'\r\n\r\n'+jpg+b'\r\n')
                except (BrokenPipeError,ConnectionResetError,OSError): pass
            def log_message(self,*args): pass
        try:
            self.http=ThreadingHTTPServer((self.video_host,self.video_port),Handler)
            self.http.daemon_threads=True
        except Exception:
            self.camera.release()
            self.camera=None
            raise
        threading.Thread(target=self.http.serve_forever,daemon=True,name='mjpeg-http').start()
        self.thread=threading.Thread(target=self._capture,daemon=True,name='camera-capture')
        self.thread.start()

    def _capture(self):
        try:
            while not self.stopping:
                ok,frame=self.camera.read()
                if not ok or frame is None:
                    raise InspectionFailure('CAMERA_READ_FAILED')
                x,y,w,h=get_roi(frame,self.full_frame)
                detected,box=detect_color(frame[y:y+h,x:x+w])
                now=time.monotonic()
                with self.condition:
                    expected,active,result,result_at=self.expected,self.active,self.result,self.result_at
                if result is not None and result.startswith('ERROR') and now-result_at < 5 and int((now-result_at)/.25)%2 == 0:
                    red=frame.copy()
                    red[:]=(0,0,255)
                    frame=cv2.addWeighted(frame,.6,red,.4,0)
                cv2.rectangle(frame,(x,y),(x+w-1,y+h-1),(255,255,255),2)
                if box is not None:
                    bx,by,bw,bh=box
                    cv2.circle(frame,(x+bx+bw//2,y+by+bh//2),max(bw,bh)//2,(0,255,0),2)
                cv2.rectangle(frame,(0,0),(frame.shape[1]-1,84),(0,0,0),-1)
                shown=result if result and now-result_at<8 else ('CHECKING' if active else 'PREVIEW')
                cv2.putText(frame,f'Detected: {detected} Expected: {expected or "-"}',(10,27),cv2.FONT_HERSHEY_SIMPLEX,.60,(255,255,255),2)
                cv2.putText(frame,shown[:54],(10,60),cv2.FONT_HERSHEY_SIMPLEX,.60,(0,0,255) if shown.startswith('ERROR') else (0,255,0),2)
                ok,jpg=cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,78])
                with self.condition:
                    self.detected=detected
                    self.sequence+=1
                    if ok: self.jpeg=jpg.tobytes()
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.error=str(exc)
                self.condition.notify_all()

    def _samples(self,timeout):
        last=self.sequence
        limit=time.monotonic()+float(timeout)
        while True:
            with self.condition:
                left=limit-time.monotonic()
                if left<=0:return
                self.condition.wait_for(lambda:self.sequence>last or self.error or self.stopping,timeout=left)
                if self.error: raise InspectionFailure(self.error)
                if self.stopping: raise InspectionFailure('CAMERA_STOPPED')
                if self.sequence<=last: return
                last=self.sequence
                detected=self.detected
            yield detected

    def begin(self,expected):
        with self.condition:
            self.expected=expected
            self.active=True
            self.result=None

    def report(self,result):
        with self.condition:
            self.result=result
            self.result_at=time.monotonic()
            self.active=False

    def wait_empty(self,timeout=5,frames=3):
        count=0
        for color in self._samples(timeout):
            count=count+1 if color=='NONE' else 0
            if count>=frames: return
        raise InspectionFailure('NOT_CLEAR')

    def wait_color(self,timeout=12,frames=5):
        previous=None
        count=0
        for color in self._samples(timeout):
            if color=='NONE': previous,count=None,0
            else:
                count=count+1 if color==previous else 1
                previous=color
                if count>=frames: return color
        raise InspectionFailure('NO_STABLE_COLOR')

    def stop(self):
        with self.condition:
            self.stopping=True
            self.condition.notify_all()
        if self.thread: self.thread.join(timeout=3)
        if self.http:
            self.http.shutdown()
            self.http.server_close()
        if self.camera: self.camera.release()
