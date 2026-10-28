#!/usr/bin/env bash
#
# Huawei MateBook X Pro 2024 on Ubuntu 26.04:
#   power  — Intel xe driver for the Meteor Lake iGPU, intel-lpmd
#   audio  — SOF 6-speaker topology, fixed tweeter/woofer balance, WirePlumber rule
#   dsp    — PipeWire filter-chain sink "MateBook Speakers" (EQ, bass, comp, limiter)
#
#   sudo ./install.sh              # everything
#   sudo ./install.sh audio dsp    # any subset of: power audio dsp
#
# Re-runnable. Reboot once after the first run (GRUB + SOF modprobe options).
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run as root: sudo $0" >&2; exit 1; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CFG="$HERE/configs"
USER_NAME="${SUDO_USER:-}"
USER_HOME="$([[ -n $USER_NAME ]] && getent passwd "$USER_NAME" | cut -d: -f6 || true)"
USER_UID="$([[ -n $USER_NAME ]] && id -u "$USER_NAME" || true)"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

# systemctl --user for the invoking desktop user; best-effort (no session = no-op).
user_systemctl() {
    [[ -n $USER_NAME && -S /run/user/$USER_UID/bus ]] || return 0
    runuser -u "$USER_NAME" -- env XDG_RUNTIME_DIR="/run/user/$USER_UID" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_UID/bus" \
        systemctl --user "$@" 2>/dev/null || true
}

# --------------------------------------------------------------------- power
stage_power() {
    log "GRUB: i915 -> xe for the Meteor Lake iGPU (runtime PM, ~2x battery)"
    if grep -q 'xe.force_probe=7d55' /etc/default/grub; then
        echo "    already set"
    else
        sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 i915.force_probe=!7d55 xe.force_probe=7d55"/' \
            /etc/default/grub
        update-grub >/dev/null
        echo "    reboot required for xe"
    fi

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
    log "SOF: ace1-4ch topology + NHLT (drives all 6 speakers), flat DSP blobs"
    apt-get install -y --no-install-recommends alsa-utils >/dev/null
    install -m644 "$CFG/alsa-sof-matebook.conf" /etc/modprobe.d/
    install -Dm644 "$CFG/HUAWEI-VGHH-XX-user.conf" \
        /usr/share/alsa/ucm2/blobs/sof/user_configs/HUAWEI/VGHH-XX.conf
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

# ----------------------------------------------------------------------- dsp
stage_dsp() {
    log "PipeWire speaker DSP (LSP EQ/compressor/limiter, Calf bass enhancer) as a WirePlumber smart filter"
    apt-get install -y --no-install-recommends lsp-plugins-lv2 calf-plugins >/dev/null
    install -Dm644 "$CFG/60-matebook-speakers-dsp.conf" \
        /etc/pipewire/pipewire.conf.d/60-matebook-speakers-dsp.conf
}

main() {
    local stages=("$@")
    [[ ${#stages[@]} -eq 0 ]] && stages=(power audio dsp)
    for s in "${stages[@]}"; do
        case "$s" in
            power|audio|dsp) "stage_$s" ;;
            *) echo "unknown stage '$s' (power audio dsp)" >&2; exit 1 ;;
        esac
    done
    log "Restarting the desktop user's PipeWire session"
    user_systemctl restart pipewire pipewire-pulse wireplumber
    cat <<EOF

Done. After a reboot run (as your user):  $HERE/verify.sh --live
Output device in GNOME Sound stays "Speaker"; the DSP sits in front of it.
EOF
}

main "$@"
