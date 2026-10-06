# Logitech F710 VESC Steering Control

These files are a starting point for desk-testing a brushed DC steering motor through a VESC and encoder. They do not modify PyVESC itself.

## What this does

`f710_vesc_steering.py` reads a Logitech F710 through Windows XInput, clamps the steering target to `-15` to `+15` steering degrees, and sends VESC `COMM_SET_POS` commands. The default center is `0` degrees.

The script includes two software safety behaviors:

- It only sends steering commands while you hold the enable button. The default is `LB`.
- It clamps the requested steering angle to `--max-angle-deg`, which defaults to `15`.

Keep using real mechanical stops, low current limits, and conservative VESC Tool settings. Software limits are helpful, but they should not be the only thing protecting the hardware.

## Install

From the repo root:

```powershell
python -m pip install -e .
python -m pip install -r steering_f710\requirements-steering.txt
```

## Check your serial port

```powershell
python steering_f710\f710_vesc_steering.py --list-ports
```

On Windows the VESC will usually look like `COM3`, `COM4`, etc.

## Check your F710 mapping

Put the F710 in `X` mode, plug in the USB receiver, turn the controller on, then run:

```powershell
python steering_f710\f710_gamepad_check.py
```

Move the left stick side to side. You should see `left=(...)` change from about `-1.000` to `+1.000`. The steering script defaults to `--axis left_x`.

If X mode does not appear through XInput on your laptop, use D mode instead:

```powershell
python steering_f710\f710_gamepad_check_dinput.py
```

Move the left stick side to side. If axis `0` moves from about `-1.000` to `+1.000`, keep the default `--axis 0` for the D-mode steering script.

## First dry run

This reads the controller without connecting to the VESC:

```powershell
python steering_f710\f710_vesc_steering.py --dry-run
```

For D mode:

```powershell
python steering_f710\f710_vesc_steering_dinput.py --dry-run
```

Hold `LB` and move the stick. The printed `steering=` value should stay between `-15.00 deg` and `+15.00 deg`.

## Run with the VESC

Replace `COM3` with your VESC serial port:

```powershell
python steering_f710\f710_vesc_steering.py --port COM3
```

For D mode:

```powershell
python steering_f710\f710_vesc_steering_dinput.py --port COM3
```

For the current robot calibration, the D-mode script already defaults to:

```text
port COM7, axis 2, center 15, left -40, right 55, wrap 0, ramp 280, min step 0.8, smoothing 0.03, rate 100
```

So the normal robot command is:

```powershell
python steering_f710\f710_vesc_steering_dinput.py
```

## Dual VESC Steering And Drive

`f710_dual_vesc_drive.py` keeps the working steering defaults and adds a second VESC for drive motors.

Controls:

- right stick X: steering
- left stick Y: drive forward/reverse
- button 5: deadman enable

Find the second VESC port:

```powershell
python steering_f710\f710_dual_vesc_drive.py --list-ports
```

First test only the drive VESC with the robot lifted:

```powershell
python steering_f710\f710_dual_vesc_drive.py --disable-steering --drive-port COM8 --max-duty 0.05
```

Replace `COM8` with the drive VESC port. Push the left stick up/down gently. If forward/reverse are backwards, add `--invert-drive`.

Then run steering and drive together:

```powershell
python steering_f710\f710_dual_vesc_drive.py --drive-port COM8 --max-duty 0.05
```

Increase `--max-duty` gradually after the direction is confirmed.

The default command is:

- left stick X controls target angle
- hold `LB` to enable
- `Start` tries to set the current VESC `pid_pos_now` as the center offset
- Ctrl+C exits and commands the center position before closing the serial port

## Useful tuning options

```powershell
python steering_f710\f710_vesc_steering.py --port COM3 --max-angle-deg 10
```

Use a smaller limit for first motion tests.

```powershell
python steering_f710\f710_vesc_steering.py --port COM3 --invert-axis
```

Use this if pushing the stick right turns left.

```powershell
python steering_f710\f710_vesc_steering.py --port COM3 --command-scale -1
```

Use this if the VESC position direction is reversed but you want to keep the joystick direction unchanged.

```powershell
python steering_f710\f710_vesc_steering.py --port COM3 --center-offset-deg 123.4
```

Use this if your VESC encoder zero is not steering center. You can also press the zero button while running if `pid_pos_now` is being reported correctly.

```powershell
python steering_f710\f710_vesc_steering.py --port COM3 --enable-button rb
```

Use this to change the hold-to-enable button. Available button names are `a`, `b`, `x`, `y`, `lb`, `rb`, `start`, `back`, `left_stick`, `right_stick`, and the d-pad names.

For D mode, slow the steering command ramp with:

```powershell
python steering_f710\f710_vesc_steering_dinput.py --port COM3 --axis 2 --ramp-motor-deg-per-s 3
```

The D-mode default is `6` motor degrees per second, so a move from `0` to `15` degrees takes about `2.5` seconds before gear ratio effects.

For the current desk steering calibration from VESC Tool:

```powershell
python steering_f710\f710_vesc_steering_dinput.py --port COM7 --axis 2 --center-motor-deg 2 --left-end-motor-deg 273 --right-end-motor-deg 84 --ramp-motor-deg-per-s 90
```

Those endpoints cross the `0/360` wrap. The script uses the short wrapped path, so center `2` to left `273` moves about `-89` degrees rather than taking the long way around.

For the robot steering calibration from VESC Tool:

```powershell
python steering_f710\f710_vesc_steering_dinput.py --port COM7 --axis 2 --center-motor-deg 15 --left-end-motor-deg 45 --right-end-motor-deg 345 --ramp-motor-deg-per-s 30 --invert
```

This also crosses the `0/360` wrap. Center `15` to right `345` is treated as `-30` degrees through `0`, not `+330` degrees around the long way.

## VESC Tool setup checklist

Before running the script against hardware:

- Configure the VESC for your motor type and encoder.
- Confirm the encoder position changes smoothly in VESC Tool.
- Configure position PID mode/current limits conservatively.
- Test small position steps in VESC Tool before using the gamepad.
- Lift or unload the desk setup if possible for the first test.
- Keep one hand ready to power off the 16 V battery.

## Important note about angle units

This script sends `SetPosition(angle_deg)` through PyVESC. On common VESC firmware, `COMM_SET_POS` is interpreted as a position target in degrees for the configured position control mode. If your steering mechanism has a gearbox, belt ratio, or encoder scaling between motor and steering wheel, adjust `--command-scale` and `--center-offset-deg` so `+15` printed steering degrees corresponds to the actual steering wheel angle.
