# Jieun v4 crisp-source and gaze design

## Correction from v3

The character body no longer follows the system pointer. The optional desktop overlay keeps the body anchored in one screen corner and moves only two iris layers toward the pointer.

The previous atlas used small figures extracted from a multi-pose board. Its idle figure occupied only 63x178 pixels inside a 192x208 cell (the pre-rebuild version was 93x198). The final v4 idle figure occupies 100x198, so the host size slider scales the character instead of mostly scaling transparent side margins. V4 uses an independent high-resolution source image per action and downsamples directly into the fixed atlas cell.

## Visual pipeline

- Built-in image generation was used in reference/edit mode with the user-provided IU photo and approved tall-proportion character as visual references.
- Each action was generated separately on a flat chroma-green background because the built-in generator did not return a usable alpha channel for the transparent-background request.
- `tools/extract_chroma_alpha.py` adapts to the actual chroma brightness, estimates alpha from green excess, and replaces unstable low-alpha key colors with the nearest opaque subject color before despilling the six-pixel silhouette ring.
- The final idle master receives a measured 1.08x horizontal correction in premultiplied-alpha space. Its height and long-leg proportions are unchanged; its predicted cell footprint increases from 93x198 to 100x198.
- `tools/build_v4_atlas.py` resizes in premultiplied-alpha space so fully transparent black RGB cannot contaminate antialiased edges.
- The fixed Codex atlas remains 1536x1872, 8 columns x 9 rows, with 192x208 cells and transparent unused cells.

## High-resolution action masters

The eight high-resolution transparent action masters are stored under `poses/`. The dynamic run/jump/work sources are 1024x1536; the final idle and the readable wave/failed/waiting/review sources are 1254x1254 before cropping/correction:

1. idle
2. running-right
3. waving
4. jumping
5. failed/sad
6. waiting
7. laptop work
8. review/thinking

The matching chroma sources are under `source-chroma/` so the alpha extraction remains reproducible.

## Eye-gaze rig

`tools/build_gaze_rig.py` produces:

- `gaze-rig/base.png`: stationary body with the two original irises removed;
- `gaze-rig/left-iris.png` and `right-iris.png`: movable iris layers;
- `gaze-rig/gaze-rig.json`: canvas, eye positions, and maximum offsets;
- `gaze-rig/gaze-directions-qa.png`: nine-direction static QA preview.

`desktop-gaze/JieunGaze.ps1` renders the rig through a Win32 layered window with per-pixel alpha. It never moves the body window after initial anchoring.

The built-in Codex pet schema exposes the atlas but no verified pointer/iris-layer hook. Therefore the built-in pet uses the crisp animated atlas, while system-pointer eye tracking is implemented by the optional `desktop-gaze` overlay.

## Prompt summary

The character is a tall adult-proportion 2D anime/semi-realistic game sprite with long dark hair, round glasses, silver hair clip, black-and-white oversized jacket, layered white dress, pastel socks, and white sneakers. Each prompt requests one full-body action, crisp eyes, a clean antialiased silhouette, no blur, no colored outline, no glow, no shadow, no detached fragments, and a flat chroma-green background.
