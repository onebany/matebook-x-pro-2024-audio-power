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
| PipeWire | filter-chain **smart filter** in front of the Speaker sink: LSP 16-band EQ → Calf Bass Enhancer → LSP mid/side EQ (100 Hz high-pass, +4 dB side above 200 Hz) → LSP compressor → LSP limiter | the tuning that used to live in an EasyEffects preset, now inside pipewire: no GUI app, no session dependencies, active on the lock screen |

The DSP is transparent: GNOME still shows the usual "Speaker" output and its
volume slider (software volume, the ALSA controls stay put). WirePlumber
routes every stream to the speakers through the filter (`wpctl status` lists it
under *Filters*). Bluetooth or USB outputs are untouched.

The volume slider acts after the DSP, so the compressor and limiter always
see the full-scale signal. Changes against the EasyEffects preset, each
measured with `./dsp-check.py`:

- 100 Hz high-pass after the enhancer (which has already turned the sub-bass
  into audible harmonics), 36 dB/oct, and no 70 Hz shelf. Below 100 Hz the
  speakers produce next to nothing (Windows: 80 Hz is 19 dB under the mids),
  yet that energy made the limiter turn the audible band down.
- Enhancer drive 2 instead of 10: at 10 the harmonics no longer followed the
  bass (loud bass 6 dB weaker than quiet bass) and smeared distortion up to
  2.5 kHz.
- Limiter: lookahead 10 ms so the 20 ms release is real (with 5 ms it is cut
  to 10 ms and the limiter chops every cycle of a 50 Hz note); ALR stays off,
  it pumps the mix 8 dB on kicks. Compressor attack 40 ms, makeup +4 dB,
  120 Hz bell +3 dB: fewer peaks for the limiter, the kick stands out again.
- Side +4 dB above 200 Hz for width; the bass below stays mono.

At music level the curve above 160 Hz is unchanged (±0.8 dB).

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
