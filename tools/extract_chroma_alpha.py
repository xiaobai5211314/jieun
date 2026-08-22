#!/usr/bin/env python3
"""Convert a flat chroma-green image into a clean, defringed RGBA cutout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--opaque-excess", type=float, default=35.0)
    parser.add_argument("--transparent-excess", type=float, default=180.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rgb = np.array(Image.open(args.input).convert("RGB"), dtype=np.float32)
    height, width = rgb.shape[:2]

    border = np.concatenate(
        (
            rgb[:24].reshape(-1, 3),
            rgb[-24:].reshape(-1, 3),
            rgb[:, :24].reshape(-1, 3),
            rgb[:, -24:].reshape(-1, 3),
        ),
        axis=0,
    )
    key = np.median(border, axis=0)
    # Image generation can vary the brightness of an otherwise flat chroma
    # key. Validate by both useful luminance and strong green dominance so a
    # darker vivid green remains safe while natural/ambiguous backgrounds fail.
    if key[1] < 180 or key[1] < key[0] + 100 or key[1] < key[2] + 100:
        raise ValueError(f"background is not chroma green: median={key.tolist()}")

    green_excess = rgb[:, :, 1] - np.maximum(rgb[:, :, 0], rgb[:, :, 2])
    key_excess = float(key[1] - max(key[0], key[2]))
    # Keep the CLI value as an upper cap, then adapt to darker generated
    # greens. A ten-point margin makes the flat key fully transparent while
    # retaining a useful antialiasing ramp toward the foreground threshold.
    transparent_excess = min(args.transparent_excess, key_excess - 10.0)
    span = transparent_excess - args.opaque_excess
    if span <= 0:
        raise ValueError("transparent threshold must exceed opaque threshold")

    alpha = np.clip(
        (transparent_excess - green_excess) / span,
        0.0,
        1.0,
    )
    alpha[green_excess <= args.opaque_excess] = 1.0
    alpha[green_excess >= transparent_excess] = 0.0

    # Keep only the main connected subject, but retain its antialiased ring.
    support = (alpha > 0.02).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        support,
        connectivity=8,
    )
    if count <= 1:
        raise ValueError("no foreground component detected")
    subject = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    alpha[labels != subject] = 0.0

    # Recover foreground RGB from C = alpha * F + (1 - alpha) * key.
    original_rgb = rgb.copy()
    partial = (alpha > 0.0) & (alpha < 1.0)
    safe_alpha = np.maximum(alpha[partial, None], 1e-4)
    recovered = (
        rgb[partial] - (1.0 - safe_alpha) * key[None, :]
    ) / safe_alpha
    rgb[partial] = np.clip(recovered, 0.0, 255.0)

    # Very low-alpha recovery amplifies tiny key-color errors into magenta or
    # green speckles. Borrow the nearest opaque subject color for that outer
    # ring, blending back to the recovered color toward the solid interior.
    opaque_core = alpha >= 0.98
    if opaque_core.any():
        distance_source = (~opaque_core).astype(np.uint8)
        _, nearest_labels = cv2.distanceTransformWithLabels(
            distance_source,
            cv2.DIST_L2,
            5,
            labelType=cv2.DIST_LABEL_PIXEL,
        )
        core_coords = np.argwhere(opaque_core)
        nearest_coords = core_coords[nearest_labels - 1]
        nearest_rgb = original_rgb[
            nearest_coords[:, :, 0],
            nearest_coords[:, :, 1],
        ]
        recovery_weight = np.clip((alpha - 0.45) / 0.40, 0.0, 1.0)
        edge_blend = (
            nearest_rgb * (1.0 - recovery_weight[:, :, None])
            + rgb * recovery_weight[:, :, None]
        )
        rgb[partial] = edge_blend[partial]

    # Remove residual green only in the narrow silhouette ring. Interior
    # colors (including the pastel socks) remain untouched.
    foreground = (alpha > 0.0).astype(np.uint8)
    inner_distance = cv2.distanceTransform(
        foreground,
        cv2.DIST_L2,
        3,
    )
    edge_ring = (foreground > 0) & (inner_distance <= 6.0)
    neutral_ceiling = np.maximum(rgb[:, :, 0], rgb[:, :, 2]) + 2.0
    rgb[:, :, 1][edge_ring] = np.minimum(
        rgb[:, :, 1][edge_ring],
        neutral_ceiling[edge_ring],
    )

    alpha_u8 = np.round(alpha * 255.0).astype(np.uint8)
    rgba = np.dstack((np.round(rgb).astype(np.uint8), alpha_u8))
    rgba[alpha_u8 == 0, :3] = 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(args.output, optimize=True)

    ys, xs = np.where(alpha_u8 > 0)
    bbox = [
        int(xs.min()),
        int(ys.min()),
        int(xs.max() + 1),
        int(ys.max() + 1),
    ]
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(args.input),
                "output": str(args.output),
                "size": [width, height],
                "key_rgb": [round(float(value), 2) for value in key],
                "transparent_excess": round(transparent_excess, 2),
                "bbox": bbox,
                "opaque_pixels": int((alpha_u8 == 255).sum()),
                "partial_pixels": int(partial.sum()),
                "transparent_pixels": int((alpha_u8 == 0).sum()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
