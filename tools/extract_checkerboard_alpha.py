#!/usr/bin/env python3
"""Extract a true alpha channel from a generated near-white checkerboard board."""

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
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--rows", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rgb = np.array(Image.open(args.input).convert("RGB"))
    height, width = rgb.shape[:2]
    if width % args.columns or height % args.rows:
        raise ValueError(
            f"image {width}x{height} does not divide into "
            f"{args.columns}x{args.rows}"
        )

    cell_width = width // args.columns
    cell_height = height // args.rows
    alpha = np.zeros((height, width), dtype=np.uint8)

    # Segment each pose independently. GrabCut is initialized from the known
    # near-white checkerboard range, while all textured/color pixels become
    # definite foreground. This preserves white fabric enclosed by real edges.
    for row in range(args.rows):
        for column in range(args.columns):
            x0 = column * cell_width
            y0 = row * cell_height
            cell_rgb = rgb[y0 : y0 + cell_height, x0 : x0 + cell_width]
            low = cell_rgb.min(axis=2)
            high = cell_rgb.max(axis=2)
            checkerboard = (low >= 235) & ((high - low) <= 14)
            textured = (~checkerboard).astype(np.uint8)

            count, component_labels, stats, _ = cv2.connectedComponentsWithStats(
                textured,
                connectivity=8,
            )
            keep = np.zeros_like(textured, dtype=bool)
            for component in range(1, count):
                if stats[component, cv2.CC_STAT_AREA] >= 80:
                    keep |= component_labels == component

            ys, xs = np.where(keep)
            if not len(xs):
                raise ValueError(f"no character detected in cell {row},{column}")

            left = max(0, int(xs.min()) - 16)
            right = min(cell_width, int(xs.max()) + 17)
            top = max(0, int(ys.min()) - 16)
            bottom = min(cell_height, int(ys.max()) + 17)

            grabcut_mask = np.full(
                (cell_height, cell_width),
                cv2.GC_BGD,
                dtype=np.uint8,
            )
            grabcut_mask[top:bottom, left:right] = cv2.GC_PR_FGD
            grabcut_mask[~checkerboard] = cv2.GC_FGD
            background_model = np.zeros((1, 65), dtype=np.float64)
            foreground_model = np.zeros((1, 65), dtype=np.float64)
            cv2.grabCut(
                cell_rgb,
                grabcut_mask,
                None,
                background_model,
                foreground_model,
                7,
                cv2.GC_INIT_WITH_MASK,
            )
            foreground = (grabcut_mask == cv2.GC_FGD) | (
                grabcut_mask == cv2.GC_PR_FGD
            )
            foreground = cv2.morphologyEx(
                foreground.astype(np.uint8),
                cv2.MORPH_CLOSE,
                np.ones((3, 3), dtype=np.uint8),
                iterations=1,
            ).astype(bool)
            alpha[y0 : y0 + cell_height, x0 : x0 + cell_width] = np.where(
                foreground,
                255,
                0,
            ).astype(np.uint8)

    # Turn the hard near-white edge into a small antialiased alpha ramp and
    # mathematically remove the light checkerboard contribution from RGB.
    component_count, component_labels, component_stats, _ = (
        cv2.connectedComponentsWithStats((alpha > 0).astype(np.uint8), 8)
    )
    if component_count <= 1:
        raise ValueError("no connected foreground after checker extraction")
    main_component = 1 + int(
        np.argmax(component_stats[1:, cv2.CC_STAT_AREA])
    )
    alpha[component_labels != main_component] = 0

    hard_foreground = alpha > 0
    distance = cv2.distanceTransform(
        hard_foreground.astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    ring = hard_foreground & (distance <= 3.0)
    rgb_float = rgb.astype(np.float32)
    background_level = 250.0
    color_distance = np.sqrt(((rgb_float - background_level) ** 2).sum(axis=2))
    color_alpha = np.clip(color_distance / 72.0 * 255.0, 0, 255)
    soft_alpha = alpha.astype(np.float32)
    ring_alpha = np.clip(
        color_alpha + np.clip(distance - 1.0, 0, 2.0) * 90.0,
        0,
        255,
    )
    soft_alpha[ring] = ring_alpha[ring]
    soft_alpha[soft_alpha < 8] = 0

    partial = (soft_alpha > 0) & (soft_alpha < 255)
    normalized_alpha = (soft_alpha[partial] / 255.0)[:, None]
    recovered = (
        rgb_float[partial] - (1.0 - normalized_alpha) * background_level
    ) / np.maximum(normalized_alpha, 1e-4)
    rgb_float[partial] = np.clip(recovered, 0, 255)

    # The generated checkerboard is a baked matte, so the last few opaque
    # pixels can still carry a white halo. Keep the extracted alpha silhouette
    # but borrow RGB from the nearest genuinely interior subject pixel.
    interior_distance = cv2.distanceTransform(
        hard_foreground.astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    clean_core = interior_distance >= 6.0
    silhouette_ring = hard_foreground & (interior_distance < 6.0)
    if clean_core.any():
        distance_source = (~clean_core).astype(np.uint8)
        _, nearest_labels = cv2.distanceTransformWithLabels(
            distance_source,
            cv2.DIST_L2,
            5,
            labelType=cv2.DIST_LABEL_PIXEL,
        )
        core_coords = np.argwhere(clean_core)
        nearest_coords = core_coords[nearest_labels - 1]
        nearest_rgb = rgb_float[
            nearest_coords[:, :, 0],
            nearest_coords[:, :, 1],
        ]
        ring_weight = np.clip((6.0 - interior_distance) / 4.5, 0.0, 1.0)
        defringed = (
            nearest_rgb * ring_weight[:, :, None]
            + rgb_float * (1.0 - ring_weight[:, :, None])
        )
        rgb_float[silhouette_ring] = defringed[silhouette_ring]

    rgba = np.dstack((rgb_float.astype(np.uint8), soft_alpha.astype(np.uint8)))
    rgba[rgba[:, :, 3] == 0, :3] = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(args.output)

    print(
        json.dumps(
            {
                "ok": True,
                "input": str(args.input),
                "output": str(args.output),
                "size": [width, height],
                "opaque_pixels": int((soft_alpha == 255).sum()),
                "partial_pixels": int(partial.sum()),
                "transparent_pixels": int((soft_alpha == 0).sum()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
