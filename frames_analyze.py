"""Check MediaPipe fingertips on recorded frames (V key) against the calibration.

    python frames_analyze.py recordings/frames_<time>

Prints the key under each fingertip per frame (raw tip -> corrected tip, as the
app uses) and writes <folder>_overlay/ images: keys green, raw tips red,
corrected tips cyan. Uses the saved calibration/, so record with the same
camera position and frame size you calibrated with.
"""
import sys
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import vision

from calibration import FINGERTIPS, fingertip, load_calibration, region_at
from phone_server import make_landmarker

BASE_DIR = Path(__file__).resolve().parent


def main(folder):
    folder = Path(folder)
    out_dir = folder.with_name(folder.name + "_overlay")
    out_dir.mkdir(exist_ok=True)
    detector = make_landmarker(vision.RunningMode.IMAGE)
    on_key = tips = 0
    for path in sorted(folder.glob("*.jpg")):
        img = cv2.imread(str(path))
        cal = load_calibration(BASE_DIR / "calibration", img.shape)
        if cal is None:
            sys.exit(f"No calibration for {img.shape[1]}x{img.shape[0]} frames: calibrate (C) first.")
        result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
        h, w = img.shape[:2]
        overlay = img.copy()
        keys = cal["key_map"] > 0
        overlay[keys] = (0.5 * overlay[keys] + [0, 90, 0]).astype("uint8")
        parts = []
        for i, hand in enumerate(result.hand_landmarks):
            label = result.handedness[i][0].category_name
            row = []
            for name, k in FINGERTIPS.items():
                x, y = fingertip(hand, k)
                raw, fixed = region_at(cal, hand[k].x, hand[k].y), region_at(cal, x, y)
                initial = name[0].upper()
                row.append(f"{initial}:{raw}->{fixed}" if raw != fixed else f"{initial}:{raw}")
                tips += 1
                on_key += bool(fixed)
                cv2.circle(overlay, (int(hand[k].x * w), int(hand[k].y * h)), 4, (0, 0, 255), -1)
                cv2.circle(overlay, (int(x * w), int(y * h)), 5, (255, 255, 0), 2)
            parts.append(f"{label}: " + " ".join(row))
        print(path.stem, " | ".join(parts) or "no hands")
        cv2.imwrite(str(out_dir / path.name), overlay)
    print(f"Fingertips on a key: {on_key}/{tips}. Overlays in {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
