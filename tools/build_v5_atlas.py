#!/usr/bin/env python3
"""Build the v5 close-composition Codex atlas with nine action rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


CELL_WIDTH = 192
CELL_HEIGHT = 208
ATLAS_COLUMNS = 8
ATLAS_ROWS = 9

POSE_FILES = {
    "idle": "idle.png",
    "run": "run-right.png",
    "wave": "wave.png",
    "jump": "jump.png",
    "failed": "failed.png",
    "waiting": "waiting.png",
    "work": "work.png",
    "review": "review.png",
}

# The host cell is only 192x208. A full-body composition makes the face too
# small regardless of source resolution, so v5 deliberately uses a readable
# head-to-hip / head-to-thigh crop for built-in Codex rendering.
CROP_FRACTIONS = {
    "idle": 0.46,
    "run": 0.58,
    "wave": 0.50,
    "jump": 0.60,
    "failed": 0.48,
    "waiting": 0.50,
    "work": 0.52,
    "review": 0.50,
}

POSE_BOUNDS = {
    "idle": (180, 204),
    "run": (188, 202),
    "wave": (184, 204),
    "jump": (188, 202),
    "failed": (178, 204),
    "waiting": (180, 204),
    "work": (188, 204),
    "review": (184, 204),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poses-dir", type=Path, required=True)
    parser.add_argument("--png", type=Path, required=True)
    parser.add_argument("--webp", type=Path, required=True)
    parser.add_argument("--contact-sheet", type=Path)
    parser.add_argument("--edge-qa", type=Path)
    return parser.parse_args()


def clear_transparent_rgb(image: Image.Image) -> Image.Image:
    rgba = np.array(image.convert("RGBA"))
    rgba[rgba[:, :, 3] == 0, :3] = 0
    return Image.fromarray(rgba, "RGBA")


def premultiplied_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    rgba = np.array(image.convert("RGBA"), dtype=np.float32) / 255.0
    alpha = rgba[:, :, 3:4]
    premultiplied = rgba[:, :, :3] * alpha
    interpolation = cv2.INTER_AREA if size[0] < image.width else cv2.INTER_LANCZOS4
    resized_rgb = cv2.resize(premultiplied, size, interpolation=interpolation)
    resized_alpha = cv2.resize(alpha, size, interpolation=interpolation)
    if resized_alpha.ndim == 2:
        resized_alpha = resized_alpha[:, :, None]
    straight = np.divide(
        resized_rgb,
        np.maximum(resized_alpha, 1e-6),
        out=np.zeros_like(resized_rgb),
        where=resized_alpha > 1e-6,
    )
    output = np.dstack((straight, resized_alpha))
    output = np.clip(np.round(output * 255.0), 0, 255).astype(np.uint8)
    # Final-cell defringe: replace the outer two rendered pixels from a nearby
    # interior color. This removes any remaining chroma rim after the large
    # action masters are reduced to the host's 192x208 cell.
    rendered_foreground = output[:, :, 3] > 2
    rendered_distance = cv2.distanceTransform(
        rendered_foreground.astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    rendered_core = rendered_distance >= 3.0
    rendered_ring = rendered_foreground & (rendered_distance < 2.1)
    if rendered_core.any():
        rendered_source = (~rendered_core).astype(np.uint8)
        _, rendered_labels = cv2.distanceTransformWithLabels(
            rendered_source,
            cv2.DIST_L2,
            5,
            labelType=cv2.DIST_LABEL_PIXEL,
        )
        rendered_coords = np.argwhere(rendered_core)
        rendered_nearest_coords = rendered_coords[rendered_labels - 1]
        rendered_rgb = output[
            rendered_nearest_coords[:, :, 0],
            rendered_nearest_coords[:, :, 1],
            :3,
        ]
        output[rendered_ring, :3] = rendered_rgb[rendered_ring]
    output[output[:, :, 3] == 0, :3] = 0
    return Image.fromarray(output, "RGBA")


def close_crop(image: Image.Image, name: str) -> Image.Image:
    rgba = clear_transparent_rgb(image)
    alpha = np.array(rgba.getchannel("A"))
    ys, xs = np.where(alpha > 0)
    if not len(xs):
        raise ValueError(f"pose {name} is empty")
    subject_left = int(xs.min())
    subject_top = int(ys.min())
    subject_right = int(xs.max() + 1)
    subject_bottom = int(ys.max() + 1)
    subject_height = subject_bottom - subject_top
    crop_bottom = min(
        rgba.height,
        subject_top + round(subject_height * CROP_FRACTIONS[name]),
    )

    region_alpha = alpha[subject_top:crop_bottom]
    region_ys, region_xs = np.where(region_alpha > 0)
    if not len(region_xs):
        raise ValueError(f"pose {name} close crop is empty")
    left = max(0, int(region_xs.min()) - 16)
    right = min(rgba.width, int(region_xs.max() + 1) + 16)
    top = max(0, subject_top - 10)
    # Extend the crop slightly below the visible cell. The host clips that
    # edge, so the portrait reads as intentionally close rather than chopped.
    bottom = min(rgba.height, crop_bottom + 24)
    return rgba.crop((left, top, right, bottom))


def load_poses(directory: Path) -> dict[str, Image.Image]:
    poses: dict[str, Image.Image] = {}
    for name, filename in POSE_FILES.items():
        poses[name] = close_crop(Image.open(directory / filename), name)
    return poses


def render_pose(
    poses: dict[str, Image.Image],
    name: str,
    *,
    scale: float = 1.0,
    dx: int = 0,
    dy: int = 0,
    flip: bool = False,
    baseline: int = 214,
) -> Image.Image:
    source = poses[name]
    if flip:
        source = source.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    max_width, max_height = POSE_BOUNDS[name]
    ratio = min(max_width / source.width, max_height / source.height) * scale
    size = (
        max(1, round(source.width * ratio)),
        max(1, round(source.height * ratio)),
    )
    sprite = premultiplied_resize(source, size)
    frame = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    x = (CELL_WIDTH - sprite.width) // 2 + dx
    y = baseline - sprite.height + dy
    frame.alpha_composite(sprite, (x, y))
    return clear_transparent_rgb(frame)


def build_rows(poses: dict[str, Image.Image]) -> list[list[Image.Image]]:
    rows: list[list[Image.Image]] = []
    rows.append(
        [
            render_pose(poses, "idle", scale=1.000),
            render_pose(poses, "idle", scale=1.006, dy=-1),
            render_pose(poses, "idle", scale=1.012, dy=-2),
            render_pose(poses, "idle", scale=1.016, dy=-2),
            render_pose(poses, "idle", scale=1.009, dy=-1),
            render_pose(poses, "idle", scale=1.000),
        ]
    )

    run_scales = (0.982, 0.994, 1.008, 1.018, 1.008, 0.994, 0.982, 0.990)
    run_dx = (-4, -2, 0, 3, 3, 0, -2, -4)
    run_dy = (3, 0, -3, -5, -3, 0, 3, 1)
    rows.append(
        [
            render_pose(
                poses,
                "run",
                scale=run_scales[index],
                dx=run_dx[index],
                dy=run_dy[index],
            )
            for index in range(8)
        ]
    )
    rows.append(
        [
            render_pose(
                poses,
                "run",
                scale=run_scales[index],
                dx=-run_dx[index],
                dy=run_dy[index],
                flip=True,
            )
            for index in range(8)
        ]
    )

    rows.append(
        [
            render_pose(poses, "idle", scale=0.995),
            render_pose(poses, "wave", scale=0.994, dx=-1),
            render_pose(poses, "wave", scale=1.014, dx=1, dy=-2),
            render_pose(poses, "idle", scale=1.000),
        ]
    )
    rows.append(
        [
            render_pose(poses, "idle", scale=0.970, dy=4),
            render_pose(poses, "jump", scale=0.960, dy=0),
            render_pose(poses, "jump", scale=1.000, dy=-6),
            render_pose(poses, "jump", scale=0.982, dy=-2),
            render_pose(poses, "idle", scale=1.000),
        ]
    )
    rows.append(
        [
            render_pose(poses, "failed", scale=scale, dx=dx, dy=dy)
            for scale, dx, dy in (
                (0.990, -1, 0),
                (0.996, 0, 1),
                (1.002, 1, 2),
                (1.008, 1, 3),
                (1.012, 0, 4),
                (1.008, -1, 3),
                (1.002, -1, 2),
                (0.996, 0, 1),
            )
        ]
    )
    for name in ("waiting", "work", "review"):
        rows.append(
            [
                render_pose(poses, name, scale=scale, dx=dx, dy=dy)
                for scale, dx, dy in (
                    (0.994, -1, 0),
                    (1.002, 0, -1),
                    (1.010, 1, -2),
                    (1.006, 1, -1),
                    (1.000, -1, 0),
                    (0.994, 0, 0),
                )
            ]
        )

    expected = (6, 8, 8, 4, 5, 8, 6, 6, 6)
    actual = tuple(len(row) for row in rows)
    if actual != expected:
        raise AssertionError(f"unexpected frame counts: {actual}")
    return rows


def compose_atlas(rows: list[list[Image.Image]]) -> Image.Image:
    atlas = Image.new(
        "RGBA",
        (CELL_WIDTH * ATLAS_COLUMNS, CELL_HEIGHT * ATLAS_ROWS),
        (0, 0, 0, 0),
    )
    for row_index, frames in enumerate(rows):
        for column_index, frame in enumerate(frames):
            atlas.alpha_composite(
                frame,
                (column_index * CELL_WIDTH, row_index * CELL_HEIGHT),
            )
    return clear_transparent_rgb(atlas)


def save_contact_sheet(rows: list[list[Image.Image]], output: Path) -> None:
    labels = ["idle", "run right", "run left", "wave", "jump", "failed", "waiting", "work", "review"]
    sheet = Image.new("RGB", (CELL_WIDTH * 3, CELL_HEIGHT * 3), (34, 31, 42))
    for index, (label, row) in enumerate(zip(labels, rows)):
        tile = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (34, 31, 42, 255))
        tile.alpha_composite(row[len(row) // 2])
        draw = ImageDraw.Draw(tile)
        draw.rounded_rectangle((5, 5, 86, 26), 6, fill=(14, 14, 17, 220))
        draw.text((11, 10), label, fill=(255, 255, 255, 255))
        sheet.paste(tile.convert("RGB"), ((index % 3) * CELL_WIDTH, (index // 3) * CELL_HEIGHT))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=96)


def save_edge_qa(rows: list[list[Image.Image]], output: Path) -> None:
    samples = [("idle", rows[0][0]), ("run", rows[1][3]), ("wave", rows[3][2])]
    backgrounds = [
        ("white", (255, 255, 255, 255)),
        ("dark", (25, 27, 32, 255)),
        ("purple", (91, 55, 126, 255)),
    ]
    sheet = Image.new("RGB", (CELL_WIDTH * 3, CELL_HEIGHT * 3), "white")
    for row_index, (sample_name, sample) in enumerate(samples):
        for column_index, (background_name, color) in enumerate(backgrounds):
            tile = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), color)
            tile.alpha_composite(sample)
            draw = ImageDraw.Draw(tile)
            label = f"{sample_name} / {background_name}"
            draw.rounded_rectangle((5, 5, 121, 26), 6, fill=(12, 12, 15, 220))
            draw.text((10, 10), label, fill=(255, 255, 255, 255))
            sheet.paste(
                tile.convert("RGB"),
                (column_index * CELL_WIDTH, row_index * CELL_HEIGHT),
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=96)


def main() -> None:
    args = parse_args()
    poses = load_poses(args.poses_dir)
    rows = build_rows(poses)
    atlas = compose_atlas(rows)
    args.png.parent.mkdir(parents=True, exist_ok=True)
    args.webp.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(args.png, format="PNG", optimize=True)
    atlas.save(
        args.webp,
        format="WEBP",
        lossless=True,
        quality=100,
        method=6,
        exact=True,
    )
    if args.contact_sheet:
        save_contact_sheet(rows, args.contact_sheet)
    if args.edge_qa:
        save_edge_qa(rows, args.edge_qa)
    print(
        json.dumps(
            {
                "ok": True,
                "poses": list(poses),
                "cropFractions": CROP_FRACTIONS,
                "rows": [len(row) for row in rows],
                "size": list(atlas.size),
                "png": str(args.png),
                "webp": str(args.webp),
                "contactSheet": str(args.contact_sheet) if args.contact_sheet else None,
                "edgeQa": str(args.edge_qa) if args.edge_qa else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
