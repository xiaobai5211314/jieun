# Jieun desktop follower

This optional Windows overlay makes the same Jieun sprite follow the system mouse pointer. It is separate from the fixed Codex pet manifest because the verified Codex atlas contract does not expose a mouse-follow event field.

## Start

Double-click `Start-JieunFollower.cmd`, or run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\JieunFollower.ps1
```

The overlay is click-through and stays near the pointer. Use its system-tray icon to Pause/Resume or Exit.
Starting it again while it is already running exits quietly instead of creating a duplicate pet.

## Behavior

- moving right or left selects the matching run row;
- settling near the pointer returns to idle;
- a nearby left click triggers jump;
- idle time can trigger wave, waiting, laptop-work, or review;
- it does not add itself to Windows startup or create a scheduled task.

## Verification modes

```powershell
# Load the atlas and validate all nine states without opening the overlay.
.\JieunFollower.ps1 -SelfTest

# Run the real overlay loop and close automatically after three seconds.
.\JieunFollower.ps1 -RuntimeTestSeconds 3
```
