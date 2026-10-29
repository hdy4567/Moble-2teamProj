import argparse
import math
import queue
import re
import select
import signal
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np


PORT = 5000
MFC_HOST = "0.0.0.0"
ARDUINO_PORT = "/dev/ttyACM0"   # USB 아두이노: 보드에 따라 /dev/ttyUSB0
ARDUINO_BAUD = 115200
VIDEO_PORT = 8080
VIDEO_HOST = "0.0.0.0"
# 기존 Arduino 숫자 명령: 5 = 오류 배출, 6 = 오류 배출 해제
MOTOR_COMMAND = "5\n"
MOTOR_ERROR_REASONS = {"MISMATCH", "MULTIPLE_REGIONS"}  # 미검출/타임아웃 시 기계 작동 금지
ERROR_BLINK_SEC = 5.0
BLINK_INTERVAL_SEC = 0.25
MIN_AREA = 0           # 0이면 최소 면적 제한 없음. 양수로 바꾸면 잡음 크기 제한
MIN_RELATIVE_AREA = 0.005  # 가장 큰 원형 후보 면적의 0.5% 미만인 배경 점 제외
MORPH_KERNEL_SIZE = 1  # 1이면 모폴로지 생략: 작은 원형 스티커 모양을 보존
MIN_CIRCULARITY = 0.85  # 원형도: 4*pi*면적/둘레^2 (원에 가까울수록 1)
MIN_AXIS_RATIO = 0.85   # 가로/세로 비율: 짧은 쪽 / 긴 쪽
MIN_CIRCLE_FILL = 0.85  # 외접원 안에서 실제 색 영역이 차지하는 비율
CONTOUR_EPSILON = 0.005  # 둘레의 0.5% 이내로 경계를 단순화해 촬영 잡음 완화
AUTO_CORRECT = {"RED": True, "GREEN": True, "BLUE": True, "YELLOW": True}
BRIGHT_RATIOS = (0.60, 0.80, 0.90)  # 각 색 영역 내 밝은 픽셀 대비 기준
EMPTY_FRAMES = 3      # 이전 화물이 없는지 확인할 연속 프레임 수
STABLE_FRAMES = 5     # 같은 색이 이 횟수만큼 연속 검출되면 최종 판정
TIMEOUT_SEC = 5.0     # 빈 구역 대기 / READY 후 판정 대기, 각각 5초

# OpenCV HSV: H=0~179, S=0~255, V=0~255.
# 실제 화물과 조명에 맞게 조정하세요. 빨강은 양 끝의 두 범위를 합칩니다.
COLOR_RANGES = {
    # 네 색 모두 흐리거나 어두운 색을 후보로 잡은 뒤 원형과 상대 밝기로 검증
    "RED": [((0, 60, 50), (10, 255, 255)),
            ((170, 60, 50), (179, 255, 255))],
    "GREEN": [((35, 60, 50), (85, 255, 255))],
    "BLUE": [((100, 60, 50), (140, 255, 255))],
    "YELLOW": [((18, 60, 50), (34, 255, 255))],
}


def circular_box(component_mask, pixel_area, touches_border=None):
    """라벨링한 영역이 원형 기준을 만족하면 사각형, 아니면 None을 반환."""
    contours, _ = cv2.findContours(component_mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(contour)
    height, width = component_mask.shape

    # 검사 구역 경계에 걸친 물체는 전체 모양을 확인할 수 없어 제외합니다.
    if touches_border is None:
        touches_border = x <= 0 or y <= 0 or x + w >= width or y + h >= height
    if touches_border:
        return None
    # JPEG/반사/픽셀 계단 때문에 실제 원의 둘레가 과대 측정되는 것을 완화.
    raw_perimeter = cv2.arcLength(contour, True)
    contour = cv2.approxPolyDP(contour, CONTOUR_EPSILON * raw_perimeter, True)
    area = cv2.contourArea(contour)
    perimeter = cv2.arcLength(contour, True)
    if perimeter <= 0 or w <= 0 or h <= 0:
        return None

    circularity = 4 * math.pi * area / (perimeter * perimeter)
    axis_ratio = min(w, h) / max(w, h)
    center, radius = cv2.minEnclosingCircle(contour)
    if radius <= 0:
        return None
    circle_fill = pixel_area / (math.pi * radius * radius)

    # 사각형, 길쭉한 타원, 속이 크게 빈 고리 등을 제외합니다.
    if (circularity < MIN_CIRCULARITY or axis_ratio < MIN_AXIS_RATIO
            or circle_fill < MIN_CIRCLE_FILL):
        return None
    return x, y, w, h


def add_unique_circle(regions, area, box):
    """같은 스티커가 여러 밝기 기준에서 잡혀도 한 번만 셉니다."""
    x, y, w, h = box
    for index, (old_area, old_box) in enumerate(regions):
        ox, oy, ow, oh = old_box
        intersection = max(0, min(x+w, ox+ow) - max(x, ox)) * \
                       max(0, min(y+h, oy+oh) - max(y, oy))
        if intersection / min(w*h, ow*oh) >= 0.65:
            if area > old_area:
                regions[index] = (area, box)
            return
    regions.append((area, box))


def find_circle_regions(mask, value_channel=None, min_value=50):
    """색 마스크에서 원형 후보를 찾고, 필요할 때 같은 색의 반사를 분리."""
    regions = []
    height, width = mask.shape
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    for i in range(1, count):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if MIN_AREA > 0 and area < MIN_AREA:
            continue
        left = int(stats[i, cv2.CC_STAT_LEFT])
        top = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        touches_border = (left <= 0 or top <= 0 or left + bw >= width
                          or top + bh >= height)
        component = (labels[top:top+bh, left:left+bw] == i).astype("uint8") * 255
        box = circular_box(component, area, touches_border)
        if box is not None:
            x, y, w, h = box
            regions.append((area, (left+x, top+y, w, h)))
            continue

        if value_channel is None:
            continue
        # 이미 원형이면 보정하지 않아 스티커 내부의 그림자를 보존합니다.
        # 반사 때문에 찌그러진 후보에만 각 영역의 상대 밝기 기준을 적용합니다.
        value = value_channel[top:top+bh, left:left+bw]
        pixels = value[component > 0]
        bright = float(np.percentile(pixels, 90))
        dimmest = int(pixels.min())
        used_levels = set()
        for ratio in BRIGHT_RATIOS:
            level = max(min_value, int(bright * ratio))
            if level <= dimmest or level in used_levels:
                continue
            used_levels.add(level)
            refined = cv2.bitwise_and(component, cv2.inRange(value, level, 255))
            # 잘라낸 작은 영상에 여백을 주고 원래 ROI 경계 여부를 다시 확인.
            refined = cv2.copyMakeBorder(refined, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
            for new_area, new_box in find_circle_regions(refined):
                x, y, w, h = new_box
                box = (left+x-1, top+y-1, w, h)
                gx, gy, _, _ = box
                if gx <= 0 or gy <= 0 or gx+w >= width or gy+h >= height:
                    continue
                add_unique_circle(regions, new_area, box)
    return regions


def detect_color(image):
    """ROI에서 원형 영역만 검사해 (색 이름, 가장 큰 원의 사각형)을 반환."""
    # 교재와 같은 HSV -> inRange -> 모폴로지 -> 라벨링 순서입니다.
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    candidates = []
    for color, ranges in COLOR_RANGES.items():
        lower, upper = ranges[0]
        mask = cv2.inRange(hsv, lower, upper)
        for lower, upper in ranges[1:]:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lower, upper))
        if MORPH_KERNEL_SIZE > 1:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT,
                                               (MORPH_KERNEL_SIZE, MORPH_KERNEL_SIZE))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        value = hsv[:, :, 2] if AUTO_CORRECT[color] else None
        min_value = min(bounds[0][2] for bounds in ranges)
        for area, box in find_circle_regions(mask, value, min_value):
            candidates.append((area, color, box))

    if not candidates:
        return "NONE", None
    area, color, box = max(candidates, key=lambda item: item[0])
    # 고정 픽셀 크기 제한이 아닙니다. 작은 스티커만 있을 때도 그대로 검출.
    # 가장 큰 후보 대비 극히 작은 다른 점만 제외하며, 0으로 설정하면 해제.
    candidates = [item for item in candidates if item[0] >= area * MIN_RELATIVE_AREA]
    return ("MIXED" if len(candidates) > 1 else color), box


def parse_check(line):
    """CHECK <번호> <지시색>을 검사하고 (번호, 색)을 반환합니다."""
    parts = line.split()
    if len(parts) != 3 or parts[0] != "CHECK":
        raise ValueError("BAD_REQUEST")
    request_id, expected = parts[1], parts[2]
    if re.fullmatch(r"[A-Za-z0-9_]{1,16}", request_id) is None:
        raise ValueError("BAD_REQUEST")
    if expected not in COLOR_RANGES:
        raise ValueError("BAD_REQUEST")
    return request_id, expected


class Inspection:
    """검사 한 건의 빈 구역 확인, 색 안정화, 정상/오류 판정을 담당합니다."""

    def __init__(self, request_id, expected, now, require_clear=True):
        self.request_id = request_id
        self.expected = expected
        self.phase = "WAIT_CLEAR" if require_clear else "WAIT_COLOR"
        self.started = now
        self.empty_count = 0
        self.previous = "NONE"
        self.stable_count = 0

    def error(self, reason):
        self.phase = "DONE"
        return f"RESULT {self.request_id} ERROR NONE {reason}\n"

    def update(self, detected, now):
        """진행 중에는 빈 문자열, 준비 시 READY, 완료 시 RESULT를 반환합니다."""
        if self.phase == "DONE":
            return ""
        if now - self.started >= TIMEOUT_SEC:
            reason = "NOT_CLEAR" if self.phase == "WAIT_CLEAR" else "NO_STABLE_COLOR"
            return self.error(reason)

        if self.phase == "WAIT_CLEAR":
            self.empty_count = self.empty_count + 1 if detected == "NONE" else 0
            if self.empty_count < EMPTY_FRAMES:
                return ""
            self.phase = "WAIT_COLOR"
            self.started = now
            return f"READY {self.request_id}\n"

        if detected == "NONE":
            self.previous = "NONE"
            self.stable_count = 0
            return ""
        self.stable_count = self.stable_count + 1 if detected == self.previous else 1
        self.previous = detected
        if self.stable_count < STABLE_FRAMES:
            return ""

        self.phase = "DONE"
        if detected == "MIXED":
            return f"RESULT {self.request_id} ERROR MIXED MULTIPLE_REGIONS\n"
        if detected == self.expected:
            return f"RESULT {self.request_id} OK {detected} MATCH\n"
        return f"RESULT {self.request_id} ERROR {detected} MISMATCH\n"


COLOR_KOREAN = {"RED": "빨강", "YELLOW": "노랑", "BLUE": "파랑", "GREEN": "초록",
                "NONE": "없음", "MIXED": "여러 개"}


def parse_terminal_color(text):
    aliases = {"빨": "RED", "빨강": "RED", "빨간색": "RED", "R": "RED",
               "노": "YELLOW", "노랑": "YELLOW", "노란색": "YELLOW", "Y": "YELLOW",
               "파": "BLUE", "파랑": "BLUE", "파란색": "BLUE", "B": "BLUE",
               "초": "GREEN", "초록": "GREEN", "초록색": "GREEN", "G": "GREEN"}
    text = text.strip().upper()
    if text in COLOR_RANGES:
        return text
    if text in aliases:
        return aliases[text]
    raise ValueError("빨/노/파/초 또는 RED/YELLOW/BLUE/GREEN 중 하나만 입력하세요.")


class TerminalInput:
    """input 대기 중에도 영상이 멈추지 않도록 입력만 별도 스레드에서 받음."""

    def __init__(self):
        self.commands = queue.Queue(maxsize=16)

    def start(self):
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            try:
                line = input()
            except (EOFError, OSError):
                line = "quit"
            try:
                self.commands.put_nowait(line)
            except queue.Full:
                print("입력이 너무 많습니다. 검사 완료 후 다시 입력하세요.", flush=True)
            if line.strip().lower() in ("q", "quit", "exit", "종료"):
                return

    def poll(self):
        try:
            return self.commands.get_nowait()
        except queue.Empty:
            return None


class FrameStore:
    """검출 결과가 그려진 최신 JPEG만 공유. 카메라 캡처는 메인 루프 단 한 곳."""
    def __init__(self):
        self.condition = threading.Condition()
        self.jpeg = None
        self.sequence = 0
        self.closed = False

    def publish(self, jpeg):
        with self.condition:
            self.jpeg = jpeg
            self.sequence += 1
            self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class VideoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            page = ("<!doctype html><html><head><meta charset='utf-8'>"
                    "<title>Cargo Inspection</title></head><body style='background:#151515;color:white'>"
                    "<h3>Live Cargo Inspection</h3><img src='/video_feed' style='width:100%;max-width:960px'>"
                    "</body></html>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        if self.path != "/video_feed":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        store = self.server.frame_store
        last = -1
        try:
            while True:
                with store.condition:
                    store.condition.wait_for(
                        lambda: store.sequence != last or store.closed, timeout=5)
                    if store.closed:
                        break
                    if store.sequence == last or store.jpeg is None:
                        continue
                    last, jpeg = store.sequence, store.jpeg
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                 + str(len(jpeg)).encode("ascii") + b"\r\n\r\n")
                self.wfile.write(jpeg + b"\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, fmt, *args):
        pass


def start_video_server(store, port=VIDEO_PORT):
    server = ThreadingHTTPServer((VIDEO_HOST, port), VideoHandler)
    server.daemon_threads = True
    server.frame_store = store
    threading.Thread(target=server.serve_forever, daemon=True, name="mjpeg-server").start()
    return server


class ArduinoMotor:
    """기본은 출력 시뮬레이션. --arduino-real일 때만 USB 시리얼을 엽니다."""

    def __init__(self, enabled=False, port=ARDUINO_PORT, baud=ARDUINO_BAUD):
        self.enabled = enabled
        self.port = port
        self.baud = baud
        self.connection = None

    def open(self):
        if not self.enabled:
            return
        try:
            import serial   # 시뮬레이션에서는 pyserial 설치 불필요
        except ImportError as error:
            raise RuntimeError("실제 Arduino 연결에는 python3-serial이 필요합니다.") from error
        self.connection = serial.Serial(port=None, baudrate=self.baud,
                                        timeout=0, write_timeout=1)
        self.connection.port = self.port
        self.connection.open()
        time.sleep(2.0)     # USB 연결로 재시작되는 Arduino의 준비 대기 (시작 시 한 번)

    def on_error(self, request_id):
        command = MOTOR_COMMAND.encode("ascii")
        if not self.enabled:
            print("에러 : 모터 동작", flush=True)
            print(f"[Arduino 시뮬레이션] {command.decode('ascii').strip()}", flush=True)
            return
        if self.connection is None or not self.connection.is_open:
            raise OSError("Arduino 시리얼 포트가 열려 있지 않습니다.")
        if self.connection.write(command) != len(command):
            raise OSError("모터 명령 일부만 전송됨. 자동 재전송하지 않습니다.")
        print(f"Arduino 명령 전송: {command.decode('ascii').strip()}", flush=True)

    def close(self):
        if self.connection is not None:
            self.connection.close()


class Feedback:
    """지시 한 건의 결과를 한 번만 처리하고 약 5초 점멸을 관리합니다."""

    def __init__(self, motor):
        self.motor = motor
        self.result = None
        self.expected = None
        self.finished = False
        self.alert_started = 0.0
        self.alert_until = 0.0

    def begin(self, expected=None):
        self.result = None
        self.finished = False
        self.expected = expected

    def alert_active(self, now):
        return now < self.alert_until

    def flash_on(self, now):
        return self.alert_active(now) and int((now - self.alert_started) / BLINK_INTERVAL_SEC) % 2 == 0

    def finish(self, line, now):
        if self.finished:
            return False
        parts = line.split()
        if len(parts) != 5 or parts[0] != "RESULT" or parts[2] not in ("OK", "ERROR"):
            raise ValueError("잘못된 검사 결과")
        self.finished = True
        self.result = dict(zip(("command", "id", "status", "detected", "reason"), parts))
        normal = parts[2] == "OK"
        label = "정상 검출" if normal else "비정상 검출 / ERROR"
        message = f"{label} : {COLOR_KOREAN.get(parts[3], parts[3])} ({parts[3]}) / {parts[4]}"
        if sys.stdout.isatty():
            message = ("\033[32m" if normal else "\033[31m") + message + "\033[0m"
        print(message, flush=True)
        if not normal:
            self.alert_started = now
            self.alert_until = now + ERROR_BLINK_SEC
            if parts[4] in MOTOR_ERROR_REASONS:
                try:
                    self.motor.on_error(parts[1])
                except (OSError, RuntimeError) as error:
                    # 검사 결과를 바꾸거나 모터 명령을 반복하지 않습니다.
                    self.result["motor_error"] = str(error)
                    print(f"에러 : 모터 명령 전송 실패 / {error}", flush=True)
        return True


def send_line(client, line):
    """TCP 일부 전송을 처리하는 sendall을 사용합니다. 실패 시 False입니다."""
    try:
        client.sendall(line.encode("ascii"))
        print("TX:", line.strip(), flush=True)
        return True
    except OSError:
        return False


def get_roi(frame, full_frame=False):
    """기본은 영상 중앙 절반, --full-frame이면 영상 전체를 검사합니다."""
    height, width = frame.shape[:2]
    if full_frame:
        return 0, 0, width, height
    return width // 4, height // 4, width // 2, height // 2


def draw_detection(frame, roi, detected, box, inspection=None, feedback=None, now=None):
    """검사 구역과 인식한 원형 스티커를 화면에 표시합니다."""
    now = time.monotonic() if now is None else now
    if feedback is not None and feedback.flash_on(now):
        red = np.zeros_like(frame)
        red[:, :, 2] = 255
        frame[:] = cv2.addWeighted(frame, 0.55, red, 0.45, 0)
    x, y, w, h = roi
    cv2.rectangle(frame, (x, y), (x+w-1, y+h-1), (255, 255, 255), 2)
    if box is not None:
        left, top, bw, bh = box
        center = (x + left + bw // 2, y + top + bh // 2)
        cv2.circle(frame, center, max(bw, bh) // 2, (0, 255, 0), 2)
    result = feedback.result if feedback is not None else None
    text_color = (255, 255, 255)
    if result is not None:
        detected = result["detected"]  # 완료한 결과는 다음 지시까지 유지
        text_color = (0, 255, 0) if result["status"] == "OK" else (0, 0, 255)
    label = f"Detected: {detected}"
    if inspection is not None:
        label += f" Expected: {inspection.expected} {inspection.phase}"
    elif result is not None and feedback.expected is not None:
        label += f" Expected: {feedback.expected}"
    cv2.rectangle(frame, (0, 0), (frame.shape[1]-1, 83), (0, 0, 0), -1)
    cv2.putText(frame, label, (10, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)
    if result is not None:
        message = ("NORMAL" if result["status"] == "OK" else "ERROR: " + result["reason"])
        if "motor_error" in result:
            message += " / MOTOR SEND FAILED"
    elif inspection is not None:
        message = f"Inspecting {inspection.request_id} / {inspection.phase}"
    else:
        message = "Waiting for command / Preview"
    cv2.putText(frame, message, (10, 59), cv2.FONT_HERSHEY_SIMPLEX, 0.6, text_color, 2)


def run_server(camera_index=0, show_window=True, preview_only=False, full_frame=False,
               input_mode="mfc", arduino_real=False, arduino_port=ARDUINO_PORT,
               arduino_baud=ARDUINO_BAUD, require_clear=False):
    cap = None
    server = None
    client = None
    inspection = None
    motor = ArduinoMotor(arduino_real, arduino_port, arduino_baud)
    feedback = Feedback(motor)
    terminal = None
    terminal_id = 0
    frames = FrameStore()
    video_server = None
    running = True
    mode = "preview" if preview_only else input_mode

    def stop_program(signum, frame):
        nonlocal running
        running = False

    # 메인 스레드에서 실행합니다. Ctrl+C / 종료 신호를 처리합니다.
    signal.signal(signal.SIGINT, stop_program)
    signal.signal(signal.SIGTERM, stop_program)
    try:
        if mode not in ("terminal", "mfc", "preview"):
            raise RuntimeError("알 수 없는 지시 입력 모드")
        cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError("USB 카메라를 열 수 없습니다.")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 카메라에 따라 적용되지 않을 수 있음

        video_server = start_video_server(frames)
        print(f"Video: http://<raspberry-pi-ip>:{VIDEO_PORT}/video_feed", flush=True)
        if mode != "preview":
            motor.open()
        if mode == "mfc":
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((MFC_HOST, PORT))
            server.listen(1)
            server.setblocking(False)
        if mode == "terminal":
            terminal = TerminalInput()
            terminal.start()
            print("터미널 시뮬레이션: 빨/노/파/초 입력 후 Enter. 종료: q / ESC / Ctrl+C", flush=True)
            print("지시 1회당 결과 1회. 검사 중/5초 경고 중 추가 지시는 거부합니다.", flush=True)
        print(f"USB camera ready. Mode={mode}. MFC TCP={PORT}, Arduino={arduino_port}", flush=True)
        buffer = b""
        connected_at = 0.0
        last_detected = None

        while running:
            # 명령을 기다릴 때도 읽어 이전 카메라 영상이 쌓이는 일을 줄입니다.
            success, frame = cap.read()
            if not success or frame is None or frame.size == 0:
                raise RuntimeError("카메라 영상 읽기 실패")
            x, y, w, h = get_roi(frame, full_frame)
            detected, box = detect_color(frame[y:y+h, x:x+w])
            if detected != last_detected:
                print(f"Detected: {detected}", flush=True)
                last_detected = detected
            new_check = False

            if terminal is not None:
                line = terminal.poll()
                if line is not None:
                    if line.strip().lower() in ("q", "quit", "exit", "종료"):
                        running = False
                        break
                    try:
                        expected = parse_terminal_color(line)
                        if inspection is not None or feedback.alert_active(time.monotonic()):
                            print("검사/경고 진행 중입니다. 완료 후 다시 입력하세요. (입력 거부)", flush=True)
                        else:
                            terminal_id += 1
                            request_id = f"T{terminal_id}"
                            inspection = Inspection(request_id, expected, time.monotonic(), require_clear)
                            feedback.begin(expected)
                            new_check = True
                            print(f"지시 {request_id} : {COLOR_KOREAN[expected]} ({expected})", flush=True)
                            if not require_clear:
                                print(f"READY {request_id} / 현재 화면부터 새로 검사합니다.", flush=True)
                    except ValueError as error:
                        print(error, flush=True)

            if client is None and server is not None:
                try:
                    client, address = server.accept()
                    client.settimeout(1.0)  # 송수신이 영구 대기하지 않도록 제한
                    buffer = b""
                    inspection = None
                    connected_at = time.monotonic()
                except BlockingIOError:
                    pass

            if client is not None:
                drop = False
                try:
                    readable, _, _ = select.select([client], [], [], 0)
                    if readable:
                        data = client.recv(256)
                        if not data:
                            drop = True
                        else:
                            buffer += data
                            if inspection is not None or len(buffer) > 128:
                                drop = True
                            elif b"\n" in buffer:
                                line, trailing = buffer.split(b"\n", 1)
                                try:
                                    if trailing:
                                        raise ValueError("추가 명령은 허용하지 않습니다.")
                                    request_id, expected = parse_check(line.decode("ascii"))
                                    if feedback.alert_active(time.monotonic()):
                                        send_line(client, f"RESULT {request_id} ERROR NONE BUSY\n")
                                        drop = True
                                    else:
                                        inspection = Inspection(request_id, expected, time.monotonic())
                                        feedback.begin(expected)
                                        new_check = True
                                        buffer = b""
                                except (ValueError, UnicodeError):
                                    send_line(client, "RESULT 0 ERROR NONE BAD_REQUEST\n")
                                    drop = True
                except OSError:
                    drop = True

                if inspection is None and time.monotonic() - connected_at >= TIMEOUT_SEC:
                    drop = True
                if drop:
                    client.close()
                    client = None
                    inspection = None
                    buffer = b""

            # CHECK 수신 전에 찍은 이번 영상은 새 검사에서 제외합니다.
            if inspection is not None and not new_check:
                reply = inspection.update(detected, time.monotonic())
                if reply:
                    if reply.startswith("RESULT "):
                        feedback.finish(reply, time.monotonic())
                    sent = send_line(client, reply) if client is not None else True
                    if terminal is not None:
                        print(reply.strip(), flush=True)
                        if reply.startswith("READY "):
                            print("검사 준비 완료. 스티커가 붙은 물건을 보여주세요.", flush=True)
                    if not sent or inspection.phase == "DONE":
                        if client is not None:
                            client.close()  # 검사 한 건의 최종 결과 후 연결 종료
                        client = None
                        inspection = None

            # 한 번 그린 프레임을 로컬 화면과 MFC 실시간 영상에 동일하게 사용
            draw_detection(frame, (x, y, w, h), detected, box, inspection, feedback)
            encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if encoded:
                frames.publish(jpeg.tobytes())
            if show_window:
                cv2.imshow("Cargo color check - white box is ROI", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    running = False

        if inspection is not None:
            reply = inspection.error("STOPPED")
            if client is not None:
                send_line(client, reply)
            else:
                print(reply.strip(), flush=True)
        return 0
    except (OSError, RuntimeError, cv2.error) as error:
        print("ERROR:", error, flush=True)
        if inspection is not None:
            reply = inspection.error("CAMERA_OR_SERVER_ERROR")
            feedback.finish(reply, time.monotonic())
            if client is not None:
                send_line(client, reply)
        return 1
    finally:
        frames.close()
        if video_server is not None:
            video_server.shutdown()
            video_server.server_close()
        if client is not None:
            client.close()
        if server is not None:
            server.close()
        if cap is not None:
            cap.release()
        motor.close()
        if show_window:
            cv2.destroyAllWindows()


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description="USB 카메라 화물 색 검사 서버")
    parser.add_argument("--camera", type=int, default=0, help="USB 카메라 번호")
    parser.add_argument("--headless", action="store_true", help="영상 창 없이 실행")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--mode", choices=("terminal", "mfc", "preview"), default="mfc",
                       help="기본: mfc. 테스트 시 terminal 또는 preview")
    modes.add_argument("--preview", dest="mode", action="store_const", const="preview",
                       help="지시 없이 카메라 인식만 확인")
    parser.add_argument("--full-frame", action="store_true", help="화면 전체를 검사")
    parser.add_argument("--require-clear", action="store_true", help="터미널에서도 빈 구역 확인 후 READY")
    parser.add_argument("--arduino-real", action="store_true", help="실제 Arduino USB 시리얼 사용")
    parser.add_argument("--arduino-port", default=ARDUINO_PORT, help="Arduino USB 장치 경로")
    parser.add_argument("--arduino-baud", type=int, default=ARDUINO_BAUD, help="Arduino 통신 속도")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_arguments()
    raise SystemExit(run_server(camera_index=args.camera, show_window=not args.headless,
                                full_frame=args.full_frame, input_mode=args.mode,
                                arduino_real=args.arduino_real, arduino_port=args.arduino_port,
                                arduino_baud=args.arduino_baud, require_clear=args.require_clear))
