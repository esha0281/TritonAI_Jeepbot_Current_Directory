"""
oak_recorder.py — Standalone OAK-D Pro Wide image recorder
============================================================
Records JPEG frames to a Donkey Car-compatible tub independently of
the JeepBot drive process.  Includes a live MJPEG stream so you can
monitor the exact framing and exposure that drive.py will see.

Camera settings mirror what drive.py / camera.py use so recorded data
looks identical to inference-time frames:
  • Same resolution  (default 1280×720, override with --resolution)
  • Same JPEG quality (default 60,     override with --quality)
  • Same OAK-D ISP pipeline (auto-exposure, auto-white-balance)

Tub layout (Donkey Car compatible)
-----------------------------------
tub/<session>/
    images/
        frame_0000001.jpg
        frame_0000002.jpg
        ...
    records.jsonl          ← one JSON line per frame

Each JSONL record
-----------------
{
  "frame_idx": 1,
  "image_file": "images/frame_0000001.jpg",
  "timestamp_ms": 1716300000123,
  "width": 1280,
  "height": 720,
  "quality": 60
}

Steering / duty are omitted — this script is for data collection only;
labels are added later during annotation or copied from a simultaneous
drive log.

Live stream
-----------
Open http://<host>:8080 in a browser (or VLC) while recording.
The stream is a standard MJPEG feed — no JS, no dependencies.

Usage
-----
    python oak_recorder.py                        # defaults
    python oak_recorder.py --fps 60               # higher capture rate
    python oak_recorder.py --resolution 640 480   # smaller frames
    python oak_recorder.py --quality 85           # higher JPEG quality
    python oak_recorder.py --tub ./my_tub         # custom tub root
    python oak_recorder.py --port 9090            # different stream port
    python oak_recorder.py --no-stream            # disable web stream
    python oak_recorder.py --mxid 1234ABCD        # pin to specific OAK-D
    python oak_recorder.py --show-preview         # OpenCV local window
    python oak_recorder.py --list-devices         # print connected OAK-Ds
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import depthai as dai
import numpy as np


# -----------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Standalone OAK-D Pro Wide recorder with live MJPEG stream."
    )
    p.add_argument("--tub",         default="tub_plant_model",        help="Root directory for tub sessions (default: tub)")
    p.add_argument("--fps",         type=int,   default=30,  help="Camera target FPS (default: 30)")
    p.add_argument("--resolution",  type=int,   nargs=2, metavar=("W", "H"), default=[1280, 720],
                   help="Capture resolution (default: 1280 720)")
    p.add_argument("--record-fps", type=float, default=2.0,help="Frames per second saved to disk (default: 5; 0 = save every camera frame)")
    p.add_argument("--quality",     type=int,   default=60,  help="JPEG quality 0-100 (default: 60, matches drive.py)")
    p.add_argument("--port",        type=int,   default=8080, help="MJPEG stream port (default: 8080)")
    p.add_argument("--no-stream",   action="store_true",   help="Disable the MJPEG web stream")
    p.add_argument("--show-preview",action="store_true",   help="Show local OpenCV preview window")
    p.add_argument("--mxid",        default="",            help="Pin to a specific OAK-D device serial")
    p.add_argument("--list-devices",action="store_true",   help="List connected OAK-D devices and exit")

    # Recording control
    p.add_argument("--record",      action="store_true",   help="Start recording immediately (default: press R to toggle)")
    p.add_argument("--max-frames",  type=int,   default=0,  help="Stop after N frames (0 = unlimited)")

    return p.parse_args()


# -----------------------------------------------------------------------
# Device helpers  (mirrors camera.py logic)
# -----------------------------------------------------------------------

def _mxid(dev) -> str | None:
    for attr in ("getMxId", "getDeviceId", "mxid", "deviceId"):
        fn = getattr(dev, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
        elif fn:
            return fn
    return None


def list_devices() -> None:
    devs = dai.Device.getAllAvailableDevices()
    if not devs:
        print("No OAK-D devices found.")
        return
    print(f"Found {len(devs)} OAK-D device(s):")
    for d in devs:
        print(f"  MXID: {_mxid(d)}")


def find_device(mxid: str) -> dai.DeviceInfo | None:
    devs = dai.Device.getAllAvailableDevices()
    if not devs:
        return None
    if not mxid:
        return devs[0]
    for d in devs:
        if _mxid(d) == mxid:
            return d
    print(f"[recorder] WARNING: Device '{mxid}' not found. Using first available.")
    return devs[0] if devs else None


# -----------------------------------------------------------------------
# Tub writer  (background thread, non-blocking)
# -----------------------------------------------------------------------

class TubWriter:
    """
    Writes (jpeg_bytes, metadata) to disk in a background thread.
    Uses the same layout as tub_recorder.py so data is interchangeable.
    """

    _FLUSH_EVERY = 10   # sync JSONL every N frames

    def __init__(self, tub_root: str, width: int, height: int, quality: int):
        session     = datetime.now().strftime("pe_v2_36_sunny_%Y%m%d_%H%M%S")
        self.session_dir = Path(tub_root) / session
        self.img_dir     = self.session_dir / "images"
        self.img_dir.mkdir(parents=True, exist_ok=True)

        self._record_path = self.session_dir / "records.jsonl"
        self._record_file = self._record_path.open("w", buffering=1)

        self._width   = width
        self._height  = height
        self._quality = quality

        self._counter  = itertools.count()
        self._wq: queue.Queue = queue.Queue(maxsize=120)
        self._active   = True
        self._dropped  = 0
        self._saved    = 0

        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="tub-writer"
        )
        self._thread.start()
        print(f"[tub] Session: {self.session_dir}")

    # ------------------------------------------------------------------

    def push(self, jpeg_bytes: bytes) -> None:
        """Non-blocking enqueue. Drops frame if writer is backed up."""
        idx = next(self._counter)
        record = {
            "frame_idx":    idx,
            "image_file":   f"images/pe_v2_36_sunny_frame_{idx:07d}.jpg",
            "timestamp_ms": int(time.time() * 1000),
            "width":        self._width,
            "height":       self._height,
            "quality":      self._quality,
        }
        try:
            self._wq.put_nowait((record, jpeg_bytes))
        except queue.Full:
            self._dropped += 1

    def close(self) -> None:
        self._active = False
        self._wq.join()
        self._record_file.close()
        msg = f"[tub] Saved {self._saved} frames → {self.session_dir}"
        if self._dropped:
            msg += f"  ({self._dropped} dropped)"
        print(msg)

    @property
    def saved(self) -> int:
        return self._saved

    # ------------------------------------------------------------------

    def _loop(self) -> None:
        flush_ctr = 0
        while self._active or not self._wq.empty():
            try:
                record, jpeg_bytes = self._wq.get(timeout=0.5)
            except queue.Empty:
                continue

            img_path = self.session_dir / record["image_file"]
            fd = os.open(img_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                os.write(fd, jpeg_bytes)
            finally:
                os.close(fd)

            self._record_file.write(json.dumps(record) + "\n")
            flush_ctr += 1
            if flush_ctr >= self._FLUSH_EVERY:
                self._record_file.flush()
                flush_ctr = 0

            self._saved += 1
            self._wq.task_done()


# -----------------------------------------------------------------------
# MJPEG stream server
# -----------------------------------------------------------------------

class _MJPEGHandler(BaseHTTPRequestHandler):
    """Serves a single MJPEG stream at / and a minimal status page at /status."""

    # Injected by start_mjpeg_server()
    _stream_queue: queue.Queue
    _get_stats: callable

    def log_message(self, *_):
        pass  # silence access log

    def do_GET(self):
        if self.path == "/status":
            self._serve_status()
        else:
            self._serve_stream()

    def _serve_stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                try:
                    jpg = self._stream_queue.get(timeout=2.0)
                except queue.Empty:
                    continue
                frame = (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + jpg
                    + b"\r\n"
                )
                self.wfile.write(frame)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_status(self):
        stats = self._get_stats()
        body = (
            f"<html><body style='font-family:monospace'>"
            f"<h2>OAK-D Recorder</h2>"
            f"<p>Recording: {'YES &#128534;' if stats['recording'] else 'NO'}</p>"
            f"<p>Frames saved: {stats['saved']}</p>"
            f"<p>Camera FPS: {stats['fps']:.1f}</p>"
            f"<p>Resolution: {stats['width']}x{stats['height']}</p>"
            f"<p>JPEG quality: {stats['quality']}</p>"
            f"<p>Session: {stats['session']}</p>"
            f"<p><a href='/'>Live stream</a></p>"
            f"</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _put_drop_oldest(q: queue.Queue, data: bytes) -> None:
    """Drop oldest entry if full — never blocks."""
    if q.full():
        try:
            q.get_nowait()
        except queue.Empty:
            pass
    try:
        q.put_nowait(data)
    except queue.Full:
        pass


def start_mjpeg_server(
    port: int,
    stream_queue: queue.Queue,
    get_stats: callable,
) -> None:
    """Start MJPEG HTTP server in a daemon thread."""

    class _Handler(_MJPEGHandler):
        _stream_queue = stream_queue
        _get_stats    = staticmethod(get_stats)

    server = HTTPServer(("0.0.0.0", port), _Handler)

    t = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="mjpeg-server",
    )
    t.start()
    print(f"[stream] Live MJPEG at http://0.0.0.0:{port}  |  Status: http://0.0.0.0:{port}/status")

# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    if args.list_devices:
        list_devices()
        return 0

    width, height = args.resolution
    fps           = args.fps
    quality       = args.quality

    record_fps = args.record_fps

    if record_fps > 0:
        record_period = 1.0 / record_fps
    else:
        record_period = 0.0

    last_record_time = 0.0
    # ------------------------------------------------------------------
    # State shared between threads
    # ------------------------------------------------------------------
    recording    = args.record            # True = record immediately
    stream_queue = queue.Queue(maxsize=2) # MJPEG stream frames
    tub: TubWriter | None = None

    if recording:
        tub = TubWriter(args.tub, width, height, quality)

    # FPS tracking
    _fps_times: list[float] = []
    _fps_lock  = threading.Lock()

    def _measured_fps() -> float:
        with _fps_lock:
            now = time.time()
            cutoff = now - 2.0
            while _fps_times and _fps_times[0] < cutoff:
                _fps_times.pop(0)
            return len(_fps_times) / 2.0

    def _tick_fps() -> None:
        with _fps_lock:
            _fps_times.append(time.time())

    def get_stats() -> dict:
        return {
            "recording": recording,
            "saved":     tub.saved if tub else 0,
            "fps":       _measured_fps(),
            "width":     width,
            "height":    height,
            "quality":   quality,
            "session":   str(tub.session_dir) if tub else "—",
        }

    # ------------------------------------------------------------------
    # MJPEG stream server
    # ------------------------------------------------------------------
    if not args.no_stream:
        start_mjpeg_server(args.port, stream_queue, get_stats)

    # ------------------------------------------------------------------
    # OAK-D pipeline
    # ------------------------------------------------------------------
    device_info = find_device(args.mxid.strip())
    if device_info is None:
        print("[recorder] ERROR: No OAK-D device found.")
        return 1

    print(f"[recorder] Opening OAK-D  MXID={_mxid(device_info)}")
    print(f"[recorder] Resolution={width}x{height}  FPS={fps}  Quality={quality}")
    print(f"[recorder] Recording={'immediate' if recording else 'press R to start'}")
    if args.show_preview:
        print("[recorder] Preview window active — press R to toggle recording, Q to quit")
    else:
        print("[recorder] Press Ctrl+C to stop  |  send SIGUSR1 or use --record to auto-start")

    device_args = [device_info] if device_info else []

    try:
        device = dai.Device(*device_args)
        with dai.Pipeline(device) as pipeline_ctx:

            cam   = pipeline_ctx.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
            out   = cam.requestOutput(size=(width, height), type=dai.ImgFrame.Type.BGR888p, fps=fps)
            rgb_q = out.createOutputQueue()

            pipeline_ctx.start()
            print(f"[recorder] Camera started @ {width}x{height} {fps}fps.")

            frame_count = 0

            while True:
                # ---- Grab frame (blocks until OAK-D delivers one) ----
                msg   = rgb_q.get()
                frame = msg.getCvFrame()     # numpy BGR — identical to drive.py

                # ---- Encode JPEG — same settings as drive.py / camera.py ----
                ret, buf = cv2.imencode(
                    ".jpg", frame,
                    [int(cv2.IMWRITE_JPEG_QUALITY), quality],
                )
                if not ret:
                    continue
                jpg = buf.tobytes()

                _tick_fps()

                # ---- Push to tub writer ----
                if recording and tub is not None:

                    now = time.monotonic()

                    if (
                        record_period == 0.0
                        or
                        (now - last_record_time) >= record_period
                    ):
                        tub.push(jpg)
                        frame_count += 1
                        last_record_time = now

                # ---- Push to MJPEG stream (always, even when not recording) ----
                if not args.no_stream:
                    _put_drop_oldest(stream_queue, jpg)

                # ---- Local preview window ----
                if args.show_preview:
                    # Overlay recording status on frame
                    overlay = frame.copy()
                    rec_text = (
                        f"REC  {tub.saved if tub else 0} frames"
                        if recording else "STANDBY — press R to record"
                    )
                    fps_text = f"{_measured_fps():.1f} fps"
                    cv2.putText(overlay, rec_text, (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                                (0, 0, 255) if recording else (0, 255, 0), 2)
                    cv2.putText(overlay, fps_text, (10, 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                (255, 255, 255), 2)
                    cv2.imshow("OAK-D Recorder", overlay)

                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q') or key == 27:   # Q or ESC
                        break
                    elif key == ord('r'):
                        recording = not recording
                        if recording and tub is None:
                            tub = TubWriter(args.tub, width, height, quality)
                            print(f"\n[recorder] Recording STARTED → {tub.session_dir}")
                        elif not recording:
                            print("\n[recorder] Recording PAUSED")

                # ---- Console status (no preview window) ----
                else:
                    if frame_count % (fps * 2) == 0:   # every ~2 seconds
                        saved  = tub.saved if tub else 0
                        status = "REC" if recording else "standby"
                        print(
                            f"\r[{status}] saved={saved}  "
                            f"fps={_measured_fps():.1f}  "
                            f"q={quality}  {width}x{height}   ",
                            end="", flush=True,
                        )

                # ---- Max frames cutoff ----
                if args.max_frames > 0 and frame_count >= args.max_frames:
                    print(f"\n[recorder] Reached --max-frames {args.max_frames}. Stopping.")
                    break

    except KeyboardInterrupt:
        print("\n[recorder] Stopped by user.")
    finally:
        if tub is not None:
            tub.close()
        if args.show_preview:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    sys.exit(main())
