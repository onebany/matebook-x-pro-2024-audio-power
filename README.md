# Huawei MateBook X Pro 2024 — power & audio on Ubuntu

Install (one command), then reboot:

```bash
sudo apt install -y git && git clone https://github.com/onebany/matebook-x-pro-2024-audio-power && sudo ./matebook-x-pro-2024-audio-power/install.sh
```

Check after the reboot: `./matebook-x-pro-2024-audio-power/verify.sh --live`

All three MateBook X Pro 2024 repos ([camera](https://github.com/onebany/matebook-x-pro-2024-camera),
[fingerprint](https://github.com/onebany/matebook-x-pro-2024-fingerprint),
[audio-power](https://github.com/onebany/matebook-x-pro-2024-audio-power)) at once, then reboot:

```bash
sudo apt install -y git && for r in camera fingerprint audio-power; do git clone https://github.com/onebany/matebook-x-pro-2024-$r && sudo ./matebook-x-pro-2024-$r/install.sh || break; done
```

## Power

- **xe** instead of i915 for the Meteor Lake iGPU (`i915.force_probe=!7d55 xe.force_probe=7d55`): working runtime PM, roughly 8 h on battery instead of 3.
- **intel-lpmd** with Intel's own Meteor Lake profile (`intel_lpmd_config_F6_M170.xml`
  from the package: workload-type states — idle, battery life, sustained,
  bursty — with matching EPP/EPB). lpmd reads that per-model file before the
  generic `intel_lpmd_config.xml`, so the generic one is left as packaged.

## Audio (Conexant CX11970, 2 tweeters + 4 woofers)

| Layer | What | Why |
|-------|------|-----|
| SOF | `sof-hda-generic-ace1-4ch.tplg`, `sof_use_tplg_nhlt=1`, flat EQ/DRC blobs for DMI `VGHH-XX` | all six speakers, no generic high-pass |
| ALSA | `Speaker` and `Bass Speaker` at 100%, stored in `asound.state` | tweeter/woofer balance |
| WirePlumber | `api.alsa.soft-mixer = true` | PipeWire never moves the hardware controls, so the balance cannot drift with the volume slider or a WirePlumber restart |
| PipeWire | filter-chain sink **MateBook Speakers**, the default output, feeding the Speaker sink: LSP 16-band EQ → Calf Bass Enhancer → LSP mid/side EQ (100 Hz high-pass, 150 Hz +6 dB, +6 dB side above 200 Hz) → LSP 3-band compressor (250 Hz / 1 kHz) → LSP limiter | the tuning that used to live in an EasyEffects preset, now inside pipewire: no GUI app, no session dependencies, active on the lock screen |

GNOME shows two outputs: **MateBook Speakers** (the DSP, default) and the raw
**Speaker** sink without it, which stays at 100% (`verify.sh` checks both;
`install.sh dsp` sets them). The MateBook Speakers slider scales the input,
before the DSP, so at low and medium volume the compressor and limiter stay
idle and only full volume is squeezed. (As a WirePlumber smart filter the
slider stayed on the Speaker sink, after the limiter, and every volume was
squeezed alike.) Bluetooth or USB outputs are untouched.

Changes against the EasyEffects preset, each measured with `./dsp-check.py`:

- 100 Hz high-pass after the enhancer (which has already turned the sub-bass
  into audible harmonics), 36 dB/oct, and no 70 Hz shelf. Below 100 Hz the
  speakers produce next to nothing (Windows: 80 Hz is 19 dB under the mids),
  yet that energy made the limiter turn the audible band down.
- Enhancer drive 2 instead of 10: at 10 the harmonics no longer followed the
  bass (loud bass 6 dB weaker than quiet bass).
- Limiter: lookahead 10 ms so the 20 ms release is real (with 5 ms it is cut
  to 10 ms and the limiter chops every cycle of a 50 Hz note); ALR stays off,
  it pumps the mix 8 dB on kicks.
- Body: in the room (`./mic-sweep.py`, below) 200-630 Hz sat 8-13 dB further
  under 1-2.5 kHz than on Windows. 300 Hz +9 dB wide, 500 Hz +5 dB, 1400 Hz
  -4 dB and 150 Hz +6 dB (after the enhancer, which keeps its input) bring
  125 Hz-4 kHz to 3.7 dB rms of the Windows curve at medium volume (was 6.7).
- 3-band compressor split at 250 Hz and 1 kHz, like Histen's DRC in the
  Windows driver: the single-band one dipped a steady 2.5 kHz tone 2 dB on
  every kick. The bass band (ratio 4, 80 ms attack) lets the kick through and
  holds the sustained bass, so at full volume the woofers get less 80-250 Hz
  than with any earlier tuning while medium volume gets the full lift.
  Loudness in the room: +1.7 to +2.9 dB for ordinary masters, -0.7 dB for
  very loud ones at full volume (the limiter's ceiling now carries the body).
- Side +6 dB above 200 Hz for width; the bass below stays mono.

`./mic-sweep.py` (out loud, ~9 s; pause the music) plays pink noise at full
volume through MateBook Speakers, or with `--raw` straight into the Speaker
sink, records the built-in mics and prints the response per 1/3 octave next to
Notebookcheck's Windows measurement of this laptop. Trust 125 Hz-4 kHz only:
the mic path is flat from 100 Hz up, but the mics in the lid hear the tweeters
off-axis. The room response with any chain is the `--raw` take plus the
chain's own transfer function (measured silently); that prediction matched
real takes of two chains within 1.1 and 1.0 dB on average, so tuning can stay
silent. This tuning, measured: 4.6 dB rms of the Windows curve at full volume
(the previous one 7.8), body 200-630 Hz -2.6 dB (was -9.5).

`./dsp-check.py` loads the filter-chain into a private pipewire client
(virtual sink → chain → virtual source, never the speakers), plays synthetic
test signals through it and checks width, squash, kick, pumping, distortion,
peak, sub-bass and level; about 30 s, needs `python3-numpy`. Run it after any
change to the tuning.

Tuning lives in `configs/60-matebook-speakers-dsp.conf` (values in dB in the
comments). After editing: `sudo ./install.sh dsp` or copy the file to
`/etc/pipewire/pipewire.conf.d/` and `systemctl --user restart pipewire`.

### Replaced

`install.sh audio` removes the earlier workarounds if present: the UCM
`Master`-volume include (dropped by every `alsa-ucm-conf` upgrade anyway), the
placeholder UCM product config `product_configs/HUAWEI/VGHH-XX.conf`, the
`intel/sof-ace-tplg` firmware symlink, the `matebook-speaker-balance` login
service and `matebook-audio-fix.sh`, and the `easyeffects-matebook` user
service. EasyEffects itself is left installed.

### Do not

- Never `sed -i` `/usr/share/alsa/ucm2/conf.d/sof-hda-dsp/sof-hda-dsp.conf`: it is a symlink and turning it into a file breaks UCM (Dummy Output).

## Requirements

Ubuntu 26.04, PipeWire 1.6 / WirePlumber 0.5, `lsp-plugins-lv2` and
`calf-plugins` from the archive (installed by `install.sh`).

## License

MIT. SOF/UCM findings come from
[Arch BBS #298027](https://bbs.archlinux.org/viewtopic.php?id=298027) and
[alsa-ucm-conf PR #410](https://github.com/alsa-project/alsa-ucm-conf/pull/410);
xe / intel-lpmd from [daichendt.one](https://daichendt.one/posts/matebook-x-pro-2024-linux/).
