#!/usr/bin/env python3
"""Apply a small reproducible horizontal correction to an RGBA pose."""

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
    parser.add_argument("--scale-x", type=float, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 0.8 <= args.scale_x <= 1.25:
        raise ValueError("scale-x must remain a small correction (0.8..1.25)")

    source = Image.open(args.input).convert("RGBA")
    bbox = source.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("input pose is empty")

    rgba = np.asarray(source.crop(bbox), dtype=np.float32) / 255.0
    alpha = rgba[:, :, 3:4]
    premultiplied = np.concatenate((rgba[:, :, :3] * alpha, alpha), axis=2)
    target_width = max(1, round(premultiplied.shape[1] * args.scale_x))
    resized = cv2.resize(
        premultiplied,
        (target_width, premultiplied.shape[0]),
        interpolation=cv2.INTER_LANCZOS4,
    )
    resized = np.clip(resized, 0.0, 1.0)
    out_alpha = resized[:, :, 3:4]
    out_rgb = np.zeros_like(resized[:, :, :3])
    visible = out_alpha[:, :, 0] > (1.0 / 255.0)
    out_rgb[visible] = resized[:, :, :3][visible] / out_alpha[visible]
    out = np.concatenate((np.clip(out_rgb, 0.0, 1.0), out_alpha), axis=2)
    out_u8 = np.round(out * 255.0).astype(np.uint8)
    out_u8[out_u8[:, :, 3] == 0, :3] = 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(out_u8, "RGBA").save(args.output, optimize=True)
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(args.input),
                "output": str(args.output),
                "scale_x": args.scale_x,
                "source_visible": [rgba.shape[1], rgba.shape[0]],
                "output_visible": [target_width, rgba.shape[0]],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
