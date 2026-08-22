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
    parser.add_argument("--decontaminate-depth", type=float, default=18.0)
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

    # Chroma similarity alone can misclassify naturally olive/brown details in
    # hair, fabric, or skin. Only pixels connected to the outside background
    # are allowed to remain transparent; enclosed look-alike colors are solid.
    background_candidate = (green_excess > args.opaque_excess).astype(np.uint8)
    candidate_count, candidate_labels = cv2.connectedComponents(
        background_candidate,
        connectivity=8,
    )
    border_labels = np.unique(
        np.concatenate(
            (
                candidate_labels[0],
                candidate_labels[-1],
                candidate_labels[:, 0],
                candidate_labels[:, -1],
            )
        )
    )
    border_labels = border_labels[border_labels != 0]
    if candidate_count <= 1 or border_labels.size == 0:
        raise ValueError("no exterior chroma component detected")
    exterior_background = np.isin(candidate_labels, border_labels)
    key_distance = np.linalg.norm(rgb - key[None, None, :], axis=2)
    definite_chroma = (green_excess > 50.0) & (key_distance < 115.0)
    alpha[(~exterior_background) & (~definite_chroma)] = 1.0

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

    # Pull the outer silhouette ring toward the nearest genuinely interior
    # subject color. This removes olive/magenta chroma contamination that can
    # remain even when a generated edge pixel is nearly opaque.
    foreground = (alpha > 0.0).astype(np.uint8)
    inner_distance = cv2.distanceTransform(
        foreground,
        cv2.DIST_L2,
        3,
    )
    decontaminate_depth = max(float(args.decontaminate_depth), 1.0)
    deep_core = inner_distance >= decontaminate_depth
    edge_ring = (foreground > 0) & (inner_distance < decontaminate_depth)
    decontaminate_mask = edge_ring & partial
    if deep_core.any():
        distance_source = (~deep_core).astype(np.uint8)
        _, nearest_labels = cv2.distanceTransformWithLabels(
            distance_source,
            cv2.DIST_L2,
            5,
            labelType=cv2.DIST_LABEL_PIXEL,
        )
        core_coords = np.argwhere(deep_core)
        nearest_coords = core_coords[nearest_labels - 1]
        nearest_rgb = rgb[
            nearest_coords[:, :, 0],
            nearest_coords[:, :, 1],
        ]
        silhouette_weight = np.clip(
            (decontaminate_depth - inner_distance)
            / max(decontaminate_depth * 0.65, 1.0),
            0.0,
            1.0,
        )
        # A translucent pixel carries proportionally more background spill.
        # Preserve its alpha for a smooth silhouette, but take its RGB almost
        # entirely from the nearest clean interior pixel.
        matte_weight = np.clip((0.90 - alpha) / 0.75, 0.0, 1.0)
        nearest_weight = np.maximum(silhouette_weight, matte_weight)
        deep_blend = (
            nearest_rgb * nearest_weight[:, :, None]
            + rgb * (1.0 - nearest_weight[:, :, None])
        )
        rgb[decontaminate_mask] = deep_blend[decontaminate_mask]

    # Remove any residual green only in the narrow silhouette ring. Interior
    # colors (including the pastel socks) remain untouched.
    neutral_ceiling = np.maximum(rgb[:, :, 0], rgb[:, :, 2]) + 2.0
    rgb[:, :, 1][decontaminate_mask] = np.minimum(
        rgb[:, :, 1][decontaminate_mask],
        neutral_ceiling[decontaminate_mask],
    )

    # Generated chroma renders can contain a nearly opaque one-pixel color
    # outline. Replace only that outermost silhouette from a nearby interior
    # core; the narrow depth avoids the horizontal smearing caused by broad
    # edge replacement while removing the gold/green rim after downscaling.
    outline_core = inner_distance >= 8.0
    outline_ring = (foreground > 0) & (inner_distance < 6.0)
    if outline_core.any():
        outline_source = (~outline_core).astype(np.uint8)
        _, outline_labels = cv2.distanceTransformWithLabels(
            outline_source,
            cv2.DIST_L2,
            5,
            labelType=cv2.DIST_LABEL_PIXEL,
        )
        outline_coords = np.argwhere(outline_core)
        outline_nearest_coords = outline_coords[outline_labels - 1]
        outline_rgb = rgb[
            outline_nearest_coords[:, :, 0],
            outline_nearest_coords[:, :, 1],
        ]
        outline_weight = np.clip(
            (6.0 - inner_distance) / 5.0,
            0.0,
            0.92,
        )
        outline_blend = (
            outline_rgb * outline_weight[:, :, None]
            + rgb * (1.0 - outline_weight[:, :, None])
        )
        rgb[outline_ring] = outline_blend[outline_ring]

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
