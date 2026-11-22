#!/usr/bin/env python3
"""Score a guided session: python session_analyze.py PREFIX  (writes PREFIX_report.txt)."""
import csv
import sys
from pathlib import Path

import numpy as np

from tapstrap import FINGERS

WINDOW = (-0.25, 0.5)  # Event-to-cue window (s); the user aims at the beep, so taps can land early.
LAGS_MS = range(0, 201, 10)


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def frac(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else f"{n}/{d} (-)"


def analyze(prefix):
    cues, idles, start = [], [], None
    for r in read_csv(f"{prefix}_cues.csv"):
        t = float(r["host_time_s"])
        if r["kind"] == "idle_start":
            start = t
        elif r["kind"] == "idle_end":
            idles.append((start, t))
        else:
            fingers = tuple(r["fingers"].split("+")) if r["fingers"] else ()
            keys = tuple(int(k) for k in r["keys"].split("+")) if r["keys"] else ()
            cues.append({"t": t, "kind": r["kind"], "fingers": fingers, "keys": keys, "events": []})
    events = [(float(r["host_time_s"]), r["finger"], int(r["key"]))
              for r in read_csv(f"{prefix}_events.csv")]

    false_taps = unmatched = 0
    for e in events:
        near = [c for c in cues if c["t"] + WINDOW[0] <= e[0] <= c["t"] + WINDOW[1]]
        if near:
            min(near, key=lambda c: abs(e[0] - c["t"]))["events"].append(e)
        elif any(a <= e[0] <= b for a, b in idles):
            false_taps += 1
        else:
            unmatched += 1

    taps = [c for c in cues if c["kind"] == "tap"]
    chords = [c for c in cues if c["kind"] == "chord"]
    det = {f: [0, 0] for f in FINGERS}    # finger -> [detected, cued]
    right = {f: [0, 0] for f in FINGERS}  # finger -> [right key, detected]
    extra_cues = extra_total = 0
    detected = []  # (first target event time, finger, target key) for the lag sweep
    for c in taps:
        f, k = c["fingers"][0], c["keys"][0]
        own = [e for e in c["events"] if e[1] == f]
        extra = len(c["events"]) - len(own)
        extra_cues += extra > 0
        extra_total += extra
        det[f][1] += 1
        if own:
            det[f][0] += 1
            right[f][1] += 1
            right[f][0] += own[0][2] == k
            detected.append((own[0][0], f, k))

    lines = [f"tap detected: {frac(sum(v[0] for v in det.values()), len(taps))}"]
    lines += [f"  tap detected {f}: {frac(*det[f])}" for f in FINGERS]
    n_right, n_det = sum(v[0] for v in right.values()), sum(v[1] for v in right.values())
    lines.append(f"right key: {frac(n_right, n_det)}")
    lines += [f"  right key {f}: {frac(*right[f])}" for f in FINGERS]
    mean_extra = extra_total / len(taps) if taps else 0.0
    lines.append(f"tap cues with extra fingers: {frac(extra_cues, len(taps))}, mean extra {mean_extra:.2f}")

    complete = exact = 0
    chord_hits = {f: [0, 0] for f in FINGERS}
    for c in chords:
        hit = {e[1] for e in c["events"]}
        for f in c["fingers"]:
            chord_hits[f][1] += 1
            chord_hits[f][0] += f in hit
        ok = set(c["fingers"]) <= hit
        complete += ok
        exact += ok and hit <= set(c["fingers"])
    lines.append(f"chord complete: {frac(complete, len(chords))}")
    lines.append(f"chord exact: {frac(exact, len(chords))}")
    lines += [f"  chord finger hit {f}: {frac(*chord_hits[f])}" for f in FINGERS if chord_hits[f][1]]

    idle_s = sum(b - a for a, b in idles)
    rate = f"{60 * false_taps / idle_s:.1f}/min" if idle_s else "-/min"
    lines.append(f"false taps while idle: {false_taps} in {idle_s:.0f} s ({rate})")
    lines.append(f"unmatched events: {unmatched}")
    lines += lag_sweep(prefix, detected, n_right, n_det)
    return lines


def lag_sweep(prefix, detected, n_right, n_det):
    """Key accuracy if the key were read from the hand frame L ms before each detected tap."""
    path = Path(f"{prefix}_hand.csv")
    rows = read_csv(path) if path.exists() else []
    if not rows or not detected:
        return ["lag sweep: skipped (no hand data or no detected taps)"]
    times = np.array([float(r["host_time_s"]) for r in rows])
    acc = {}
    for lag in LAGS_MS:
        hits = 0
        for te, f, k in detected:
            i = np.searchsorted(times, te - lag / 1000, side="right") - 1
            hits += i >= 0 and int(rows[i][f"{f}_key"]) == k
        acc[lag] = hits
    best = max(acc, key=acc.get)  # Ties go to the smallest lag.
    lines = [f"lag {lag} ms key acc: {frac(acc[lag], len(detected))}" for lag in LAGS_MS]
    lines.append(f"lag best: {best} ms, {frac(acc[best], len(detected))}")
    lines.append(f"app right key (for comparison): {frac(n_right, n_det)}")
    return lines


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    prefix = sys.argv[1]
    lines = analyze(prefix)
    print("\n".join(lines))
    Path(f"{prefix}_report.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
