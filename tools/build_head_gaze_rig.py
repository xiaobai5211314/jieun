#!/usr/bin/env python3
"""Build a layered Jieun rig whose eyes lead and head follows the cursor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


EYES = {
    "left": {"center": (605, 137), "radius": (6, 5)},
    "right": {"center": (654, 137), "radius": (6, 5)},
}
SOURCE_HEAD_BOX = (445, 8, 815, 350)
SOURCE_NECK_PIVOT = (629, 248)
MAX_GAZE = (5, 3)
MAX_HEAD_TRANSLATION = (10, 7)
MAX_HEAD_ROTATION = 4.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("body_source", type=Path)
    parser.add_argument("head_source", type=Path)
    parser.add_argument("output_dir", type=Path)
    return parser.parse_args()


def soft_ellipse(
    shape: tuple[int, int],
    center: tuple[float, float],
    radius: tuple[float, float],
    feather: float,
) -> np.ndarray:
    height, width = shape
    yy, xx = np.indices((height, width), dtype=np.float32)
    nx = (xx - center[0]) / max(radius[0], 1.0)
    ny = (yy - center[1]) / max(radius[1], 1.0)
    distance = np.sqrt(nx * nx + ny * ny)
    return np.clip((1.0 - distance) / max(feather, 1e-4), 0.0, 1.0)


def eye_feather(width: int, height: int) -> np.ndarray:
    yy, xx = np.indices((height, width), dtype=np.float32)
    nx = (xx - (width - 1) / 2.0) / max((width - 1) / 2.0, 1.0)
    ny = (yy - (height - 1) / 2.0) / max((height - 1) / 2.0, 1.0)
    distance = np.sqrt(nx * nx + ny * ny)
    return np.clip((1.0 - distance) / 0.35, 0.0, 1.0)


def compose_frame(
    body: Image.Image,
    head_base: Image.Image,
    head_position: tuple[int, int],
    head_pivot: tuple[int, int],
    eye_patches: dict[str, Image.Image],
    eye_positions: dict[str, tuple[int, int]],
    direction: tuple[float, float],
) -> Image.Image:
    dx, dy = direction
    head = head_base.copy()
    gaze_x = round(dx * MAX_GAZE[0])
    gaze_y = round(dy * MAX_GAZE[1])
    for name, patch in eye_patches.items():
        x, y = eye_positions[name]
        head.alpha_composite(patch, (x + gaze_x, y + gaze_y))

    angle = dx * MAX_HEAD_ROTATION
    rotated = head.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        center=head_pivot,
        expand=False,
    )
    move_x = round(dx * MAX_HEAD_TRANSLATION[0])
    move_y = round(dy * MAX_HEAD_TRANSLATION[1])
    output = body.copy()
    output.alpha_composite(
        rotated,
        (head_position[0] + move_x, head_position[1] + move_y),
    )
    return output


def main() -> None:
    args = parse_args()
    body_source = Image.open(args.body_source).convert("RGBA")
    head_source = Image.open(args.head_source).convert("RGBA")
    if body_source.size != head_source.size:
        raise ValueError(
            f"source size mismatch: {body_source.size} != {head_source.size}"
        )

    body_rgba = np.array(body_source)
    head_rgba = np.array(head_source)
    source_alpha = np.maximum(body_rgba[:, :, 3], head_rgba[:, :, 3])
    subject_box = Image.fromarray(source_alpha).getbbox()
    if subject_box is None:
        raise ValueError("source image is empty")

    crop_left = max(0, subject_box[0] - 24)
    crop_top = max(0, subject_box[1] - 16)
    crop_right = min(body_source.width, subject_box[2] + 24)
    crop_bottom = min(body_source.height, subject_box[3] + 14)
    canvas_box = (crop_left, crop_top, crop_right, crop_bottom)

    height, width = source_alpha.shape
    # The movable patch includes the complete head and upper hair. The body is
    # cleared with a slightly smaller mask, leaving a hidden overlap that keeps
    # small cursor-driven rotations from opening a transparent seam at the neck.
    upper = soft_ellipse(
        (height, width),
        center=(629.0, 145.0),
        radius=(122.0, 142.0),
        feather=0.11,
    )
    lower_hair = soft_ellipse(
        (height, width),
        center=(629.0, 232.0),
        radius=(176.0, 112.0),
        feather=0.13,
    )
    head_mask = np.maximum(upper, lower_hair)
    clear_upper = soft_ellipse(
        (height, width),
        center=(629.0, 145.0),
        radius=(111.0, 132.0),
        feather=0.10,
    )
    clear_lower = soft_ellipse(
        (height, width),
        center=(629.0, 228.0),
        radius=(163.0, 99.0),
        feather=0.12,
    )
    body_clear = np.maximum(clear_upper, clear_lower)

    body_layer = body_rgba.copy()
    body_layer[:, :, 3] = np.round(
        body_layer[:, :, 3].astype(np.float32) * (1.0 - body_clear)
    ).astype(np.uint8)
    body_layer[body_layer[:, :, 3] == 0, :3] = 0
    body = Image.fromarray(body_layer, "RGBA").crop(canvas_box)

    head_layer = head_rgba.copy()
    head_layer[:, :, 3] = np.round(
        head_layer[:, :, 3].astype(np.float32) * head_mask
    ).astype(np.uint8)
    head_layer[head_layer[:, :, 3] == 0, :3] = 0

    # Remove the original irises from the movable head. Their tiny patches are
    # restored separately and can lead the slower head movement.
    head_rgb = head_layer[:, :, :3].copy()
    inpaint_mask = np.zeros((height, width), dtype=np.uint8)
    for eye in EYES.values():
        cx, cy = eye["center"]
        rx, ry = eye["radius"]
        cv2.ellipse(
            inpaint_mask,
            (cx, cy),
            (rx + 1, ry + 1),
            0,
            0,
            360,
            255,
            -1,
        )
    inpainted_rgb = cv2.inpaint(head_rgb, inpaint_mask, 3, cv2.INPAINT_TELEA)
    head_layer[:, :, :3] = inpainted_rgb

    head_left, head_top, head_right, head_bottom = SOURCE_HEAD_BOX
    head = Image.fromarray(head_layer, "RGBA").crop(SOURCE_HEAD_BOX)
    head_position = (head_left - crop_left, head_top - crop_top)
    head_pivot = (
        SOURCE_NECK_PIVOT[0] - head_left,
        SOURCE_NECK_PIVOT[1] - head_top,
    )

    eye_patches: dict[str, Image.Image] = {}
    eye_positions: dict[str, tuple[int, int]] = {}
    eye_metadata: dict[str, object] = {}
    for name, eye in EYES.items():
        cx, cy = eye["center"]
        rx, ry = eye["radius"]
        box = (cx - rx, cy - ry, cx + rx + 1, cy + ry + 1)
        patch_array = head_rgba[box[1] : box[3], box[0] : box[2]].copy()
        feather = eye_feather(patch_array.shape[1], patch_array.shape[0])
        patch_array[:, :, 3] = np.round(
            patch_array[:, :, 3].astype(np.float32) * feather
        ).astype(np.uint8)
        patch_array[patch_array[:, :, 3] == 0, :3] = 0
        patch = Image.fromarray(patch_array, "RGBA")
        position = (box[0] - head_left, box[1] - head_top)
        eye_patches[name] = patch
        eye_positions[name] = position
        eye_metadata[name] = {
            "position": list(position),
            "size": list(patch.size),
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    body.save(args.output_dir / "body.png", optimize=True)
    head.save(args.output_dir / "head-base.png", optimize=True)
    for name, patch in eye_patches.items():
        patch.save(args.output_dir / f"{name}-iris.png", optimize=True)
    idle_composite = compose_frame(
        body,
        head,
        head_position,
        head_pivot,
        eye_patches,
        eye_positions,
        (0.0, 0.0),
    )
    idle_composite.save(args.output_dir / "idle-composite.png", optimize=True)

    config = {
        "canvasSize": list(body.size),
        "sourceCrop": list(canvas_box),
        "head": {
            "position": list(head_position),
            "size": list(head.size),
            "pivot": list(head_pivot),
            "maxTranslation": list(MAX_HEAD_TRANSLATION),
            "maxRotationDegrees": MAX_HEAD_ROTATION,
            "smoothing": 0.10,
        },
        "eyes": {
            "maxGaze": list(MAX_GAZE),
            "smoothing": 0.24,
            "layers": eye_metadata,
        },
        "display": {
            "defaultHeight": 900,
            "minimumHeight": 420,
            "maximumHeight": 1400,
        },
    }
    (args.output_dir / "head-gaze-rig.json").write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )

    directions = [
        (-1.0, -1.0),
        (0.0, -1.0),
        (1.0, -1.0),
        (-1.0, 0.0),
        (0.0, 0.0),
        (1.0, 0.0),
        (-1.0, 1.0),
        (0.0, 1.0),
        (1.0, 1.0),
    ]
    labels = ["UL", "UP", "UR", "LEFT", "CENTER", "RIGHT", "DL", "DOWN", "DR"]
    qa_sheet = Image.new("RGB", (780, 690), (34, 31, 42))
    face_box = (
        480 - crop_left,
        18 - crop_top,
        778 - crop_left,
        325 - crop_top,
    )
    for index, (direction, label) in enumerate(zip(directions, labels)):
        frame = compose_frame(
            body,
            head,
            head_position,
            head_pivot,
            eye_patches,
            eye_positions,
            direction,
        )
        face = frame.crop(face_box)
        tile = Image.new("RGBA", (260, 230), (34, 31, 42, 255))
        resized = face.copy()
        resized.thumbnail((250, 215), Image.Resampling.LANCZOS)
        tile.alpha_composite(
            resized,
            ((260 - resized.width) // 2, (230 - resized.height) // 2),
        )
        draw = ImageDraw.Draw(tile)
        draw.rounded_rectangle((7, 7, 72, 30), 7, fill=(15, 15, 18, 220))
        draw.text((14, 12), label, fill=(255, 255, 255, 255))
        qa_sheet.paste(tile.convert("RGB"), ((index % 3) * 260, (index // 3) * 230))
    qa_sheet.save(args.output_dir / "head-gaze-directions-qa.png", quality=96)

    print(
        json.dumps(
            {
                "ok": True,
                "bodySource": str(args.body_source),
                "headSource": str(args.head_source),
                "outputDir": str(args.output_dir),
                **config,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
