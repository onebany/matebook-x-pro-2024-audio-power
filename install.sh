#!/usr/bin/env bash
#
# Huawei MateBook X Pro 2024 on Ubuntu 26.04:
#   power  — CPU limits for the barely ramping fan, intel-lpmd (the iGPU stays on i915)
#   audio  — SOF topology with the speakers in 4 channels, UCM, ALSA levels, WirePlumber rule
#   amps   — the FS2119 speaker amps as Windows plays them, at boot and after every resume
#   dsp    — the speaker DSP inside the "Speaker" output (Windows' Histen + SmartPA sound)
#
#   sudo ./install.sh              # everything
#   sudo ./install.sh amps dsp     # any subset of: power audio amps dsp
#
# Re-runnable. Reboot once after the first run (SOF topology and modprobe options).
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run as root: sudo $0" >&2; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG="$HERE/configs"
USER_NAME="${SUDO_USER:-}"
USER_HOME="$([[ -n $USER_NAME ]] && getent passwd "$USER_NAME" | cut -d: -f6 || true)"
USER_UID="$([[ -n $USER_NAME ]] && id -u "$USER_NAME" || true)"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# A command in the invoking desktop user's session; best-effort (no session = no-op).
as_user() {
    [[ -n $USER_NAME && -S /run/user/$USER_UID/bus ]] || return 0
    runuser -u "$USER_NAME" -- env XDG_RUNTIME_DIR="/run/user/$USER_UID" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_UID/bus" \
        "$@" 2>/dev/null || true
}
user_systemctl() { as_user systemctl --user "$@"; }

# --------------------------------------------------------------------- power
stage_power() {
    log "CPU limits (the EC fan barely ramps on Linux): every core at most 3.2 GHz, RAPL PL1 18 W / PL2 30 W"
    install -m644 "$CFG/matebook-cpu-limits.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable -q matebook-cpu-limits.service
    systemctl restart matebook-cpu-limits.service

    log "intel-lpmd with Intel's Meteor Lake profile (intel_lpmd_config_F6_M170.xml)"
    apt-get install -y --no-install-recommends intel-lpmd >/dev/null
    # lpmd reads the per-CPU-model file before the generic intel_lpmd_config.xml,
    # so an edited generic file is never used here. Older versions of this repo
    # overwrote that conffile anyway: put the packaged one back.
    if [[ "$(dpkg --verify intel-lpmd 2>/dev/null || true)" == *" /etc/intel_lpmd/intel_lpmd_config.xml"* ]]; then
        rm -f /etc/intel_lpmd/intel_lpmd_config.xml
        apt-get install -y --reinstall -o Dpkg::Options::=--force-confmiss intel-lpmd >/dev/null
    fi
    systemctl enable -q intel_lpmd
    systemctl restart intel_lpmd
}

# --------------------------------------------------------------------- audio
stage_audio() {
    log "SOF: speakers in 4 channels (woofers FL FR, tweeters RL RR) + NHLT, flat DSP blobs"
    apt-get install -y --no-install-recommends alsa-utils >/dev/null
    install -Dm644 "$CFG/sof-hda-generic-ace1-4ch-spk4.tplg" \
        /lib/firmware/updates/intel/sof-ipc4-tplg/sof-hda-generic-ace1-4ch-spk4.tplg
    install -m644 "$CFG/alsa-sof-matebook.conf" /etc/modprobe.d/
    install -Dm644 "$CFG/HUAWEI-VGHH-XX-user.conf" \
        /usr/share/alsa/ucm2/blobs/sof/user_configs/HUAWEI/VGHH-XX.conf
    # UCM opens Speaker in 2 channels, which the 4-channel PCM refuses (no HiFi profile, Dummy Output).
    # alsa-lib takes conf.d/<driver>/<card long name>.conf before the stock <driver>.conf, and the first
    # SectionUseCase wins, so the card file is the stock one with only its HiFi verb file swapped.
    # Regenerated on every run: after an alsa-ucm-conf upgrade re-run this stage. Stock files stay as packaged.
    local ucm=/usr/share/alsa/ucm2/Intel/sof-hda-dsp
    install -m644 "$CFG/ucm-HiFi-matebook-x-pro-2024.conf" "$ucm/HiFi-matebook-x-pro-2024.conf"
    sed 's|File "/Intel/sof-hda-dsp/HiFi.conf"|File "/Intel/sof-hda-dsp/HiFi-matebook-x-pro-2024.conf"|' \
        "$ucm/sof-hda-dsp.conf" > "$ucm/matebook-x-pro-2024.conf"
    grep -q HiFi-matebook-x-pro-2024 "$ucm/matebook-x-pro-2024.conf" \
        || { echo "no HiFi verb line in $ucm/sof-hda-dsp.conf (alsa-ucm-conf changed?)" >&2; exit 1; }
    ln -sfn ../../Intel/sof-hda-dsp/matebook-x-pro-2024.conf \
        /usr/share/alsa/ucm2/conf.d/sof-hda-dsp/HUAWEI-VGHH_XX-M1010-VGHH_XX_PCB.conf
    update-initramfs -u >/dev/null

    log "ALSA: tweeters and woofers at 100%, stored in asound.state"
    # PipeWire never touches these again (api.alsa.soft-mixer below), so the
    # balance set here survives volume changes, logins and WirePlumber restarts.
    for c in Speaker 'Bass Speaker'; do
        amixer -q -c sofhdadsp sset "$c" 100% unmute 2>/dev/null \
            || echo "    !! no ALSA control '$c' yet — reboot, then: sudo $0 audio"
    done
    alsactl store 2>/dev/null || true

    log "WirePlumber: software mixer (hardware Speaker controls stay at 100%)"
    install -Dm644 "$CFG/51-matebook-audio.conf" \
        /etc/wireplumber/wireplumber.conf.d/51-matebook-audio.conf

    log "Removing the previous UCM / EasyEffects / balance-at-login workarounds"
    sed -i '/huawei-matebook-speaker/d' /usr/share/alsa/ucm2/Intel/sof-hda-dsp/HiFi.conf 2>/dev/null || true
    rm -f /usr/share/alsa/ucm2/Intel/sof-hda-dsp/huawei-matebook-speaker.conf \
          /usr/share/alsa/ucm2/conf.d/sof-hda-dsp/huawei-vgxx-speaker.conf \
          /usr/share/alsa/ucm2/blobs/sof/product_configs/HUAWEI/VGHH-XX.conf \
          /etc/systemd/user/matebook-speaker-balance.service \
          /usr/local/bin/matebook-audio-fix.sh
    # Meteor Lake kernels load topologies from intel/sof-ipc4-tplg only.
    [[ -L /lib/firmware/intel/sof-ace-tplg ]] && rm /lib/firmware/intel/sof-ace-tplg
    user_systemctl disable --now easyeffects-matebook.service matebook-speaker-balance.service
    if [[ -n $USER_HOME ]]; then
        rm -f "$USER_HOME/.config/systemd/user/easyeffects-matebook.service" \
              "$USER_HOME/.config/systemd/user/matebook-speaker-balance.service" \
              "$USER_HOME/.config/wireplumber/wireplumber.conf.d/51-matebook-audio.conf"
    fi
    user_systemctl daemon-reload
}

# ---------------------------------------------------------------------- amps
stage_amps() {
    log "FS2119 speaker amps as Windows plays them (ALGO), at boot and after every resume"
    install -Dm644 -t /usr/local/lib/matebook-x-pro-2024 "$HERE/amps.py" "$CFG/amps-algo.tsv" "$CFG/amps-inbox.tsv"
    install -m644 "$CFG/matebook-amps.service" /etc/systemd/system/
    systemctl daemon-reload
    systemctl enable -q matebook-amps.service
    systemctl restart matebook-amps.service || { journalctl -b -u matebook-amps -n 20 --no-pager; exit 1; }
    echo "    $(cat /run/matebook-amps)"
}

# ----------------------------------------------------------------------- dsp
stage_dsp() {
    log "Speaker DSP (Windows' Histen + SmartPA, swh LADSPA, LSP guard) inside the \"Speaker\" output"
    apt-get install -y --no-install-recommends lsp-plugins-lv2 swh-plugins >/dev/null
    install -Dm644 "$CFG/60-matebook-speakers-dsp.conf" \
        /etc/wireplumber/wireplumber.conf.d/60-matebook-speakers-dsp.conf
    # earlier versions: a separate "MateBook Speakers" filter-chain sink
    rm -f /etc/pipewire/pipewire.conf.d/60-matebook-speakers-dsp.conf
}

# After the restart: Speaker is the default output again (earlier versions made
# their separate "MateBook Speakers" sink the default).
dsp_default() {
    [[ -n $USER_NAME && -S /run/user/$USER_UID/bus ]] || return 0
    log "Default output: Speaker"
    as_user pw-metadata 0 default.configured.audio.sink \
        '{ "name": "alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Speaker__sink" }' Spa:String:JSON >/dev/null
}

main() {
    local stages=("$@")
    [[ ${#stages[@]} -eq 0 ]] && stages=(power audio amps dsp)
    for s in "${stages[@]}"; do
        case "$s" in
            power|audio|amps|dsp) "stage_$s" ;;
            *) echo "unknown stage '$s' (power audio amps dsp)" >&2; exit 1 ;;
        esac
    done
    log "Restarting the desktop user's PipeWire session"
    user_systemctl restart pipewire pipewire-pulse wireplumber
    [[ " ${stages[*]} " == *" dsp "* ]] && dsp_default
    cat <<EOF

Done. After a reboot run (as your user):  $HERE/verify.sh --live
Output device in GNOME Sound: "Speaker", with the DSP inside; its slider is the volume.
EOF
}

main "$@"
