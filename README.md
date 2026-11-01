# Huawei MateBook X Pro 2024 — power & audio on Ubuntu

Install (one command), then reboot:

```bash
sudo apt install -y git && git clone https://github.com/onebany/matebook-x-pro-2024-audio-power && sudo ./matebook-x-pro-2024-audio-power/install.sh
```

Check after the reboot: `./matebook-x-pro-2024-audio-power/verify.sh --live`.
On any other laptop (DMI not `HUAWEI` / `VGHH-XX`) `install.sh` stops before changing anything.

All three MateBook X Pro 2024 repos ([camera](https://github.com/onebany/matebook-x-pro-2024-camera),
[fingerprint](https://github.com/onebany/matebook-x-pro-2024-fingerprint),
[audio-power](https://github.com/onebany/matebook-x-pro-2024-audio-power)) at once, then reboot:

```bash
sudo apt install -y git && for r in camera fingerprint audio-power; do git clone https://github.com/onebany/matebook-x-pro-2024-$r && sudo ./matebook-x-pro-2024-$r/install.sh || break; done
```

## Power

- **CPU limits**, `matebook-cpu-limits.service`: the EC fan stays at about
  3700-4600 rpm even at 100 °C and Linux cannot drive it, so uncapped cores sit
  at 100 °C and throttle. The service caps every core at 3.2 GHz and sets RAPL
  PL1 18 W (28 s) / PL2 30 W at boot; one core then runs 3.18 GHz at 81 °C, idle
  73 °C at 11.7 W.
- **intel-lpmd** with Intel's own Meteor Lake profile (`intel_lpmd_config_F6_M170.xml`
  from the package: workload-type states — idle, battery life, sustained,
  bursty — with matching EPP/EPB). lpmd reads that per-model file before the
  generic `intel_lpmd_config.xml`, so the generic one is left as packaged.
- The iGPU stays on **i915**: xe (`i915.force_probe=!7d55 xe.force_probe=7d55`)
  gave working runtime PM, about 8 h on battery instead of 3, but GPU resets here.

## Audio (Conexant CX11970, 2 tweeters + 4 woofers)

| Layer | What | Why |
|-------|------|-----|
| SOF | `sof-hda-generic-ace1-4ch-spk4.tplg` (stock `ace1-4ch` with the speaker PCM in 4 channels, `topology/build.sh`), `sof_use_tplg_nhlt=1`, flat EQ/DRC blobs for DMI `VGHH-XX` | woofers and tweeters get their own channels, as on Windows; no generic high-pass |
| UCM | card file `conf.d/sof-hda-dsp/HUAWEI-VGHH_XX-M1010-VGHH_XX_PCB.conf` → a copy of the stock `sof-hda-dsp.conf` whose HiFi verb adds `PlaybackChannels 4` to Speaker | the stock UCM opens Speaker in 2 channels, which the 4-channel PCM refuses (Dummy Output) |
| ALSA | `Speaker` (DAC 0x23, woofers) and `Bass Speaker` (DAC 0x22, tweeters, despite the name) at 100%, stored in `asound.state` | tweeter/woofer balance |
| WirePlumber | `api.alsa.soft-mixer = true` | PipeWire never moves the hardware controls, so the balance cannot drift with the volume slider or a WirePlumber restart |
| Amps | `matebook-amps.service` → `amps.py algo` at boot and after every resume: the three FourSemi FS2119 amps (ACPI `HWSP0001`, I2C) get the registers Windows' MultiPADriver writes when it plays | the BIOS leaves the tweeter amp 21-29 dB down |
| WirePlumber | a graph inside the **Speaker** output itself (`monitor.alsa.rules`: the ALSA node's `audioconvert.filter-graph.0`): Huawei Histen (EQ, 3-band compressor, limiter) → the Speaker volume → SmartPA crossover (woofers FL FR below 3.2 kHz, tweeters RL RR above 3 kHz) → a power guard per speaker group | the sound of Windows with "Audio enhancements" on |

GNOME shows one output, **Speaker**, with the DSP inside. Its slider acts in
the graph, after the Histen dynamics, as the Windows volume does: the sound
keeps its character at every volume. Bluetooth, USB and HDMI are untouched.
The graph takes FL FR; what PipeWire upmixes onto RL RR is ignored, so the
rear channels of 5.1 content are dropped.

Earlier versions made the DSP a separate "MateBook Speakers" filter-chain
sink aimed at Speaker. WirePlumber destroys such a sink whenever Speaker is
briefly gone (the card coming up after boot, a profile switch), and the DSP
stayed gone until PipeWire restarted. The graph cannot go through
`node.filter-graph.rules` either: that path sets it as a runtime parameter,
which PipeWire 1.6 cuts at 4 KB, and this graph is 56 KB.

The chain is the approximation a Windows agent fitted to WASAPI loopback
captures of a test file (Histen set SMART_ONE, which Windows uses below 53 %
volume; SMART_THREE above differs only below 250 Hz and in stereo width).
Through it the same file lands within 0.3-2 dB per third octave of Windows'
own loopback on every level from -45 to -15 dBFS. Its LADSPA compressors and
limiter come from `swh-plugins`.

`./dsp-check.py` runs the graph the way Speaker does, in a stream's
audioconvert with Speaker's four channels (a private loopback feeds
`pw-record` carrying the graph, never the speakers), and checks the
crossover (no bass on the tweeters), clipping, the guard, that a dense master
stays under the guard and that the slider acts after the dynamics; about
1 min, needs `python3-numpy`. Run it after any change to
`configs/60-matebook-speakers-dsp.conf`, then `sudo ./install.sh dsp`.

`./mic-sweep.py` (out loud, ~9 s; pause the music) plays pink noise at full
volume into Speaker, records the built-in mics and prints the response per 1/3 octave next to
Notebookcheck's Windows measurement of this laptop. Trust 125 Hz-4 kHz only:
the mics in the lid hear the tweeters off-axis.

### Amps: ALGO, and the guard instead of Huawei's protection

Windows' MultiPADriver has two setups for the amps: INBOX (scenes 2 + 3), its
default without the Huawei APO, and ALGO (scenes 0 + 3), the gain it plays at
while Huawei's SmartPA protects the speakers (voltage/current sense, a coil
temperature model, a power limiter). `amps.py` writes ALGO: in the room it is
+8.8 dB on the woofers and +8.2 dB on the tweeters over INBOX, and 100 % on
the slider is then about as loud as Windows. INBOX alone tops out 8-9 dB
lower, which is why GNOME's over-amplification seemed needed.

SmartPA does not run here. In its place the chain ends in a power guard per
speaker group (LSP compressor, 250 ms RMS, ratio 100): never more than a
full-scale sine gets in INBOX, -11.8 dBFS RMS on the woofer outputs and
-11.2 on the tweeters. Music does not reach it: the Histen dynamics hold a
dense master at -14 dBFS RMS. What it catches is sustained tones, a held bass
note at 100-150 Hz most of all, which without it got 4x that power. Short
peaks pass, as on Windows. The plans in `configs/amps-*.tsv` are the driver's
`.dat` records in the order of its ETW trace; every write is read back.

Above 100 % (over-amplification) the samples after the dynamics clip; there
is no point in it any more.

Quieter amps (INBOX): `echo MODE=inbox | sudo tee /etc/default/matebook-amps`
and `sudo systemctl start matebook-amps`. Back to the BIOS setup:
`sudo systemctl disable matebook-amps` and reboot; then the tweeters are
quiet again and the sound turns dull.

### Replaced

`install.sh audio` removes the earlier workarounds if present: the UCM
`Master`-volume include (dropped by every `alsa-ucm-conf` upgrade anyway), the
placeholder UCM product config `product_configs/HUAWEI/VGHH-XX.conf`, the
`intel/sof-ace-tplg` firmware symlink, the `matebook-speaker-balance` login
service and `matebook-audio-fix.sh`, and the `easyeffects-matebook` user
service. EasyEffects itself is left installed.

### Speakers in 4 channels

The Speaker sink is FL FR RL RR: FL FR drive the four woofers (DAC 0x23),
RL RR the two tweeters (DAC 0x22), the layout Windows sends. With the stock
2-channel topology both DACs played the same stereo signal, so the woofers
carried the whole band.

The kernel fixes the channels of the HDA link up from the last copier with
its name, which is the capture one. That is why the capture side of the link
is 4 channels too: with a 2-channel capture copier, the 4-channel playback ran
at half speed.

### Roll back to the stock 2-channel topology

`tplg_filename=sof-hda-generic-ace1-4ch.tplg` in
`/etc/modprobe.d/alsa-sof-matebook.conf`, then
`sudo rm /usr/share/alsa/ucm2/conf.d/sof-hda-dsp/HUAWEI-VGHH_XX-M1010-VGHH_XX_PCB.conf`,
`sudo update-initramfs -u` and reboot. Both go together: the 4-channel UCM on
the stock topology, or the reverse, leaves Dummy Output.

### Do not

- Never `sed -i` `/usr/share/alsa/ucm2/conf.d/sof-hda-dsp/sof-hda-dsp.conf`: it is a symlink and turning it into a file breaks UCM (Dummy Output).
- No second `SectionUseCase."HiFi"` next to an include of the stock card file: alsa-lib keeps the stock one and ignores ours.

## Requirements

Ubuntu 26.10 (kernel 7.3), PipeWire 1.6 / WirePlumber 0.5, `lsp-plugins-lv2` and
`swh-plugins` from the archive (installed by `install.sh`).

## License

MIT; `topology/spk4.patch` and `configs/sof-hda-generic-ace1-4ch-spk4.tplg` derive
from the SOF topology sources (BSD-3-Clause). SOF/UCM findings come from
[Arch BBS #298027](https://bbs.archlinux.org/viewtopic.php?id=298027) and
[alsa-ucm-conf PR #410](https://github.com/alsa-project/alsa-ucm-conf/pull/410);
xe and intel-lpmd from [daichendt.one](https://daichendt.one/posts/matebook-x-pro-2024-linux/).
