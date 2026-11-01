#!/usr/bin/env python3
"""Check the speaker DSP through PipeWire, silently.

Takes the graph from configs/60-matebook-speakers-dsp.conf (the WirePlumber
rule that puts it inside the Speaker output) and runs it the way Speaker does,
in a stream's audioconvert with Speaker's 4 channels: a private loopback
(virtual 4-channel sink -> virtual source) feeds pw-record, which carries the
graph. The speakers are never touched. Plays test signals and checks:

  crossover  the tweeters (RL RR) get no bass
  safety     a loud master does not clip any output
  guard      sustained full-scale tones stay at each speaker group's power
             bound: what a full-scale sine gets in the amps' INBOX mode
             (amps.py runs them in ALGO, +8.8 dB woofers, +8.2 dB tweeters)
  music      a dense master stays under the guard (the Histen dynamics hold it)
  volume     the Speaker slider acts after the dynamics, cubic like GNOME

  ./dsp-check.py [conf]        # about 1 min; exit 1 if a check fails
"""
import json
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
BOUND = {"woofers": -3 - 8.8, "tweeters": -3 - 8.2}     # dBFS RMS on the chain outputs, the guards' thresholds
# state.restore-props: WirePlumber would otherwise restore a volume once set on these nodes
LOOP = """context.properties = { log.level = 0 }
context.spa-libs = { audio.convert.* = audioconvert/libspa-audioconvert  support.* = support/libspa-support }
context.modules = [
  { name = libpipewire-module-protocol-native }
  { name = libpipewire-module-client-node }
  { name = libpipewire-module-adapter }
  { name = libpipewire-module-loopback
    args = {
      node.description = "dsp-check"
      audio.position = [ FL FR RL RR ]
      capture.props = { node.name = "dsptest.in" media.class = Audio/Sink priority.session = 0 state.restore-props = false }
      playback.props = { node.name = "dsptest.out" media.class = Audio/Source priority.session = 0 state.restore-props = false }
    }
  }
]
"""


def test_conf(path):
    """The graph the repo's rule gives Speaker (audioconvert.filter-graph.0), as WirePlumber hands it over."""
    src = open(path).read()
    i = j = src.index("{", src.index("audioconvert.filter-graph.0 ="))
    depth = 0
    while True:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
        if depth == 0:
            return src[i:j]


def write_wav(path, x):
    data = x.astype("<f4").tobytes()
    hdr = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16,
                      3, 2, FS, FS * 8, 8, 32, b"data", len(data))
    open(path, "wb").write(hdr + data)


def read_wav(path, ch=4):
    b = open(path, "rb").read()
    i = 12
    while b[i:i + 4] != b"data":
        i += 8 + int.from_bytes(b[i + 4:i + 8], "little")
    d = b[i + 8:]                      # to EOF: the size field may be stale
    return np.frombuffer(d[:len(d) // (4 * ch) * 4 * ch], "<f4").reshape(-1, ch).astype(float)


def render(graph, takes):
    """takes: (stereo signal, Speaker volume as wpctl/GNOME show it); returns FL FR RL RR per take."""
    with tempfile.TemporaryDirectory() as d:
        conf = os.path.join(d, "dsp-check.conf")
        open(conf, "w").write(LOOP)
        pw = subprocess.Popen(["pipewire", "-c", conf], stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                nodes = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True).stdout or "[]")
                ids = {(o.get("info") or {}).get("props", {}).get("node.name"): o["id"] for o in nodes
                       if o.get("type") == "PipeWire:Interface:Node"}
                if "dsptest.in" in ids and "dsptest.out" in ids:
                    break
                time.sleep(0.2)
            else:
                sys.exit("dsp-check: loopback did not start (pipewire -c dsp-check.conf)")
            outs = []
            for i, (x, vol) in enumerate(takes):
                src, dst = f"{d}/in{i}.wav", f"{d}/out{i}.wav"
                write_wav(src, x)
                # --volume is linear: the cube of the slider, as GNOME sets Speaker's channelVolumes
                rec = subprocess.Popen(["pw-record", "--target", "dsptest.out", "--format", "f32",
                                        "--rate", str(FS), "--channels", "4", "--channel-map", "FL,FR,RL,RR",
                                        "--volume", str(vol ** 3), "-P",
                                        "{ state.restore-props = false audioconvert.filter-graph.0 = " + graph + " }",
                                        dst], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
                subprocess.run(["pw-play", "--target", "dsptest.in", src], check=True)
                time.sleep(0.5)
                rec.send_signal(signal.SIGINT)
                rec.wait(5)
                if not os.path.exists(dst):
                    sys.exit("dsp-check: pw-record wrote nothing, the graph did not load (journalctl --user -u pipewire)")
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


def pink(n, seed):
    f = np.fft.rfftfreq(n, 1 / FS)
    f[0] = f[1]
    x = np.fft.irfft(np.fft.rfft(np.random.default_rng(seed).standard_normal(n)) / np.sqrt(f), n)
    return x / np.sqrt(np.mean(x ** 2))


def stereo_noise(seconds=6):
    """Pink noise, L/R correlation 0.5, -20 dBFS RMS."""
    n = int(seconds * FS)
    c, a, b = pink(n, 1), pink(n, 2), pink(n, 3)
    return np.stack([c + a, c + b], 1) * np.sqrt(0.5) * 0.1


def master(seconds=12):
    """A dense modern master: pink noise on an 8th-note drum envelope, peaks -0.3 dBFS, RMS about -8 dBFS."""
    n = int(seconds * FS)
    t = np.arange(n) / FS
    env = 0.55 + 0.45 * np.exp(-(t % 0.25) / 0.06)
    c, a, b = pink(n, 3), pink(n, 4), pink(n, 5)
    x = np.stack([c + 0.6 * a, c + 0.6 * b], 1) * env[:, None]
    return np.tanh(2.2 * x / np.abs(x).max()) * 0.966


def sine(f, seconds=8):
    return np.stack([np.sin(2 * np.pi * f * np.arange(int(seconds * FS)) / FS) * 0.999] * 2, 1)


def loudest(y, ch):
    """Highest 250 ms RMS of the louder channel, dBFS, after the first 2 s (signal on, the guard settled)."""
    on = np.flatnonzero(np.abs(y).max(1) > 1e-3)
    y = y[on[0] + 2 * FS:on[-1], ch]
    k = len(y) // (FS // 4)
    return db((y[:k * (FS // 4)] ** 2).reshape(k, FS // 4, -1).mean(1).max(1)).max()


def main():
    conf = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "configs/60-matebook-speakers-dsp.conf")
    W, T = slice(0, 2), slice(2, 4)
    noise, loud, bass, treble, dense, v1, v04 = render(test_conf(conf), [
        (stereo_noise(), 1.0), (music(), 1.0), (sine(150), 1.0), (sine(10000), 1.0), (master(), 1.0),
        (stereo_noise(3), 1.0), (stereo_noise(3), 0.4)])
    tw = noise[:, T]
    checks = [
        ("crossover: tweeters below 1 kHz re all, dB", db(np.sum(band(tw, 20, 1000) ** 2)) - db(np.sum(tw ** 2)), "<=", -30),
        ("safety: loud master, peak of any output, dBFS", 20 * np.log10(np.abs(loud).max()), "<=", 0),
        ("guard: woofers, 150 Hz full-scale sine, dBFS RMS", loudest(bass, W), "<=", BOUND["woofers"] + 0.5),
        ("guard: tweeters, 10 kHz full-scale sine, dBFS RMS", loudest(treble, T), "<=", BOUND["tweeters"] + 0.5),
        ("music: dense master, woofers, dBFS RMS", loudest(dense, W), "<=", BOUND["woofers"] - 1),
        ("volume: slider 0.4 vs 1.0 off the cube, dB",
         abs(db(np.mean(v04[:, 0] ** 2)) - db(np.mean(v1[:, 0] ** 2)) - 60 * np.log10(0.4)), "<=", 0.5),
    ]
    bad = 0
    for name, v, op, lim in checks:
        ok = v >= lim if op == ">=" else v <= lim
        bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name:50} {v:7.2f}  (want {op} {lim:.1f})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
