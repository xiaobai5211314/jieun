#!/usr/bin/env python3
"""Build a crisp contract-compatible atlas from independent v4 pose masters."""

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

POSE_FILES = {
    "idle": "idle-final-readable-wide.png",
    "run": "run-right.png",
    "wave": "wave.png",
    "jump": "jump.png",
    "failed": "failed.png",
    "waiting": "waiting.png",
    "work": "work.png",
    "review": "review.png",
}

POSE_BOUNDS = {
    "idle": (180, 198),
    "run": (188, 196),
    "wave": (180, 198),
    "jump": (188, 192),
    "failed": (180, 198),
    "waiting": (180, 198),
    "work": (188, 194),
    "review": (180, 198),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--poses-dir", type=Path, required=True)
    parser.add_argument("--png", type=Path, required=True)
    parser.add_argument("--webp", type=Path, required=True)
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
    output[output[:, :, 3] == 0, :3] = 0
    return Image.fromarray(output, "RGBA")


def load_poses(directory: Path) -> dict[str, Image.Image]:
    poses: dict[str, Image.Image] = {}
    for name, filename in POSE_FILES.items():
        image = clear_transparent_rgb(Image.open(directory / filename))
        bbox = image.getbbox()
        if bbox is None:
            raise ValueError(f"pose {name} is empty")
        poses[name] = image.crop(bbox)
    return poses


def render_pose(
    poses: dict[str, Image.Image],
    name: str,
    *,
    scale: float = 1.0,
    dx: int = 0,
    dy: int = 0,
    flip: bool = False,
    baseline: int = 204,
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

    run_scales = (0.980, 0.995, 1.010, 1.020, 1.010, 0.995, 0.980, 0.990)
    run_dx = (-3, -1, 1, 3, 3, 1, -1, -3)
    run_dy = (2, -1, -4, -6, -4, -1, 2, 0)
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
            render_pose(poses, "wave", scale=0.990, dy=0),
            render_pose(poses, "wave", scale=1.012, dy=-2),
            render_pose(poses, "idle", scale=1.000),
        ]
    )

    rows.append(
        [
            render_pose(poses, "idle", scale=0.965, dy=4),
            render_pose(poses, "jump", scale=0.960, dy=0, baseline=204),
            render_pose(poses, "jump", scale=1.000, dy=-5, baseline=204),
            render_pose(poses, "jump", scale=0.980, dy=-2, baseline=204),
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

    rows.append(
        [
            render_pose(poses, "waiting", scale=scale, dx=dx, dy=dy)
            for scale, dx, dy in (
                (0.995, -1, 0),
                (1.002, 0, -1),
                (1.010, 1, -2),
                (1.006, 1, -1),
                (1.000, -1, 0),
                (0.995, 0, 0),
            )
        ]
    )

    rows.append(
        [
            render_pose(poses, "work", scale=scale, dx=dx, dy=dy)
            for scale, dx, dy in (
                (0.990, -1, 0),
                (0.998, 0, -1),
                (1.008, 1, -2),
                (1.004, 1, -1),
                (0.998, -1, 0),
                (0.992, 0, 0),
            )
        ]
    )

    rows.append(
        [
            render_pose(poses, "review", scale=scale, dx=dx, dy=dy)
            for scale, dx, dy in (
                (0.995, -1, 0),
                (1.002, 0, -1),
                (1.010, 1, -2),
                (1.006, 1, -1),
                (1.000, -1, 0),
                (0.995, 0, 0),
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
    print(
        json.dumps(
            {
                "ok": True,
                "poses": list(poses),
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
