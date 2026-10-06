"""
detect_cameras.py — OAK-D camera detection and live test
Run this standalone to see exactly which OAK-D devices are connected
and whether each one can actually open and deliver frames.

Usage:
    python3 detect_cameras.py
"""

import sys
import time

try:
    import depthai as dai
except ImportError:
    print("ERROR: depthai is not installed.")
    print("       pip install depthai --break-system-packages")
    sys.exit(1)

print(f"depthai version: {dai.__version__}\n")

# -----------------------------------------------------------------------
# Step 1: Discover devices — try every known API variant
# -----------------------------------------------------------------------
devs = []

# Try DeviceBootloader first (depthai 3.x)
try:
    devs = dai.DeviceBootloader.getAllAvailableDevices()
    print(f"[discovery] dai.DeviceBootloader.getAllAvailableDevices() → {len(devs)} device(s)")
except Exception as e:
    print(f"[discovery] DeviceBootloader method failed: {e}")

# Fall back to Device.getAllAvailableDevices (depthai 2.x)
if not devs:
    try:
        devs = dai.Device.getAllAvailableDevices()
        print(f"[discovery] dai.Device.getAllAvailableDevices() → {len(devs)} device(s)")
    except Exception as e:
        print(f"[discovery] Device method failed: {e}")

if not devs:
    print("\nNo OAK-D devices found. Check USB connections and try again.")
    sys.exit(1)

# -----------------------------------------------------------------------
# Step 2: Print every attribute on the first DeviceInfo so we know
#         exactly what fields depthai exposes on THIS install
# -----------------------------------------------------------------------
print("\n--- DeviceInfo attributes (from first device) ---")
d0 = devs[0]
for attr in dir(d0):
    if attr.startswith("_"):
        continue
    try:
        val = getattr(d0, attr)
        if not callable(val):
            print(f"  .{attr} = {val!r}")
    except Exception:
        pass
print("-------------------------------------------------\n")

# -----------------------------------------------------------------------
# Step 3: Extract MXID using whatever attribute exists
# -----------------------------------------------------------------------
def get_mxid(dev) -> str:
    for attr in ("mxid", "getMxId", "deviceId", "getDeviceId", "name"):
        val = getattr(dev, attr, None)
        if val is None:
            continue
        if callable(val):
            try:
                result = val()
                if result:
                    return str(result)
            except Exception:
                pass
        elif val:
            return str(val)
    return "unknown"

print(f"Found {len(devs)} OAK-D device(s):\n")
for i, dev in enumerate(devs):
    mxid = get_mxid(dev)
    print(f"  Device {i}: MXID={mxid}")

# -----------------------------------------------------------------------
# Step 4: Try to open each device and grab one frame
# -----------------------------------------------------------------------
print("\n--- Opening each device and grabbing a test frame ---\n")

for i, dev_info in enumerate(devs):
    mxid = get_mxid(dev_info)
    print(f"[device {i}] MXID={mxid}  opening...", flush=True)

    try:
        with dai.Pipeline(dai.Device(dev_info)) as pipeline:
            cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
            out = cam.requestOutput(size=(640, 400), type=dai.ImgFrame.Type.BGR888p, fps=5)
            q   = out.createOutputQueue()
            pipeline.start()

            print(f"[device {i}] pipeline started — waiting for frame...", flush=True)

            frame = None
            deadline = time.time() + 5.0
            while time.time() < deadline:
                try:
                    msg = q.tryGet()
                    if msg is not None:
                        frame = msg.getCvFrame()
                        break
                except Exception:
                    pass
                time.sleep(0.05)

            if frame is not None:
                h, w = frame.shape[:2]
                print(f"[device {i}] ✓ WORKING  — got {w}x{h} frame")
            else:
                print(f"[device {i}] ✗ TIMEOUT  — device opened but no frame in 5s")

    except Exception as e:
        print(f"[device {i}] ✗ FAILED   — {e}")

    print()

print("Done.")