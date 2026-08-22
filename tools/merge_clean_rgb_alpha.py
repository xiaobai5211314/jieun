#!/usr/bin/env python3
"""Combine a clean generated RGB render with a separately extracted alpha."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("rgb_image", type=Path)
    parser.add_argument("alpha_image", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--defringe-depth", type=float, default=8.0)
    parser.add_argument("--strip-light-side-matte", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rgb = np.array(Image.open(args.rgb_image).convert("RGB"), dtype=np.float32)
    alpha = np.array(
        Image.open(args.alpha_image).convert("RGBA").getchannel("A"),
        dtype=np.uint8,
    )
    if rgb.shape[:2] != alpha.shape:
        raise ValueError(
            f"size mismatch: RGB={rgb.shape[1]}x{rgb.shape[0]} "
            f"alpha={alpha.shape[1]}x{alpha.shape[0]}"
        )

    if args.strip_light_side_matte:
        height, width = alpha.shape
        yy, xx = np.indices(alpha.shape)
        channel_min = rgb.min(axis=2)
        channel_range = rgb.max(axis=2) - channel_min
        light_matte = (channel_min >= 225.0) & (channel_range <= 20.0)
        side_hair_zone = (yy < height * 0.29) & (
            (xx < width * 0.44) | (xx > width * 0.56)
        )
        alpha[light_matte & side_hair_zone] = 0

    foreground = alpha > 0
    depth = max(float(args.defringe_depth), 1.0)
    inner_distance = cv2.distanceTransform(
        foreground.astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    clean_core = inner_distance >= depth
    edge_ring = foreground & (inner_distance < depth)
    if not clean_core.any():
        raise ValueError("foreground has no interior core")

    distance_source = (~clean_core).astype(np.uint8)
    _, nearest_labels = cv2.distanceTransformWithLabels(
        distance_source,
        cv2.DIST_L2,
        5,
        labelType=cv2.DIST_LABEL_PIXEL,
    )
    core_coords = np.argwhere(clean_core)
    nearest_coords = core_coords[nearest_labels - 1]
    nearest_rgb = rgb[
        nearest_coords[:, :, 0],
        nearest_coords[:, :, 1],
    ]

    # The RGB render was generated on a light checkerboard. Its edge pixels
    # contain that matte even though the separate alpha is correct. Preserve
    # the silhouette and replace only the narrow RGB ring from inside out.
    edge_weight = np.clip(
        (depth - inner_distance) / max(depth * 0.75, 1.0),
        0.0,
        1.0,
    )
    blended = (
        nearest_rgb * edge_weight[:, :, None]
        + rgb * (1.0 - edge_weight[:, :, None])
    )
    rgb[edge_ring] = blended[edge_ring]

    rgba = np.dstack((np.round(rgb).astype(np.uint8), alpha))
    rgba[alpha == 0, :3] = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(args.output, optimize=True)

    ys, xs = np.where(alpha > 0)
    print(
        json.dumps(
            {
                "ok": True,
                "rgb_image": str(args.rgb_image),
                "alpha_image": str(args.alpha_image),
                "output": str(args.output),
                "size": [int(rgb.shape[1]), int(rgb.shape[0])],
                "bbox": [
                    int(xs.min()),
                    int(ys.min()),
                    int(xs.max() + 1),
                    int(ys.max() + 1),
                ],
                "transparent_rgb_residue": int(
                    np.count_nonzero(rgba[alpha == 0, :3])
                ),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
