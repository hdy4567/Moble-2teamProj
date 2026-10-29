"""Run the shop through Waitress and a temporary public HTTPS tunnel."""

import argparse
import os
import re
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from tools.web_shortcut import refresh_live_package


ROOT = Path(__file__).resolve().parent
TUNNEL_EXE = ROOT / "tools" / "cloudflared.exe"
LIVE_SHORTCUT = ROOT / "출력물" / "바로가기" / "MobleKurly_현재주소_바로가기"


def publish_live_shortcut(address):
    """Refresh the team launcher without exposing secrets or stopping the tunnel."""
    try:
        archive = refresh_live_package(address, LIVE_SHORTCUT)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"WARNING: Could not update the team shortcut package: {exc}", flush=True)
        return None
    print(f"TEAM SHORTCUT ZIP: {archive}", flush=True)
    return archive


def stop_child(process):
    if process and process.poll() is None:
        if os.name == "nt":
            # The Windows venv launcher can create another Python process.
            # Stop only this child tree, not every Python process on the PC.
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
            try:
                process.wait(timeout=8)
                return
            except subprocess.TimeoutExpired:
                pass
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description="Share Moble Kurly over HTTPS.")
    parser.add_argument("--port", type=int, default=5001)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Choose a port between 1024 and 65535.")
    if not TUNNEL_EXE.is_file():
        raise SystemExit("tools/cloudflared.exe is missing. See README.md.")

    # Never attach the public tunnel to an unrelated server already on this port.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", args.port))
        except OSError:
            raise SystemExit(f"Port {args.port} is in use. Try --port 5002.")

    server = None
    tunnel = None
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        server = subprocess.Popen(
            [sys.executable, "-m", "waitress", f"--listen=127.0.0.1:{args.port}",
             "--threads=4", "--no-expose-tracebacks", "app:app"],
            cwd=ROOT, creationflags=flags,
        )
        origin = f"http://127.0.0.1:{args.port}"
        ready = False
        for _ in range(40):
            if server.poll() is not None:
                raise RuntimeError("The shop server exited during startup.")
            try:
                with urlopen(origin, timeout=3) as response:
                    ready = response.status == 200
                if ready:
                    break
            except (URLError, TimeoutError):
                time.sleep(0.5)
        if not ready:
            raise RuntimeError("The shop did not become ready. Check MySQL and .env.")

        print(f"Local shop is ready: {origin}", flush=True)
        print("Creating the public HTTPS address. Keep this process running.", flush=True)
        tunnel = subprocess.Popen(
            [str(TUNNEL_EXE), "tunnel", "--no-autoupdate", "--protocol", "http2",
             "--url", origin],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=flags,
        )
        published_address = None
        for line in tunnel.stdout:
            print(line.rstrip(), flush=True)
            match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if match:
                address = match.group(0)
                print(f"\nMOBLE KURLY PUBLIC URL: {address}\n", flush=True)
                if address != published_address:
                    published_address = address
                    publish_live_shortcut(address)
            if server.poll() is not None:
                raise RuntimeError("The shop server stopped.")
        raise RuntimeError("The public tunnel stopped.")
    except KeyboardInterrupt:
        print("\nStopping public access and the share server.", flush=True)
    finally:
        stop_child(tunnel)
        stop_child(server)


if __name__ == "__main__":
    main()
