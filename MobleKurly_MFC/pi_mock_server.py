# Demo Raspberry Pi command server (Python 3 stdlib, no extra packages).
# Listening ONLY on localhost by default. Do not expose to the internet.
import socketserver

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        raw = self.rfile.readline(513)
        if not raw or len(raw) > 512 or not raw.endswith(b"\n"):
            return
        try:
            message = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            return
        parts = message.split("|")
        if len(parts) != 3:
            return
        command, order_id, request_id = parts
        print(f"[MOCK] {command=} {order_id=} {request_id=}")
        if command == "PING" and order_id == "-":
            reply = f"PONG|{request_id}"
        elif command in ("DISPATCH_ORDER", "RETRY_ORDER") and order_id.isdecimal():
            # ACK means request accepted by mock, NEVER physically dispatched.
            reply = f"ACK|{request_id}|MOCK_ONLY"
        else:
            reply = f"ERR|{request_id}|BAD_COMMAND"
        self.wfile.write((reply + "\n").encode("utf-8"))

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    with Server(("127.0.0.1", 5055), Handler) as srv:
        print("MobleKurly mock Pi server ready: 127.0.0.1:5055")
        srv.serve_forever()
