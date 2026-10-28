#!/usr/bin/env bash
# shellcheck disable=SC2015  # "test && ok || fail": ok() always succeeds, so this is a plain if/else
# Health check for power + audio. Run as the desktop user (needs the PipeWire session).
set -u   # no pipefail: grep -q closing a pipe must not fail a check

ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; rc=1; }
rc=0

echo "power"
grep -qs '^DRIVER=xe' /sys/class/drm/card*/device/uevent && ok "iGPU on xe" || fail "iGPU not on xe (reboot after install? cat /proc/cmdline)"
systemctl is-active -q intel_lpmd && ok "intel_lpmd active" || fail "intel_lpmd not active"

echo "SOF / ALSA"
tplg="$(cat /sys/module/snd_sof_pci/parameters/tplg_filename 2>/dev/null)"
[[ $tplg == sof-hda-generic-ace1-4ch.tplg ]] && ok "topology $tplg" || fail "topology '${tplg:-?}' (expected ace1-4ch; reboot?)"
[[ -L /usr/share/alsa/ucm2/conf.d/sof-hda-dsp/sof-hda-dsp.conf ]] && ok "UCM conf.d link intact" || fail "UCM conf.d/sof-hda-dsp/sof-hda-dsp.conf is not a symlink (Dummy Output ahead)"
for c in Speaker 'Bass Speaker'; do
    amixer -c sofhdadsp sget "$c" 2>/dev/null | grep -q '\[100%\]' && ok "$c 100%" || fail "$c not at 100% (sudo ./install.sh audio)"
done

echo "PipeWire"
sink="$(wpctl status 2>/dev/null | grep -oE '[0-9]+\. Meteor Lake-P HD Audio Controller Speaker' | grep -oE '^[0-9]+')"
pw-dump 2>/dev/null | grep -qE '"api.alsa.soft-mixer": *(true|"true")' && ok "soft-mixer on the ALSA card" || fail "soft-mixer not applied (WirePlumber rule; systemctl --user restart wireplumber)"
wpctl status 2>/dev/null | grep -q 'matebook_speakers' && ok "DSP filter node present" || fail "DSP filter missing (journalctl --user -u pipewire -b | grep -i filter)"
wpctl inspect @DEFAULT_AUDIO_SINK@ 2>/dev/null | grep -q 'node.name = "matebook_speakers"' && ok "default sink is MateBook Speakers (the slider acts before the DSP)" || fail "default sink is not MateBook Speakers (sudo ./install.sh dsp)"
[[ -n $sink ]] && wpctl get-volume "$sink" | grep -q 'Volume: 1.00' && ok "raw Speaker sink at 100%" || fail "raw Speaker sink not at 100%: it turns the DSP output down after the limiter (wpctl set-volume ${sink:-ID} 1)"
if [[ "${1:-}" == "--live" ]]; then
    echo "live (2 s tone, muted): stream must reach the ALSA sink through matebook_speakers"
    was_muted=0
    if [[ -n $sink ]]; then
        wpctl get-volume "$sink" | grep -q MUTED && was_muted=1
        wpctl set-mute "$sink" 1
    fi
    timeout 6 gst-launch-1.0 -q audiotestsrc num-buffers=100 volume=0.02 ! audioconvert ! pipewiresink 2>/dev/null &
    sleep 1.5
    if pw-dump 2>/dev/null | python3 -c '
import json,sys
d=json.load(sys.stdin); n={o["id"]:o["info"]["props"].get("node.name","") for o in d if o["type"].endswith("Node")}
links=[(n.get(o["info"]["output-node-id"],""), n.get(o["info"]["input-node-id"],"")) for o in d if o["type"].endswith("Link")]
ok_in  = any(b=="matebook_speakers" and "matebook" not in a for a,b in links)
ok_out = any(a=="matebook_speakers.out" and "HiFi__Speaker__sink" in b for a,b in links)
sys.exit(0 if ok_in and ok_out else 1)'; then ok "audio flows app -> DSP -> Speaker"; else fail "DSP not in the path (wpctl status; pw-dump links)"; fi
    wait
    [[ -n $sink ]] && wpctl set-mute "$sink" "$was_muted"
fi
pgrep -x easyeffects >/dev/null && fail "easyeffects still running (legacy)" || ok "no EasyEffects process"

exit $rc
