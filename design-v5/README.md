# Jieun v5 design

Version 5 rebuilds the Jieun pet around the supplied IU reference while preserving the package's fixed Codex atlas contract.

## Visual system

- polished semi-realistic 3D character treatment;
- long dark hair, round glasses, silver hairpin and earrings;
- oversized black track jacket with white bands;
- layered white slit dress, pastel striped socks and white-black sneakers;
- clean RGBA edges with zero RGB residue in fully transparent pixels.

## Two intentionally different compositions

- `spritesheet.png` / `spritesheet.webp`: large upper-body close compositions so the face remains readable in the host's 192x208 cell;
- `head-rig/`: complete full-body artwork for the optional 420-1400 pixel desktop overlay.

## Actions

The atlas contains the required nine rows and frame counts:

1. idle breathing - 6 frames;
2. run right - 8 frames;
3. run left - 8 frames;
4. wave - 4 frames;
5. jump - 5 frames;
6. failed/disappointed - 8 frames;
7. waiting/thinking - 6 frames;
8. working/typing - 6 frames;
9. reviewing/inspection - 6 frames.

## Cursor-follow rig

`head-gaze-rig.json` describes separate body, head, left-iris and right-iris layers. Eyes use faster smoothing (`0.24`); the head uses slower smoothing (`0.10`), up to 10x7 source pixels of translation and 4 degrees of rotation. The body remains anchored.

## Rebuild

```powershell
python .\tools\build_head_gaze_rig.py .\design-v5\poses\base-final.png .\design-v5\poses\base-master.png .\design-v5\head-rig
Copy-Item .\design-v5\head-rig\idle-composite.png .\design-v5\poses\idle.png -Force
python .\tools\build_v5_atlas.py --poses-dir .\design-v5\poses --png .\spritesheet.png --webp .\spritesheet.webp --contact-sheet .\design-v5\atlas-contact-sheet.png
```

The original image-generation outputs remain in the Codex generated-images directory. The selected v5 source renders are copied into `source-chroma/`; extracted transparent masters are in `poses/`.
