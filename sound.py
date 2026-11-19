"""Plays paper keys as MIDI notes (default output: the OS synth, e.g. Microsoft GS Wavetable Synth)."""
import math
import time

import mido

NOTE_S = 0.3  # shortcut: fixed note length until lift detection exists.


def key_note(key, base_note=60):
    """Paper keys are numbered 1..N left to right, so key 1 is base_note (60 = middle C)."""
    return base_note + key - 1


def tap_velocity(peak_g, low=0.5, high=3.0):
    """Harder taps play louder: low g (pass the finger's tap threshold) -> 40, high g or more -> 127.

    Scales by log(peak / low), so it tracks loudness ratios and a low calibrated
    threshold still spreads ordinary taps across the range.
    """
    high = max(high, 2 * low)  # A threshold near or over `high` must not divide by zero.
    t = math.log(max(peak_g, low) / low) / math.log(high / low)
    return int(40 + min(t, 1.0) * 87)


class NotePlayer:
    def __init__(self, program=0, port=None):
        self.port = port if port is not None else mido.open_output()  # System default output.
        self.port.send(mido.Message("program_change", program=program))
        self.off_at = []  # (monotonic time, note) still sounding

    def play(self, note, velocity):
        if not 0 <= note <= 127:
            return  # Keys beyond the MIDI range stay silent.
        if any(n == note for _, n in self.off_at):
            # Re-tap of a sounding note: end it now so its old off can't cut the new one short.
            self.off_at = [(t, n) for t, n in self.off_at if n != note]
            self.port.send(mido.Message("note_off", note=note))
        self.port.send(mido.Message("note_on", note=note, velocity=velocity))
        self.off_at.append((time.monotonic() + NOTE_S, note))

    def update(self, now=None):
        now = time.monotonic() if now is None else now
        due = [n for t, n in self.off_at if t <= now]
        self.off_at = [(t, n) for t, n in self.off_at if t > now]
        for note in due:
            self.port.send(mido.Message("note_off", note=note))

    def close(self):
        for _, note in self.off_at:
            self.port.send(mido.Message("note_off", note=note))
        self.off_at = []
        self.port.close()
