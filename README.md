# Huawei MateBook X Pro 2024 — power & audio on Ubuntu

```bash
git clone <repo-url> matebook-x-pro-2024-audio-power
cd matebook-x-pro-2024-audio-power
sudo ./install.sh && sudo reboot
./verify.sh --live
```

## Power

- **xe** instead of i915 for the Meteor Lake iGPU (`i915.force_probe=!7d55 xe.force_probe=7d55`): working runtime PM, roughly 8 h on battery instead of 3.
- **intel-lpmd** with `lp_mode_cpus = 12-21`: P-cores are parked under low load.

## Audio (Conexant CX11970, 2 tweeters + 4 woofers)

| Layer | What | Why |
|-------|------|-----|
| SOF | `sof-hda-generic-ace1-4ch.tplg`, `sof_use_tplg_nhlt=1`, flat EQ/DRC blobs for DMI `VGHH-XX` | all six speakers, no generic high-pass |
| ALSA | `Speaker` and `Bass Speaker` at 100%, stored in `asound.state` | tweeter/woofer balance |
| WirePlumber | `api.alsa.soft-mixer = true`, Speaker profile pinned | PipeWire never moves the hardware controls, so the balance cannot drift with the volume slider or a WirePlumber restart |
| PipeWire | filter-chain **smart filter** in front of the Speaker sink: LSP 16-band EQ → Calf Bass Enhancer → LSP compressor → LSP limiter | the tuning that used to live in an EasyEffects preset, now inside pipewire: no GUI app, no session dependencies, active on the lock screen |

The DSP is transparent: GNOME still shows the usual "Speaker" output and its
volume slider (software volume, the ALSA controls stay put). WirePlumber
routes every stream to the speakers through the filter (`wpctl status` lists it
under *Filters*). Bluetooth or USB outputs are untouched.

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
