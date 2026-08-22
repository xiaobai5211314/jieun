# Jieun eye-gaze overlay

This optional Windows overlay keeps the character body stationary and moves only the two iris layers toward the system mouse pointer.

## Start

Double-click `Start-JieunGaze.cmd`, or run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\JieunGaze.ps1
```

The Win32 layered window uses per-pixel alpha transparency and is click-through. It does not use a color-key background. Use the `Jieun Gaze` system-tray icon to pause/resume the gaze or exit.

## Important behavior

- the character stays anchored to one screen corner;
- only the irises move toward the cursor;
- the body does not chase the pointer;
- starting it twice does not create duplicates;
- it does not create startup persistence or a scheduled task.

## Options

```powershell
# Different corner and size.
.\JieunGaze.ps1 -Anchor BottomLeft -DisplayHeight 560

# Asset/config validation without opening the overlay.
.\JieunGaze.ps1 -SelfTest

# Run the real WinForms/Win32 layered-window loop and close after five seconds.
.\JieunGaze.ps1 -RuntimeTestSeconds 5
```
