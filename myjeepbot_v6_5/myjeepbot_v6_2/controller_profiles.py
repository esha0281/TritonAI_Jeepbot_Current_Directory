# ===============================================
# CONTROLLER PROFILES
# Per-controller axis/button/tuning maps, kept out of myconfig.py so the
# config file stays short. myconfig.py picks a name (CONTROLLER = "...") and
# calls resolve() to pull the matching values.
#
# Axis/button indices come from each device's HID layout and are NOT the same
# between controllers. To find them: run
#   python3 controller_axes_test.py
# wiggle one control, and read off the index that changes.
#
# device_name is a case-insensitive substring used to grab the right USB
# device when more than one joystick is plugged in. Leave "" to just use the
# first joystick found (fine when only one controller is connected).
# ===============================================

CONTROLLER_PROFILES = {
    "f710": {
        "device_name":     "",      # F710 dongle is usually the only joystick
        "steering_axis":   2,       # right-stick X (D mode)
        "drive_axis":      1,       # left-stick Y
        "deadman_button":  5,       # right bumper
        "deadzone":        0.08,
        "invert_steering": False,
        "invert_drive":    True,
    },
    "radiomaster": {
        "device_name":     "Arduino",   # Leonardo enumerates as "Arduino ..."
        # ---- CONFIRM THESE TWO WITH controller_axes_test.py ----
        "steering_axis":   2,
        "drive_axis":      1,
        "deadman_button":  0,       # LBtn on the Leonardo (button 0)
        "deadzone":        0.15,    # bumped up: SBUS center isn't exactly 0
        "invert_steering": False,
        "invert_drive":    False,
    },
}


def resolve(controller: str) -> dict:
    """Return the profile dict for `controller`, or raise if it's unknown."""
    if controller not in CONTROLLER_PROFILES:
        raise ValueError(
            f"CONTROLLER={controller!r} must be one of {list(CONTROLLER_PROFILES)}"
        )
    return CONTROLLER_PROFILES[controller]
