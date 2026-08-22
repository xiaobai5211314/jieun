#!/usr/bin/env python3
"""Split the v4 idle master into a fixed body and movable iris layers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


EYES = {
    "left": {"center": (282, 117), "radius": (7, 6)},
    "right": {"center": (341, 117), "radius": (7, 6)},
}
MAX_GAZE = (6, 4)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output_dir", type=Path)
    return parser.parse_args()


def ellipse_alpha(width: int, height: int, feather: float = 0.24) -> np.ndarray:
    yy, xx = np.indices((height, width), dtype=np.float32)
    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0
    nx = (xx - cx) / max(cx, 1.0)
    ny = (yy - cy) / max(cy, 1.0)
    distance = np.sqrt(nx * nx + ny * ny)
    return np.clip((1.0 - distance) / feather, 0.0, 1.0)


def compose(
    base: Image.Image,
    patches: dict[str, Image.Image],
    positions: dict[str, tuple[int, int]],
    offset: tuple[int, int],
) -> Image.Image:
    output = base.copy()
    for name, patch in patches.items():
        x, y = positions[name]
        output.alpha_composite(patch, (x + offset[0], y + offset[1]))
    return output


def main() -> None:
    args = parse_args()
    source = Image.open(args.input).convert("RGBA")
    source_array = np.array(source)
    alpha = source_array[:, :, 3]
    subject_bbox = Image.fromarray(alpha).getbbox()
    if subject_bbox is None:
        raise ValueError("source image is empty")

    left = max(0, subject_bbox[0] - 12)
    top = max(0, subject_bbox[1] - 12)
    right = min(source.width, subject_bbox[2] + 12)
    bottom = min(source.height, subject_bbox[3] + 12)

    rgb = source_array[:, :, :3].copy()
    inpaint_mask = np.zeros(alpha.shape, dtype=np.uint8)
    for eye in EYES.values():
        center = eye["center"]
        radius = eye["radius"]
        cv2.ellipse(
            inpaint_mask,
            center,
            (radius[0] + 1, radius[1] + 1),
            0,
            0,
            360,
            255,
            -1,
        )
    inpainted = cv2.inpaint(rgb, inpaint_mask, 3, cv2.INPAINT_TELEA)
    base_array = np.dstack((inpainted, alpha))
    base_array[alpha == 0, :3] = 0
    base = Image.fromarray(base_array, "RGBA").crop((left, top, right, bottom))

    patches: dict[str, Image.Image] = {}
    positions: dict[str, tuple[int, int]] = {}
    metadata_eyes: dict[str, object] = {}
    for name, eye in EYES.items():
        cx, cy = eye["center"]
        rx, ry = eye["radius"]
        patch_box = (cx - rx, cy - ry, cx + rx + 1, cy + ry + 1)
        patch_array = source_array[
            patch_box[1] : patch_box[3],
            patch_box[0] : patch_box[2],
        ].copy()
        feather = ellipse_alpha(patch_array.shape[1], patch_array.shape[0])
        patch_array[:, :, 3] = np.round(
            patch_array[:, :, 3].astype(np.float32) * feather
        ).astype(np.uint8)
        patch_array[patch_array[:, :, 3] == 0, :3] = 0
        patch = Image.fromarray(patch_array, "RGBA")
        position = (patch_box[0] - left, patch_box[1] - top)
        patches[name] = patch
        positions[name] = position
        metadata_eyes[name] = {
            "position": list(position),
            "size": list(patch.size),
            "center": [position[0] + rx, position[1] + ry],
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    base.save(args.output_dir / "base.png", optimize=True)
    for name, patch in patches.items():
        patch.save(args.output_dir / f"{name}-iris.png", optimize=True)

    config = {
        "canvasSize": list(base.size),
        "sourceCrop": [left, top, right, bottom],
        "maxGaze": list(MAX_GAZE),
        "eyes": metadata_eyes,
    }
    (args.output_dir / "gaze-rig.json").write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )

    directions = [
        (-MAX_GAZE[0], -MAX_GAZE[1]),
        (0, -MAX_GAZE[1]),
        (MAX_GAZE[0], -MAX_GAZE[1]),
        (-MAX_GAZE[0], 0),
        (0, 0),
        (MAX_GAZE[0], 0),
        (-MAX_GAZE[0], MAX_GAZE[1]),
        (0, MAX_GAZE[1]),
        (MAX_GAZE[0], MAX_GAZE[1]),
    ]
    labels = ["UL", "U", "UR", "L", "CENTER", "R", "DL", "D", "DR"]
    face_box = (205, 55, 415, 190)
    sheet = Image.new("RGB", (630, 405), "white")
    for index, (offset, label) in enumerate(zip(directions, labels)):
        frame = compose(base, patches, positions, offset)
        face = frame.crop(face_box)
        preview = Image.new("RGBA", face.size, "white")
        preview.alpha_composite(face)
        preview = preview.convert("RGB")
        draw = ImageDraw.Draw(preview)
        draw.rectangle((0, 0, 58, 18), fill=(20, 20, 20))
        draw.text((5, 3), label, fill="white")
        sheet.paste(preview, ((index % 3) * 210, (index // 3) * 135))
    sheet.save(args.output_dir / "gaze-directions-qa.png", quality=95)

    print(
        json.dumps(
            {
                "ok": True,
                "input": str(args.input),
                "outputDir": str(args.output_dir),
                **config,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
