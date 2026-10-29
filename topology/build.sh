#!/usr/bin/env bash
# Rebuild configs/sof-hda-generic-ace1-4ch-spk4.tplg:
#   ./topology/build.sh <sof source tree, tag v2.15>      (github.com/thesofproject/sof)
# The stock sof-hda-generic-ace1-4ch target (defines from tools/topology/topology2/production/
# tplg-targets-hda-generic.cmake) plus spk4.patch: HDA Analog playback in 4 channels, FL FR to
# DAC 0x23 (woofers), RL RR to DAC 0x22 (tweeters). Capture of the same link is 4 channels too:
# the kernel fixes up the link's channels from the last copier with its name, the capture one.
# Needs alsatplg >= 1.2.7 with the nhlt plugin (alsa-utils).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
sof=$(cd "${1:?usage: $0 <sof v2.15 source tree>}" && pwd)
w=$(mktemp -d); trap 'rm -rf "$w"' EXIT
cp -a "$sof/tools/topology/topology2" "$w/"
patch -s -d "$w/topology2" -p1 < "$here/spk4.patch"
"$sof/tools/topology/topology2/get_abi.sh" "$sof" ipc4 > "$w/abi.conf"
cat "$w/abi.conf" "$w/topology2/sof-hda-generic.conf" > "$w/spk4.conf"
defs=PLATFORM=mtl,HDA_CONFIG=mix,NUM_DMICS=4,PDM1_MIC_A_ENABLE=1,PDM1_MIC_B_ENABLE=1,PREPROCESS_PLUGINS=nhlt
defs+=,NHLT_BIN=nhlt-sof-hda-generic-ace1-4ch.bin,DMIC0_ENHANCED_CAPTURE=true
defs+=,EFX_DMIC0_TDFB_PARAMS=line4_pass,EFX_DMIC0_DRC_PARAMS=dmic_default
(cd "$w" && ALSA_CONFIG_DIR="$w/topology2" alsatplg -I "$w/topology2/" -D "$defs" -p -c spk4.conf -o spk4.tplg >/dev/null)
install -m644 "$w/spk4.tplg" "$here/../configs/sof-hda-generic-ace1-4ch-spk4.tplg"
echo "configs/sof-hda-generic-ace1-4ch-spk4.tplg rebuilt"
