#!/usr/bin/env python3
"""Measure the speaker DSP through PipeWire, silently.

Loads the filter-chain from configs/60-matebook-speakers-dsp.conf into a
private pipewire client (virtual sink -> chain -> virtual source; the speakers
are never touched), plays synthetic test signals through it and checks what
you hear on the laptop:

  width    side/mid above 1 kHz raised, bass below 150 Hz kept mono
  squash   the dynamics flatten a loud master by at most a few dB
  kick     the kick still stands out over the bass line when loud
  pumping  a steady 2.5 kHz tone does not dip when the kick and bass hit
  clean    the bass enhancer does not smear distortion up to 2.5 kHz
  safety   peak <= 0 dBFS, little energy below 90 Hz (speakers cannot play it)
  level    a loud master stays about as loud as with the previous tuning

  ./dsp-check.py [conf]        # ~30 s; exit 1 if a check fails
"""
import os
import signal
import struct
import subprocess
import sys
import tempfile
import time

import numpy as np

FS = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = """context.properties = { log.level = 0 }
context.spa-libs = { audio.convert.* = audioconvert/libspa-audioconvert  support.* = support/libspa-support }
context.modules = [
  { name = libpipewire-module-protocol-native }
  { name = libpipewire-module-client-node }
  { name = libpipewire-module-adapter }
"""


def test_conf(path):
    """The repo filter-chain, renamed and cut loose from the speakers."""
    src = open(path).read()
    body = src[src.index("[", src.index("context.modules")) + 1:src.rindex("]")]
    body = "\n".join(l for l in body.splitlines()
                     if "filter.smart" not in l and "node.passive" not in l)
    body = body.replace('"MateBook Speakers"', '"dsp-check"')
    body = body.replace('"matebook_speakers.out"',
                        '"dsptest.out"  media.class = Audio/Source  priority.session = 0')
    body = body.replace('"matebook_speakers"', '"dsptest.in"  priority.session = 0')
    return HEADER + body + "]\n"


def write_wav(path, x):
    data = x.astype("<f4").tobytes()
    hdr = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16,
                      3, 2, FS, FS * 8, 8, 32, b"data", len(data))
    open(path, "wb").write(hdr + data)


def read_wav(path):
    b = open(path, "rb").read()
    i = 12
    while b[i:i + 4] != b"data":
        i += 8 + int.from_bytes(b[i + 4:i + 8], "little")
    d = b[i + 8:]                      # to EOF: the size field may be stale
    return np.frombuffer(d[:len(d) // 8 * 8], "<f4").reshape(-1, 2).astype(float)


def render(conf_text, signals):
    with tempfile.TemporaryDirectory() as d:
        conf = os.path.join(d, "dsp-check.conf")
        open(conf, "w").write(conf_text)
        pw = subprocess.Popen(["pipewire", "-c", conf], stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                if '"dsptest.out"' in subprocess.run(["pw-cli", "ls", "Node"],
                                                     capture_output=True, text=True).stdout:
                    break
                time.sleep(0.2)
            else:
                sys.exit("dsp-check: filter-chain did not start (pipewire -c dsp-check.conf)")
            outs = []
            for i, x in enumerate(signals):
                src, dst = f"{d}/in{i}.wav", f"{d}/out{i}.wav"
                write_wav(src, x)
                rec = subprocess.Popen(["pw-record", "--target", "dsptest.out", "--format", "f32",
                                        "--rate", str(FS), "--channels", "2", dst],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
                subprocess.run(["pw-play", "--target", "dsptest.in", src], check=True)
                time.sleep(0.5)
                rec.send_signal(signal.SIGINT)
                rec.wait(5)
                outs.append(read_wav(dst))
            return outs
        finally:
            pw.terminate()
            pw.wait(5)


def band(x, lo, hi):
    X = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(len(x), 1 / FS)
    X[(f < lo) | (f >= hi)] = 0
    return np.fft.irfft(X, len(x), axis=0)


def db(power):
    return 10 * np.log10(power + 1e-30)


def music(seconds=10):
    """Kick + bass line + a steady 2.5 kHz tone, -1 dBFS peak like a loud master."""
    t = np.arange(int(seconds * FS)) / FS
    tb = t % 0.5
    kick = np.sin(2 * np.pi * (45 * tb + 75 * 0.03 * (1 - np.exp(-tb / 0.03)))) * np.exp(-tb / 0.15)
    notes = np.array([55, 43.65, 65.41, 49.0])[(t // 1).astype(int) % 4]
    ph = 2 * np.pi * np.cumsum(notes) / FS
    bass = np.sin(ph) + 0.5 * np.sin(2 * ph) + 0.25 * np.sin(3 * ph)
    x = 0.6 * kick + 0.3 * bass + 0.05 * np.sin(2 * np.pi * 2500 * t)
    x *= 0.891 / np.abs(x).max()
    return np.stack([x, x], 1)


def stereo_noise(seconds=6):
    """Pink noise, L/R correlation 0.5, -20 dBFS RMS."""
    rng = np.random.default_rng(1)
    n = int(seconds * FS)
    f = np.fft.rfftfreq(n, 1 / FS)
    f[0] = f[1]

    def pink():
        x = np.fft.irfft(np.fft.rfft(rng.standard_normal(n)) / np.sqrt(f), n)
        return x / np.sqrt(np.mean(x ** 2))
    c, a, b = pink(), pink(), pink()
    return np.stack([c + a, c + b], 1) * np.sqrt(0.5) * 0.1


def steady(y):
    a = np.abs(y).max(1)
    on = np.flatnonzero(a > a.max() * 1e-3)
    return y[on[0] + FS:on[-1] - FS // 4]


def crest(x):
    return 20 * np.log10(np.abs(x).max() / np.sqrt(np.mean(x ** 2)))


def kick_over_bass(x):
    """Kick peak over the sustained bass line, 90-300 Hz, dB (kick every 0.5 s)."""
    k, beat = FS // 100, FS // 2
    env = np.sqrt(np.convolve(band(x, 90, 300) ** 2, np.ones(k) / k, "same"))
    return np.median([20 * np.log10(env[i:i + beat // 5].max() / env[i + int(0.3 * FS):i + int(0.45 * FS)].mean())
                      for i in range(0, len(env) - beat, beat)])


def tone_swing(x, f0=2500, win=0.02):
    """p5..p95 spread of the level of a steady tone, dB."""
    z = x * np.exp(-2j * np.pi * f0 * np.arange(len(x)) / FS)
    k = int(win * FS)
    env = 20 * np.log10(np.abs(np.convolve(z, np.ones(k) / k, "valid")) + 1e-12)
    return np.ptp(np.percentile(env, [5, 95]))


def side_mid(y, lo, hi):
    m, s = band((y[:, 0] + y[:, 1]) / 2, lo, hi), band((y[:, 0] - y[:, 1]) / 2, lo, hi)
    return db(np.mean(s ** 2)) - db(np.mean(m ** 2))


def main():
    conf = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "configs/60-matebook-speakers-dsp.conf")
    loud_in = music()
    wide_in = stereo_noise()
    loud, quiet, wide = (steady(y) for y in render(test_conf(conf),
                                                   [loud_in, loud_in * 10 ** (-30 / 20), wide_in]))
    L, Q = loud[:, 0], quiet[:, 0]
    checks = [
        ("width: side/mid 1-8 kHz vs input, dB", side_mid(wide, 1000, 8000) - side_mid(wide_in, 1000, 8000), ">=", 3),
        ("width: side/mid 40-150 Hz vs input, dB", side_mid(wide, 40, 150) - side_mid(wide_in, 40, 150), "<=", -6),
        ("squash: crest quiet - loud, dB", crest(Q) - crest(L), "<=", 3),
        ("kick: over the bass, quiet - loud, dB", kick_over_bass(Q) - kick_over_bass(L), "<=", 1.5),
        ("pumping: 2.5 kHz tone swing loud - quiet, dB", tone_swing(L) - tone_swing(Q), "<=", 1.5),
        ("clean: 2.5 kHz tone swing quiet, dB", tone_swing(Q), "<=", 1.5),
        ("safety: peak, dBFS", 20 * np.log10(np.abs(loud).max()), "<=", 0),
        ("safety: energy below 90 Hz, %", 100 * np.mean(band(L, 0, 90) ** 2) / np.mean(L ** 2), "<=", 20),
        # previous tuning (d983bba): -26.6; the volume slider has more than 1.5 dB left
        ("level: 200 Hz-8 kHz RMS, dBFS", db(np.mean(band(L, 200, 8000) ** 2)), ">=", -28),
    ]
    bad = 0
    for name, v, op, lim in checks:
        ok = v >= lim if op == ">=" else v <= lim
        bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name:46} {v:7.2f}  (want {op} {lim})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
