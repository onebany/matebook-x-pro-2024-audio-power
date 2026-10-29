#!/usr/bin/env python3
"""The three FourSemi FS2119 speaker amps (ACPI HWSP0001) set up the way Windows plays. Root; matebook-amps.service
runs it at boot and after every resume.

  amps.py algo|inbox    write the mode's plan unless the amps are in it already; the result goes to /run/matebook-amps
  amps.py status        the amps' mode, nothing written
  amps.py selftest      no hardware: the plans parse, and their modes tell apart from each other and from the BIOS setup

The BIOS leaves the tweeter amp 21-29 dB down. Windows' MultiPADriver writes ALGO (scenes 0 + 3, the gain it plays
at, with Huawei's SmartPA speaker protection running) or INBOX (scenes 2 + 3, its default without the Huawei APO).
ALGO measured +8.8 dB on the woofers and +8.2 dB on the tweeters over INBOX; the power guard at the end of the DSP
chain holds each group at what a full-scale sine gets in INBOX. The plans (amps-*.tsv) are the driver's .dat records
in the order of its ETW trace; every write is read back, as Windows does.
"""
import ctypes
import glob
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS = "/run/matebook-amps"
I2C_RDWR, I2C_M_RD = 0x0707, 0x0001
CHIPS = {"tweeter": (r"\_SB.PC00.I2C2", 0x69), "woofer0": (r"\_SB.PC00.I2C3", 0x6B), "woofer1": (r"\_SB.PC00.I2C3", 0x69)}
SIGNATURE = (0x11, 0x15, 0x39, 0x3A, 0x41)   # play state, gain, volume, tweeter level: BIOS, INBOX and ALGO differ here


class Msg(ctypes.Structure):
    _fields_ = [("addr", ctypes.c_uint16), ("flags", ctypes.c_uint16), ("len", ctypes.c_uint16),
                ("buf", ctypes.POINTER(ctypes.c_uint8))]


class RdWr(ctypes.Structure):
    _fields_ = [("msgs", ctypes.POINTER(Msg)), ("nmsgs", ctypes.c_uint32)]


libc = ctypes.CDLL(None, use_errno=True)


def xfer(fd, *msgs):
    arr = (Msg * len(msgs))(*msgs)
    if libc.ioctl(fd, I2C_RDWR, ctypes.byref(RdWr(arr, len(msgs)))) < 0:
        raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))


def read(fd, addr, reg, n=2):
    w, r = (ctypes.c_uint8 * 1)(reg), (ctypes.c_uint8 * n)()
    xfer(fd, Msg(addr, 0, 1, w), Msg(addr, I2C_M_RD, n, r))
    return int.from_bytes(bytes(r), "big")


def write(fd, addr, reg, val, n):
    b = (ctypes.c_uint8 * (n + 1))(reg, *val.to_bytes(n, "big"))
    xfer(fd, Msg(addr, 0, n + 1, b))


def plan(mode):
    path = next(p for p in (f"{HERE}/amps-{mode}.tsv", f"{HERE}/configs/amps-{mode}.tsv") if os.path.exists(p))
    rows = []
    for line in open(path):
        if line.strip() and not line.startswith("#"):
            chip, reg, n, val, delay = line.split()
            assert chip in CHIPS, chip
            rows.append((chip, int(reg, 16), int(n), int(val, 16), int(delay)))
    return rows


def signature(rows):
    """What a plan leaves in the signature registers: {(chip, reg): value}."""
    return {(c, r): v for c, r, n, v, d in rows if r in SIGNATURE}


def mode_of(regs):
    for m in ("algo", "inbox"):
        if all(regs.get(k) == v for k, v in signature(plan(m)).items()):
            return m
    return "other"


def open_amps():
    """fd per bus after the chip-id checks; at boot the I2C adapters may still be probing."""
    for _ in range(20):
        found = {}
        for d in glob.glob("/sys/bus/i2c/devices/i2c-*/firmware_node/path"):
            found[open(d).read().strip().replace("\\_SB_.", "\\_SB.")] = d.split("/")[-3]
        if all(acpi in found for acpi, _ in CHIPS.values()):
            break
        time.sleep(0.5)
    else:
        raise OSError(f"no I2C adapter for {sorted({a for a, _ in CHIPS.values()} - set(found))}")
    fds = {}
    for chip, (acpi, addr) in CHIPS.items():
        fd = fds.setdefault(acpi, os.open(f"/dev/{found[acpi]}", os.O_RDWR))
        if (cid := read(fd, addr, 0x03)) != 0x2019:
            raise OSError(f"{chip} at {found[acpi]} {addr:#x}: chip id {cid:#06x}, not an FS2119")
    return fds


def current(fds):
    return {(c, r): read(fds[CHIPS[c][0]], CHIPS[c][1], r) for c in CHIPS for r in SIGNATURE}


def apply(fds, mode):
    """The plan; a failed write stops the rest. Returns the read-back mismatches."""
    bad = 0
    for chip, reg, n, val, delay in plan(mode):
        fd, addr = fds[CHIPS[chip][0]], CHIPS[chip][1]
        write(fd, addr, reg, val, n)
        time.sleep(delay / 1000)
        got = read(fd, addr, reg, n)
        bad += got != val and not (reg == 0x10 and got == 0)   # the soft reset bit clears itself
    return bad


def selftest():
    a, i = plan("algo"), plan("inbox")
    assert (len(a), len(i)) == (159, 148), (len(a), len(i))
    # read from the amps after a cold boot (2026-10-29): the tweeter at 0x41 = 153F is the quiet one
    bios = {("tweeter", 0x11): 0x0300, ("tweeter", 0x15): 3, ("tweeter", 0x39): 0xF300, ("tweeter", 0x3A): 0xF300,
            ("tweeter", 0x41): 0x153F}
    for w in ("woofer0", "woofer1"):
        bios.update({(w, 0x11): 0x0300, (w, 0x15): 3, (w, 0x39): 0xEE00, (w, 0x3A): 0xEE00, (w, 0x41): 0x053F})
    assert mode_of(bios) == "other"
    for m in ("algo", "inbox"):
        assert mode_of({**bios, **signature(plan(m))}) == m, m
    print("amps selftest OK")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "selftest":
        return selftest()
    assert cmd in ("status", "algo", "inbox"), f"unknown mode {cmd}"
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        fds = open_amps()
        was = mode_of(current(fds))
        if cmd == "status":
            return print(was)
        if was == cmd:
            msg = f"{cmd}: already set, {stamp}"
        else:
            bad = apply(fds, cmd)
            ok = bad == 0 and mode_of(current(fds)) == cmd
            msg = f"{cmd if ok else 'FAILED ' + cmd}: written over {was}, {bad} read-back mismatches, {stamp}"
    except OSError as e:
        msg = f"FAILED {cmd}: {e}, {stamp}"
    if cmd != "status":
        open(STATUS, "w").write(msg + "\n")
    print(msg)
    sys.exit(msg.startswith("FAILED"))


if __name__ == "__main__":
    main()
