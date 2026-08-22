# Jieun v3 design

## Visual direction

- Reference: the user-provided IU photo is used only for the facial impression, long dark hair, round wire-frame glasses, silver hair clip, and black/white streetwear.
- Style: polished adult stylized 2D sprite with the reference image's elegant long-legged proportions, scaled uniformly to remain readable inside a 192x208 cell.
- Palette: charcoal black, ivory white, muted skin tones, restrained pastel sock accents, and silver accessories.
- Edge rule: true RGBA transparency only. No chroma-key canvas, colored outline, glow, detached shadow, labels, or grid lines.

## Codex animation map

| Row | State | Frames | Motion design |
| ---: | --- | ---: | --- |
| 0 | idle | 6 | breathing and subtle weight shift |
| 1 | running-right | 8 | right-facing sprint bounce |
| 2 | running-left | 8 | direction-correct mirrored sprint |
| 3 | waving | 4 | neutral, clear wave, return |
| 4 | jumping | 5 | anticipation, rise, peak, descend, settle |
| 5 | failed | 8 | lowered head and slow deflation |
| 6 | waiting | 6 | hands together and expectant sway |
| 7 | running | 6 | seated focused laptop work |
| 8 | review | 6 | chin-rest thinking and inspection |

The Codex package contract remains fixed at 8 columns x 9 rows. Extra behaviors are implemented by the optional desktop follower instead of adding ignored atlas rows or manifest fields.

## Mouse-follow behavior

`desktop-follower/JieunFollower.ps1` is a separate click-through Windows overlay that reads the same `spritesheet.png`:

- follows the cursor with a small offset;
- selects running-left or running-right based on travel direction;
- idles near the pointer;
- reacts to a left click with a jump;
- randomly cycles waving, waiting, focused work, and review while settled;
- exposes Pause/Resume and Exit through a tray icon.

It does not patch the Codex installation, create a scheduled task, or add startup persistence.

## Image-generation prompt summary

Built-in image generation was used with the IU reference photo as a visual reference. The final character anchor preserves the preferred tall, long-legged adult proportions together with the same glasses, hair, hair clip, black/white jacket, layered white dress, pastel socks, and white sneakers. The rejected short-legged draft is not used. The key-pose board requested exactly eight consistent poses: idle, running-right, waving, jumping, failed, waiting, active-work, and review. Background cleanup was completed deterministically after the generator returned a baked checkerboard instead of an alpha channel.
