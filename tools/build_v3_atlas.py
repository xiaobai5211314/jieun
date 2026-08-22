#!/usr/bin/env python3
"""Build the contract-compatible Jieun v3 atlas from the generated key poses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


CELL_WIDTH = 192
CELL_HEIGHT = 208
ATLAS_COLUMNS = 8
ATLAS_ROWS = 9
POSE_COLUMNS = 4
POSE_ROWS = 2

# Key-pose board order:
# 0 idle, 1 running-right, 2 waving, 3 jumping,
# 4 failed, 5 waiting, 6 active-work, 7 review.
POSE_BOXES = {
    0: (110, 178),
    1: (182, 152),
    2: (120, 178),
    3: (170, 150),
    4: (110, 176),
    5: (110, 176),
    6: (150, 145),
    7: (110, 176),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poses", type=Path, required=True)
    parser.add_argument("--png", type=Path, required=True)
    parser.add_argument("--webp", type=Path, required=True)
    return parser.parse_args()


def clear_transparent_rgb(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    source_pixels = (
        image.get_flattened_data()
        if hasattr(image, "get_flattened_data")
        else image.getdata()
    )
    pixels = [
        (0, 0, 0, 0) if pixel[3] == 0 else pixel
        for pixel in source_pixels
    ]
    image.putdata(pixels)
    return image


def load_poses(path: Path) -> list[Image.Image]:
    board = Image.open(path).convert("RGBA")
    board_array = np.array(board)
    foreground = (board_array[:, :, 3] > 8).astype(np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        foreground,
        connectivity=8,
    )

    components = [
        component
        for component in range(1, count)
        if stats[component, cv2.CC_STAT_AREA] >= 500
    ]
    components.sort(
        key=lambda component: stats[component, cv2.CC_STAT_AREA],
        reverse=True,
    )
    components = components[: POSE_COLUMNS * POSE_ROWS]
    if len(components) != POSE_COLUMNS * POSE_ROWS:
        raise ValueError(
            f"expected {POSE_COLUMNS * POSE_ROWS} poses, found {len(components)}"
        )

    components.sort(
        key=lambda component: (
            0 if centroids[component][1] < board.height / 2 else 1,
            centroids[component][0],
        )
    )

    poses: list[Image.Image] = []
    for component in components:
        left = stats[component, cv2.CC_STAT_LEFT]
        top = stats[component, cv2.CC_STAT_TOP]
        width = stats[component, cv2.CC_STAT_WIDTH]
        height = stats[component, cv2.CC_STAT_HEIGHT]
        component_array = board_array[top : top + height, left : left + width].copy()
        component_mask = labels[top : top + height, left : left + width] == component
        component_array[~component_mask, :] = 0
        poses.append(Image.fromarray(component_array, "RGBA"))
    return poses


def render_pose(
    poses: list[Image.Image],
    pose_index: int,
    *,
    scale: float = 1.0,
    angle: float = 0.0,
    dx: int = 0,
    dy: int = 0,
    flip: bool = False,
    baseline: int = 198,
) -> Image.Image:
    source = poses[pose_index]
    if flip:
        source = source.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    max_width, max_height = POSE_BOXES[pose_index]
    ratio = min(max_width / source.width, max_height / source.height) * scale
    width = max(1, round(source.width * ratio))
    height = max(1, round(source.height * ratio))
    sprite = source.resize((width, height), Image.Resampling.LANCZOS)
    if angle:
        sprite = sprite.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=True,
        )

    frame = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    x = (CELL_WIDTH - sprite.width) // 2 + dx
    y = baseline - sprite.height + dy
    frame.alpha_composite(sprite, (x, y))
    return clear_transparent_rgb(frame)


def build_rows(poses: list[Image.Image]) -> list[list[Image.Image]]:
    rows: list[list[Image.Image]] = []

    # Calm breathing and weight shift.
    rows.append(
        [
            render_pose(poses, 0, scale=1.000, dy=0),
            render_pose(poses, 0, scale=1.006, angle=-0.3, dy=-1),
            render_pose(poses, 0, scale=1.012, angle=0.3, dy=-2),
            render_pose(poses, 0, scale=1.016, dy=-2),
            render_pose(poses, 0, scale=1.009, angle=-0.2, dy=-1),
            render_pose(poses, 0, scale=1.000, dy=0),
        ]
    )

    run_angles = (-5, -2, 1, 4, 5, 2, -1, -4)
    run_scales = (0.98, 1.00, 1.02, 1.00, 0.98, 1.00, 1.02, 1.00)
    run_dy = (1, -2, -5, -2, 1, -2, -5, -2)
    run_dx = (-2, 0, 2, 0, -2, 0, 2, 0)
    rows.append(
        [
            render_pose(
                poses,
                1,
                scale=run_scales[i],
                angle=run_angles[i],
                dx=run_dx[i],
                dy=run_dy[i],
            )
            for i in range(8)
        ]
    )
    rows.append(
        [
            render_pose(
                poses,
                1,
                scale=run_scales[i],
                angle=-run_angles[i],
                dx=-run_dx[i],
                dy=run_dy[i],
                flip=True,
            )
            for i in range(8)
        ]
    )

    rows.append(
        [
            render_pose(poses, 0, scale=0.995),
            render_pose(poses, 2, scale=0.990, angle=-1, dy=0),
            render_pose(poses, 2, scale=1.015, angle=1, dy=-2),
            render_pose(poses, 0, scale=1.000),
        ]
    )

    rows.append(
        [
            render_pose(poses, 0, scale=0.960, dy=4),
            render_pose(poses, 3, scale=0.970, angle=-2, dy=-8, baseline=194),
            render_pose(poses, 3, scale=1.020, angle=1, dy=-24, baseline=194),
            render_pose(poses, 3, scale=0.990, angle=2, dy=-9, baseline=194),
            render_pose(poses, 0, scale=1.000, dy=0),
        ]
    )

    rows.append(
        [
            render_pose(poses, 4, scale=0.990, angle=0, dy=0),
            render_pose(poses, 4, scale=0.995, angle=0.6, dy=1),
            render_pose(poses, 4, scale=1.000, angle=1.2, dy=2),
            render_pose(poses, 4, scale=1.005, angle=0.8, dy=3),
            render_pose(poses, 4, scale=1.010, angle=0, dy=4),
            render_pose(poses, 4, scale=1.005, angle=-0.6, dy=3),
            render_pose(poses, 4, scale=1.000, angle=-0.3, dy=2),
            render_pose(poses, 4, scale=0.995, angle=0, dy=1),
        ]
    )

    rows.append(
        [
            render_pose(poses, 5, scale=0.995, angle=-0.8, dx=-1),
            render_pose(poses, 5, scale=1.005, angle=0, dy=-1),
            render_pose(poses, 5, scale=1.010, angle=0.8, dx=1, dy=-2),
            render_pose(poses, 5, scale=1.005, angle=0.2, dy=-1),
            render_pose(poses, 5, scale=1.000, angle=-0.5, dx=-1),
            render_pose(poses, 5, scale=0.995, angle=0),
        ]
    )

    rows.append(
        [
            render_pose(poses, 6, scale=0.990, angle=-0.4, dx=-1, dy=0),
            render_pose(poses, 6, scale=1.000, angle=0.2, dy=-1),
            render_pose(poses, 6, scale=1.010, angle=0.5, dx=1, dy=-2),
            render_pose(poses, 6, scale=1.005, angle=-0.2, dy=-1),
            render_pose(poses, 6, scale=1.000, angle=0.3, dx=-1),
            render_pose(poses, 6, scale=0.995, angle=0),
        ]
    )

    rows.append(
        [
            render_pose(poses, 7, scale=0.995, angle=-1.0, dx=-1),
            render_pose(poses, 7, scale=1.005, angle=-0.3, dy=-1),
            render_pose(poses, 7, scale=1.010, angle=0.6, dx=1, dy=-2),
            render_pose(poses, 7, scale=1.008, angle=1.0, dx=1, dy=-1),
            render_pose(poses, 7, scale=1.002, angle=0.2),
            render_pose(poses, 7, scale=0.995, angle=-0.6, dx=-1),
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


def main() -> None:
    args = parse_args()
    poses = load_poses(args.poses)
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

    print(
        json.dumps(
            {
                "ok": True,
                "poses": len(poses),
                "rows": [len(row) for row in rows],
                "size": list(atlas.size),
                "png": str(args.png),
                "webp": str(args.webp),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
