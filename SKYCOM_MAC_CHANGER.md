# Skycom Amlogic STB Permanent MAC Changer

This guide explains how to use the automated python script [change_mac_final.py](file:///d:/code/stb_mac_changer_project/change_mac_final.py) to permanently change the MAC address of a Skycom Amlogic Set-Top Box (STB) with root access.

The script is self-contained and handles all levels of modification required to make the change persistent across reboots, factory resets (except partition reflashing), and launcher updates.

---

## How It Works

The script patches the device at three distinct levels to ensure absolute persistence:

1. **Hardware Secure Storage (Unifykeys)**:
   Amlogic devices use a secure non-volatile storage partition called `unifykeys`. The Skycom Launcher reads the MAC directly from `/sys/class/unifykeys/read`. The script writes the target MAC directly to these registers:
   ```bash
   echo mac > /sys/class/unifykeys/name
   echo <MAC_ADDRESS> > /sys/class/unifykeys/write
   ```
   This survives cold reboots natively.

2. **U-Boot Environment Partition**:
   The script dumps the bootloader environment partition `/dev/block/env`, replaces all occurrences of the old MAC, patches the bootloader macros `cmdline_keys` and `storeargs` to bypass eFuse logic, recalculates the U-Boot environment CRC32 checksum, and flashes the patched image back to the partition. This ensures `ro.boot.mac` and `androidboot.mac` are correctly populated on boot.

3. **System Boot Hook Script (`adbcontroll.sh`)**:
   The device firmware includes an built-in init service that runs `/system/bin/adbcontroll.sh` as root upon boot completion. The script deploys a custom shell script to this location that dynamically overrides the MAC on the `eth0` network interface and sets the UI system property `dev.com.mft.ethmac` used by the launcher to display the MAC address.

---

## Prerequisites

1. **Python 3** installed on your computer.
2. **ADB (Android Debug Bridge)** installed and added to your system's PATH.
3. **STB Connection**: The target STB must have USB debugging / Network ADB enabled and be reachable via network or USB.
4. **Root Access**: The STB must have a `userdebug` or rooted build (allows running `su` or `adb root`).

---

## Usage Instructions

### 1. Run the Script
Open a terminal in this directory and execute the script with the desired target MAC address:

```bash
# If the STB is connected over USB:
python change_mac_final.py --mac D0:76:58:54:93:99 --reboot

# If the STB is on the network (e.g., at IP 192.168.1.108):
python change_mac_final.py --ip 192.168.1.108 --mac D0:76:58:54:93:99 --reboot
```

### 2. Options
* `--mac`: **[Required]** The target MAC address to apply (format: `D0:76:58:54:93:99` or `d07658549399`).
* `--ip`: **[Optional]** The IP address of the STB to connect via Network ADB before applying changes.
* `--skip-uboot`: **[Optional]** Skips dumping and patching the physical bootloader environment partition.
* `--reboot`: **[Optional]** Automatically triggers a device reboot once the setup finishes.

---

## Post-Run Verification

Once the STB reboots, you can verify the settings by running:

```bash
# 1. Verify the network interface has the new MAC address:
adb shell ip link show eth0

# 2. Verify the system properties match:
adb shell getprop dev.com.mft.ethmac
adb shell getprop ro.boot.mac

# 3. Verify the hardware unifykeys storage:
adb shell "echo mac > /sys/class/unifykeys/name && cat /sys/class/unifykeys/read"
```
All commands should return the updated target MAC address (`d0:76:58:54:93:99`).
