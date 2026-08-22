# Jieun head + eye cursor-follow overlay

This optional Windows overlay keeps the full-body character anchored to a screen corner. Her eyes react first, then her head and upper hair follow the system mouse pointer with a softer delay.

## Start

Double-click `Start-JieunGaze.cmd`, or run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\JieunGaze.ps1
```

The Win32 layered window uses per-pixel alpha transparency and is click-through. It does not use a color-key background. Use the `Jieun Head Gaze` system-tray icon to pause/resume the motion or exit.

## Important behavior

- the character stays anchored to one screen corner;
- the eyes lead the cursor direction;
- the head and upper hair translate and rotate subtly after the eyes;
- the body stays anchored and does not chase the pointer;
- the default display height is `900`, with a supported range of `420` to `1400`;
- starting it twice does not create duplicates;
- it does not create startup persistence or a scheduled task.

## Options

```powershell
# Different corner and size.
.\JieunGaze.ps1 -Anchor BottomLeft -DisplayHeight 1100

# Asset/config validation without opening the overlay.
.\JieunGaze.ps1 -SelfTest

# Run the real WinForms/Win32 layered-window loop and close after five seconds.
.\JieunGaze.ps1 -RuntimeTestSeconds 5
```

The built-in Codex pet and this desktop overlay are separate renderers. The built-in pet uses a fixed 192x208 cell and therefore uses a close upper-body composition for readability; the desktop overlay keeps the complete long-legged full-body art.
