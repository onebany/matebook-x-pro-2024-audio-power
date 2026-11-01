# Huawei MateBook X Pro 2024 on Ubuntu: audio

```bash
sudo apt install -y git && git clone https://github.com/onebany/matebook-x-pro-2024-audio-power && sudo ./matebook-x-pro-2024-audio-power/install.sh
```

## Русский

Только для MateBook X Pro 2024 (VGHH-XX): на другом ноутбуке `install.sh` ничего не меняет. Проверено на Ubuntu 26.10.
После первой установки перезагрузите ноутбук и запустите `./matebook-x-pro-2024-audio-power/verify.sh --live`.
Обновление: `git -C matebook-x-pro-2024-audio-power pull && sudo ./matebook-x-pro-2024-audio-power/install.sh`.

- Динамики в четырёх каналах, как в Windows: вуферы играют бас и середину, твитеры верх.
- Обработка повторяет звук Windows с включёнными «улучшениями» Huawei и работает прямо в выходе «Speaker». 100 % звучит примерно как 100 % в Windows, выше звук обрезается.
- При загрузке и после сна служба включает усилителям режим, в котором играет Windows. Там динамики бережёт SmartPA Huawei, здесь ограничитель мощности в обработке. Режим на 8–9 дБ тише, как в Windows без обработки Huawei: `echo MODE=inbox | sudo tee /etc/default/matebook-amps && sudo systemctl start matebook-amps`.

## English

Only for the MateBook X Pro 2024 (VGHH-XX): on any other laptop `install.sh` changes nothing. Tested on Ubuntu 26.10.
Reboot after the first install, then run `./matebook-x-pro-2024-audio-power/verify.sh --live`.
To update: `git -C matebook-x-pro-2024-audio-power pull && sudo ./matebook-x-pro-2024-audio-power/install.sh`.

- Speakers in four channels, as on Windows: the woofers play bass and mids, the tweeters the highs.
- The DSP reproduces Windows with Huawei's "Audio enhancements" on and runs inside the "Speaker" output. 100 % is about as loud as 100 % on Windows; above that the sound clips.
- At boot and after every resume a service sets the amps to the mode Windows plays in. Windows protects the speakers there with Huawei's SmartPA; here a power limiter in the DSP does. 8–9 dB quieter, the mode Windows uses without Huawei's processing: `echo MODE=inbox | sudo tee /etc/default/matebook-amps && sudo systemctl start matebook-amps`.

## Camera, fingerprint / Камера, отпечаток

[matebook-x-pro-2024-camera](https://github.com/onebany/matebook-x-pro-2024-camera), [matebook-x-pro-2024-fingerprint](https://github.com/onebany/matebook-x-pro-2024-fingerprint). All three / все три:

```bash
sudo apt install -y git && for r in camera fingerprint audio-power; do git clone https://github.com/onebany/matebook-x-pro-2024-$r && sudo ./matebook-x-pro-2024-$r/install.sh || break; done
```

## License / Лицензия

MIT; `topology/spk4.patch` and `configs/sof-hda-generic-ace1-4ch-spk4.tplg`: BSD-3-Clause (SOF topology sources).
Based on / на основе: [Arch BBS #298027](https://bbs.archlinux.org/viewtopic.php?id=298027), [alsa-ucm-conf PR #410](https://github.com/alsa-project/alsa-ucm-conf/pull/410).
