#!/usr/bin/env python3
"""Speaker response in the room through the built-in mic array. PLAYS OUT LOUD (~9 s).

  ./mic-sweep.py          # through MateBook Speakers (the DSP), pink noise -20 dBFS RMS
  ./mic-sweep.py --raw    # straight into the Speaker sink, without the DSP

Pause the music first. Mono pink noise goes out at full volume (the sink is set
to 1.0 for the take) and the four DMICs are recorded, with the SOF capture DRC
and beamformer switched off (all restored after). Per 1/3 octave: H = Sxy/Sxx (delay-aligned, power-averaged over the mics;
distortion and enhancer harmonics do not enter it), relative to 630 Hz-2.5 kHz,
next to Notebookcheck's Windows measurement of this laptop (max volume, pink).

Trust 125 Hz-4 kHz: the DMIC path is flat from 100 Hz up (its SOF IIR is a
40 Hz high-pass, +20 dB), the four mics agree within 1.5 dB below 630 Hz.
Above ~5 kHz the mics in the lid hear the tweeters off-axis and read far low.
"""
import json
import signal
import struct
import subprocess
import sys
import tempfile
import time

import numpy as np

FS = 48000
MIC = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source"
SPEAKER = "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink"
CTLS = ["Dmic0 Capture DRC switch", "Dmic0 Capture TDFB beam switch"]
BANDS = [1000 * 2 ** (k / 3) for k in range(-9, 13)]              # 125 Hz .. 16 kHz
# Notebookcheck 2024 review, dB SPL per 1/3 octave, 125 Hz .. 16 kHz
WINDOWS = [66.1, 64.7, 69.5, 70.7, 74.7, 77.1, 76.7, 73.3, 73.0, 72.0, 70.9,
           70.9, 75.5, 72.9, 71.8, 73.2, 74.9, 72.8, 69.4, 66.3, 68.7, 66.1]
REF = slice(7, 14)                                                 # 630 Hz .. 2.5 kHz


def ctl(name, value=None):
    if value is None:
        out = subprocess.run(["amixer", "-c", "sofhdadsp", "cget", f"name={name}"],
                             capture_output=True, text=True, check=True).stdout
        return out.rsplit("values=", 1)[1].split()[0]
    subprocess.run(["amixer", "-q", "-c", "sofhdadsp", "cset", f"name={name}", value], check=True)


def node_id(name):
    """wpctl 0.5 takes numeric ids only."""
    for o in json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, check=True).stdout):
        if o.get("type") == "PipeWire:Interface:Node" and (o.get("info") or {}).get("props", {}).get("node.name") == name:
            return str(o["id"])
    sys.exit(f"no PipeWire node {name}")


def volume(node, value=None):
    """Volume as wpctl and the GNOME slider show it (cubic)."""
    if value is None:
        return subprocess.run(["wpctl", "get-volume", node], capture_output=True, text=True, check=True).stdout.split()[1]
    subprocess.run(["wpctl", "set-volume", node, value], check=True)


def pink(n, rms_db):
    f = np.fft.rfftfreq(n, 1 / FS)
    X = np.fft.rfft(np.random.default_rng(7).standard_normal(n))
    X[1:] /= np.sqrt(f[1:])
    X[(f < 45) | (f > 20000)] = 0
    x = np.fft.irfft(X, n)
    x *= 10 ** (rms_db / 20) / np.sqrt(np.mean(x ** 2))
    fade = np.hanning(FS // 5)
    x[:FS // 10] *= fade[:FS // 10]
    x[-FS // 10:] *= fade[FS // 10:]
    return x


def wav(path, x=None, ch=2):
    if x is not None:
        data = x.astype("<f4").tobytes()
        open(path, "wb").write(struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(data), b"WAVE", b"fmt ",
                                           16, 3, ch, FS, FS * 4 * ch, 4 * ch, 32, b"data", len(data)) + data)
        return None
    b = open(path, "rb").read()
    i = 12
    while b[i:i + 4] != b"data":
        i += 8 + int.from_bytes(b[i + 4:i + 8], "little")
    d = b[i + 8:]                      # to EOF: the size field may be stale
    return np.frombuffer(d[:len(d) // (4 * ch) * 4 * ch], "<f4").reshape(-1, ch).astype(float)


def take(sink, x):
    with tempfile.TemporaryDirectory() as d:
        wav(f"{d}/x.wav", np.stack([x, x], 1))
        saved = {c: ctl(c) for c in CTLS}
        node = node_id(sink)
        vol = volume(node)
        rec = subprocess.Popen(["pw-record", "--target", MIC, "--format", "f32", "--rate", str(FS),
                                "--channels", "4", f"{d}/y.wav"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.8)            # PCM open first: UCM may (re)apply its controls on start
            for c in CTLS:
                ctl(c, "off")
            # The DSP sink's slider acts before the chain: at 0.5 the compressors would
            # see -18 dB and the room 18 dB less signal. Windows was measured at max volume.
            volume(node, "1.0")
            time.sleep(0.4)
            subprocess.run(["pw-play", "--target", sink, f"{d}/x.wav"], check=True)
            time.sleep(0.6)
        finally:
            rec.send_signal(signal.SIGINT)
            rec.wait(5)
            volume(node, vol)
            for c, v in saved.items():
                ctl(c, v)
        return wav(f"{d}/y.wav", ch=4)


def response(x, y, n=8192):
    """Per band: H in dB and the coherence (low = noise or distortion dominate)."""
    N = 1 << int(np.ceil(np.log2(len(y) + len(x))))
    r = np.fft.irfft(np.fft.rfft(y.mean(1), N) * np.conj(np.fft.rfft(x, N)), N)
    lag = int(np.argmax(np.abs(r[:3 * FS])))       # the recording starts ~1.3 s early
    y = y[lag:lag + len(x)]
    x = x[:len(y)]
    w = np.hanning(n)
    sxx = syy = sxy = 0
    for i in range(0, len(x) - n, n // 2):
        X = np.fft.rfft(w * x[i:i + n])
        Y = np.fft.rfft(w[:, None] * y[i:i + n], axis=0)
        sxx = sxx + np.abs(X) ** 2
        syy = syy + np.abs(Y) ** 2
        sxy = sxy + np.conj(X)[:, None] * Y
    f = np.fft.rfftfreq(n, 1 / FS)
    h2 = (np.abs(sxy) ** 2 / sxx[:, None] ** 2).mean(1)
    coh = (np.abs(sxy) ** 2 / (sxx[:, None] * syy)).mean(1)
    k = [(f >= fc * 2 ** (-1 / 6)) & (f < fc * 2 ** (1 / 6)) for fc in BANDS]
    return np.array([10 * np.log10(h2[m].mean()) for m in k]), np.array([coh[m].mean() for m in k])


def main():
    sink = SPEAKER if "--raw" in sys.argv[1:] else "matebook_speakers"
    x = pink(8 * FS, -20)
    h, coh = response(x, take(sink, x))
    h -= h[REF].mean()
    win = np.array(WINDOWS) - np.mean(WINDOWS[REF])
    print(f"{sink}: dB re 630 Hz-2.5 kHz      room  Windows  room-Win  coherence")
    for fc, a, b, c in zip(BANDS, h, win, coh):
        print(f"{fc:8.0f} Hz {a:27.1f} {b:8.1f} {a - b:9.1f} {c:10.2f}")
    fit = slice(0, 16)                                             # 125 Hz .. 4 kHz
    print(f"body 200-630 Hz vs Windows {np.mean((h - win)[2:8]):+.1f} dB, "
          f"rms 125 Hz-4 kHz {np.sqrt(np.mean((h - win)[fit] ** 2)):.1f} dB")


if __name__ == "__main__":
    main()
