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
| PipeWire | filter-chain **smart filter** in front of the Speaker sink: LSP 16-band EQ → Calf Bass Enhancer → 100 Hz high-pass → LSP compressor → LSP limiter | the tuning that used to live in an EasyEffects preset, now inside pipewire: no GUI app, no session dependencies, active on the lock screen |

The DSP is transparent: GNOME still shows the usual "Speaker" output and its
volume slider (software volume, the ALSA controls stay put). WirePlumber
routes every stream to the speakers through the filter (`wpctl status` lists it
under *Filters*). Bluetooth or USB outputs are untouched.

Two changes against the EasyEffects preset, measured offline through these
same plugins (30 s of bass-heavy funk and of acoustic music, 0 dBFS ceiling):
the preset's x4-slope bass shelf plus the enhancer lift 40–80 Hz by ~30 dB, so
89% of the output energy sat below 100 Hz where laptop speakers produce next to
nothing, and the limiter turned everything else down to make room for it. A
100 Hz high-pass after the enhancer (which has already turned that bass into
audible harmonics) and +4 dB compressor makeup make the 150 Hz–15 kHz band
4–6 dB louder with about the same pumping; the curve above 120 Hz is
unchanged (±0.6 dB).

Tuning lives in `configs/60-matebook-speakers-dsp.conf` (values in dB in the
comments). After editing: `sudo ./install.sh dsp` or copy the file to
`/etc/pipewire/pipewire.conf.d/` and `systemctl --user restart pipewire`.

### Replaced

`install.sh audio` removes the earlier workarounds if present: the UCM
`Master`-volume include (dropped by every `alsa-ucm-conf` upgrade anyway), the
`matebook-speaker-balance` login service and `matebook-audio-fix.sh`, and the
`easyeffects-matebook` user service. EasyEffects itself is left installed.

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
