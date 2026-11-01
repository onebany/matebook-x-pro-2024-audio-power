#!/usr/bin/env bash
# shellcheck disable=SC2015  # "test && ok || fail": ok() always succeeds, so this is a plain if/else
# Health check for the speakers. Run as the desktop user (needs the PipeWire session).
set -u   # no pipefail: grep -q closing a pipe must not fail a check

ok()   { printf '  \033[32mOK\033[0m   %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; rc=1; }
rc=0
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "SOF / ALSA"
tplg="$(cat /sys/module/snd_sof_pci/parameters/tplg_filename 2>/dev/null)"
[[ $tplg == sof-hda-generic-ace1-4ch-spk4.tplg ]] && ok "topology $tplg (speakers in 4 channels)" || fail "topology '${tplg:-?}' (expected ace1-4ch-spk4; sudo ./install.sh audio, reboot)"
[[ -L /usr/share/alsa/ucm2/conf.d/sof-hda-dsp/sof-hda-dsp.conf ]] && ok "UCM conf.d link intact" || fail "UCM conf.d/sof-hda-dsp/sof-hda-dsp.conf is not a symlink (Dummy Output ahead)"
alsaucm -c hw:sofhdadsp dump text 2>/dev/null | sed -n '/Device.Speaker/,/}/p' | grep -q 'PlaybackChannels 4' && ok "UCM opens Speaker in 4 channels" || fail "UCM Speaker not in 4 channels: the 4-channel PCM fails, Dummy Output (sudo ./install.sh audio)"
for c in Speaker 'Bass Speaker'; do
    amixer -c sofhdadsp sget "$c" 2>/dev/null | grep -q '\[100%\]' && ok "$c 100%" || fail "$c not at 100% (sudo ./install.sh audio)"
done

echo "amps"
amps="$(cat /run/matebook-amps 2>/dev/null)"
[[ $amps == algo:* || $amps == inbox:* ]] && ok "FS2119 amps: $amps" || fail "FS2119 amps not set up: '${amps:-no status}' (systemctl status matebook-amps; sudo ./install.sh amps)"

echo "PipeWire"
sink="$(wpctl status 2>/dev/null | grep -oE '[0-9]+\. Meteor Lake-P HD Audio Controller Speaker' | grep -oE '^[0-9]+')"
pw-dump 2>/dev/null | grep -qE '"api.alsa.soft-mixer": *(true|"true")' && ok "soft-mixer on the ALSA card" || fail "soft-mixer not applied (WirePlumber rule; systemctl --user restart wireplumber)"
[[ -e /usr/lib/ladspa/sc4_1882.so && -e /usr/lib/ladspa/fast_lookahead_limiter_1913.so ]] && ok "LADSPA sc4 + fastLookaheadLimiter (swh-plugins)" || fail "swh-plugins missing: the DSP chain cannot load (sudo ./install.sh dsp)"
cmp -s /etc/wireplumber/wireplumber.conf.d/60-matebook-speakers-dsp.conf "$HERE/configs/60-matebook-speakers-dsp.conf" && ok "DSP rule for the Speaker output as in the repo" || fail "DSP rule missing or differs from configs/ (sudo ./install.sh dsp)"
[[ ! -e /etc/pipewire/pipewire.conf.d/60-matebook-speakers-dsp.conf ]] && ok "no separate MateBook Speakers sink (earlier versions)" || fail "old MateBook Speakers sink still configured in /etc/pipewire (sudo ./install.sh dsp)"
pid="$(systemctl --user show -p MainPID --value pipewire 2>/dev/null)"
[[ -n $sink ]] && wpctl inspect "$sink" | grep -q 'audioconvert.filter-graph.0' &&
    ! journalctl --user -b _PID="${pid:-0}" -o cat 2>/dev/null | grep -qiE "can't load filter-graph|failed to activate graph" &&
    ok "DSP inside Speaker (graph set, no load errors in this PipeWire)" || fail "Speaker plays without the DSP (journalctl --user -u pipewire -b | grep -i graph)"
wpctl inspect @DEFAULT_AUDIO_SINK@ 2>/dev/null | grep -q 'node.name = "alsa_output.*HiFi__Speaker__sink"' && ok "default output is Speaker (its slider acts after the dynamics)" || fail "default output is not Speaker (wpctl set-default ${sink:-ID})"
[[ -n $sink ]] && wpctl inspect "$sink" | grep -q 'audio.position = "\[ FL, FR, RL, RR \]"' && ok "Speaker sink FL FR (woofers) RL RR (tweeters)" || fail "Speaker sink is not 4 channels FL FR RL RR (wpctl inspect ${sink:-ID})"
if [[ "${1:-}" == "--live" ]]; then
    echo "live (2 s tone, muted): an app's stream must go straight into Speaker"
    was_muted=0
    if [[ -n $sink ]]; then
        wpctl get-volume "$sink" | grep -q MUTED && was_muted=1
        wpctl set-mute "$sink" 1
    fi
    timeout 6 gst-launch-1.0 -q audiotestsrc num-buffers=100 volume=0.02 ! audioconvert ! \
        pipewiresink stream-properties="props,node.name=verify-tone" 2>/dev/null &
    sleep 1.5
    if pw-dump 2>/dev/null | python3 -c '
import json,sys
d=json.load(sys.stdin); n={o["id"]:o["info"]["props"].get("node.name","") for o in d if o["type"].endswith("Node")}
links=[(n.get(o["info"]["output-node-id"],""), n.get(o["info"]["input-node-id"],"")) for o in d if o["type"].endswith("Link")]
sys.exit(0 if any(a=="verify-tone" and b.endswith("HiFi__Speaker__sink") for a,b in links) else 1)'; then ok "audio flows app -> Speaker (the DSP runs inside it)"; else fail "the test stream did not reach Speaker (wpctl status; pw-dump links)"; fi
    wait
    [[ -n $sink ]] && wpctl set-mute "$sink" "$was_muted"
fi
pgrep -x easyeffects >/dev/null && fail "easyeffects still running (legacy)" || ok "no EasyEffects process"

exit $rc
