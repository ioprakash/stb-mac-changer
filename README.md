# STB MAC Changer Reference & Automation

This directory contains utility files and documentation to change the MAC address of an Android Set-Top Box (STB) with root access, specifically tested on **Allwinner H616/H313 (sun50iw9p1)** platform running **Android 10**.

---

## Device Information (Target Specs)
During inspection, the following hardware details were found on the connected STB:
*   **Model**: `NETTV-1000` (google/walley/eros-p1)
*   **Processor (SoC)**: Quad-Core ARM Cortex-A53 (Allwinner `sun50iw9p1` platform, `cupid` board)
*   **Android OS**: Android 10 (API level 29)
*   **RAM**: 2 GB
*   **Firmware Kernel**: `Linux version 4.9.170 #2 SMP PREEMPT CST 2024`
*   **Network Interfaces**:
    *   `eth0` (Ethernet) - Original MAC: `90:0e:b3:98:01:8d`
    *   `wlan0` (Wi-Fi) - Original MAC: `8c:ef:ab:d0:14:cd`

---

## Reference Manual Commands
Because the default `su` binary on this device's firmware is a legacy/basic build, it **does not support the `-c` flag** (e.g., `su -c "command"` fails with `invalid uid/gid`). Instead, all root commands must be passed to `su` via a standard input pipe (`echo "command" | su`).

### 1. Check Root Access
```bash
adb shell "echo 'id' | su"
```
*Expected Output:* `uid=0(root) gid=0(root) ...`

### 2. Check Device Network Interfaces & MACs
```bash
adb shell "ip link"
```
*Look for:* `link/ether XX:XX:XX:XX:XX:XX` under the `eth0` or `wlan0` section.

### 3. Read Boot / Kernel Arguments
```bash
adb shell "echo 'cat /proc/cmdline' | su"
```
*Look for:* `mac_addr=XX:XX:XX:XX:XX:XX` in the output, which shows what U-Boot passed to the kernel.

### 4. Temporary MAC Address Change (Reverts on Reboot)
To change the MAC address temporarily without saving it to system configurations:
```bash
# Bring the interface down
adb shell "echo 'ip link set eth0 down' | su"

# Set the new MAC address
adb shell "echo 'ip link set eth0 address 90:0e:b3:bc:42:fd' | su"

# Bring the interface back up
adb shell "echo 'ip link set eth0 up' | su"
```

### 5. Permanent MAC Address Change (Option A - Survives Reboot)
To change the MAC address permanently across reboots by updating the Android system settings database:
```bash
# Write new MAC address to global settings
adb shell "settings put global ethernet_mac_addr 90:0e:b3:bc:42:fd"

# Verify the setting database was updated
adb shell "settings get global ethernet_mac_addr"

# Reboot the STB to apply settings
adb reboot
```

---

## Automation Utility (`change_mac.py`)
`change_mac.py` is a Python 3 CLI script that automates the steps described above. It automatically locates the ADB binary, detects connected devices, validates MAC formatting, and applies changes.

### Requirements
- Python 3.x installed on your PC.
- ADB installed (the script automatically searches for it on your `PATH` or in `C:\adb\adb.exe`).

### Usage Instructions

Open your terminal/command prompt, navigate to this directory, and run the script:

#### 1. Show Help Menu
```bash
python change_mac.py --help
```

#### 2. Apply Both Temporary and Permanent Changes (Recommended)
This changes the MAC address of `eth0` instantly, updates the settings database, and automatically sends a reboot command:
```bash
python change_mac.py --mac 90:0e:b3:bc:42:fd --mode both --reboot
```

#### 3. Change MAC Address Temporarily Only (No Reboot)
```bash
python change_mac.py --mac 90:0e:b3:bc:42:fd --mode temp
```

#### 4. Change MAC Address Permanently Only (No Auto-Reboot)
```bash
python change_mac.py --mac 90:0e:b3:bc:42:fd --mode perm
```

#### 5. Change MAC Address on a Specific Interface
If your Ethernet interface has a different name (e.g., `eth1`):
```bash
python change_mac.py --mac 90:0e:b3:bc:42:fd -i eth1
```
