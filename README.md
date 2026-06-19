# STB MAC Changer Reference & Automation

This repository contains utility scripts, reference configurations, and automated tools to permanently change the MAC address of Android Set-Top Boxes (STBs) with root access. It supports platforms running **Allwinner H616/H313 (sun50iw9p1)** and **Amlogic (Skycom)**.

---

## Supported Devices

1. **Allwinner STBs (e.g. NETTV-1000)**
   * **SoC**: Quad-Core ARM Cortex-A53 (Allwinner `sun50iw9p1` / `cupid` board)
   * **OS**: Android 10 (API level 29)
   * **Original MAC**: `90:0e:b3:98:01:8d`
   * **Documentation**: See standard instructions below.

2. **Amlogic Skycom STBs**
   * **Documentation**: Detailed technical guide in [SKYCOM_MAC_CHANGER.md](file:///d:/code/stb_mac_changer_project/SKYCOM_MAC_CHANGER.md) and step-by-step manual commands in [SKYCOM_MANUAL_STEPS.md](file:///d:/code/stb_mac_changer_project/SKYCOM_MANUAL_STEPS.md).
   * **Automated Script**: [Mac-Change-Amlogic-SKYCOM.py](file:///d:/code/stb_mac_changer_project/Mac-Change-Amlogic-SKYCOM.py).

---

## Amlogic Skycom STB Permanent MAC Changer (Quick Start)

For Amlogic-based Skycom STBs, the MAC address is locked at multiple layers (Hardware Unifykeys registers, U-Boot environment variables, and interface links). We have written a comprehensive, self-contained Python 3 script to automate the entire patching process:

### Usage:
```bash
# Connect the STB over network ADB and execute:
python Mac-Change-Amlogic-SKYCOM.py --ip 192.168.1.108 --mac D0:76:58:54:93:99 --reboot
```

For a detailed breakdown of how this is implemented, refer to [SKYCOM_MAC_CHANGER.md](file:///d:/code/stb_mac_changer_project/SKYCOM_MAC_CHANGER.md) or the manual step-by-step instructions in [SKYCOM_MANUAL_STEPS.md](file:///d:/code/stb_mac_changer_project/SKYCOM_MANUAL_STEPS.md).

---

## Allwinner STB Reference Manual Commands

Because the default `su` binary on some legacy Allwinner firmware does **not support the `-c` flag** (e.g., `su -c "command"` fails with `invalid uid/gid`), all root commands must be passed to `su` via standard input pipe (`echo "command" | su`).

### 1. Check Root Access
```bash
adb shell "echo 'id' | su"
```
*Expected Output:* `uid=0(root) gid=0(root) ...`

### 2. Check Device Network Interfaces & MACs
```bash
adb shell "ip link"
```

### 3. Read Boot / Kernel Arguments
```bash
adb shell "echo 'cat /proc/cmdline' | su"
```

### 4. Temporary MAC Address Change (Reverts on Reboot)
```bash
# Bring the interface down
adb shell "echo 'ip link set eth0 down' | su"

# Set the new MAC address
adb shell "echo 'ip link set eth0 address 90:0e:b3:bc:42:fd' | su"

# Bring the interface back up
adb shell "echo 'ip link set eth0 up' | su"
```

### 5. Permanent MAC Address Change (Option A - Survives Reboot)
```bash
# Write new MAC address to global settings
adb shell "settings put global ethernet_mac_addr 90:0e:b3:bc:42:fd"

# Verify the setting database was updated
adb shell "settings get global ethernet_mac_addr"

# Reboot the STB to apply settings
adb reboot
```

---

## Advanced Permanent MAC Changer Methods (For Allwinner STBs)

On Allwinner Set-Top Boxes, the MAC address is parsed by U-Boot during the boot sequence and injected into the Linux kernel cmdline. We can persist the MAC address using two methods:

### Method 1: Automatic Startup Script
This method keeps a startup shell script on the device that automatically runs on every boot and changes the MAC address before the network service configures it.

#### Setup Process:
1. Create a script named `init.macchanger.sh`:
   ```bash
   #!/system/bin/sh
   ip link set eth0 down
   ip link set eth0 address 90:0e:b3:bc:42:fd
   ip link set eth0 up
   ```
2. Copy this script to the device's `/data/local/tmp/` directory:
   ```bash
   adb push init.macchanger.sh /data/local/tmp/
   ```
3. Use root permissions to place it in the system initialization scripts directory (e.g., `/system/etc/init.d/` if supported, or register it as a service in `/vendor/etc/init/hw/init.sun50iw9p1.rc`):
   ```bash
   adb shell "echo 'cp /data/local/tmp/init.macchanger.sh /system/etc/init.d/99macchanger && chmod 755 /system/etc/init.d/99macchanger' | su"
   ```

---

### Method 2: U-Boot Env Partition Patching
The boot arguments (visible in `/proc/cmdline`) contain `mac_addr=90:0E:B3:98:01:8D`. This is read directly from the `env` partition (`/dev/block/mmcblk0p2`). 

This partition has a **CRC32 Checksum** header. If the checksum doesn't match the variables block, the bootloader resets the environment, causing a boot loop or entering recovery.

We have created an automated patcher script: [Patch-Env-Generic-SKYCOM.py](file:///D:/code/stb_mac_changer_project/Patch-Env-Generic-SKYCOM.py) to parse and recalculate this checksum.

#### Execution Process:
1. **Dump the Env Partition** from the STB:
   ```bash
   adb shell "echo 'dd if=/dev/block/mmcblk0p2 bs=1024 count=128' | su" > env.img
   ```
2. **Patch the MAC address** using `patch_env.py` on your PC:
   ```bash
    python Patch-Env-Generic-SKYCOM.py env.img --set mac_addr=90:0e:b3:bc:42:fd --output env_patched.img
   ```
3. **Push the patched image** back to the STB:
   ```bash
   adb push env_patched.img /data/local/tmp/env_patched.img
   ```
4. **Flash it** to the partition:
   ```bash
   adb shell "echo 'dd if=/data/local/tmp/env_patched.img of=/dev/block/mmcblk0p2' | su"
   ```
5. **Reboot the device**:
   ```bash
   adb reboot
   ```

---

## Automation Utilities

### 1. MAC Address Auto-Changer (`Mac-Change-Generic-SKYCOM.py`)
`Mac-Change-Generic-SKYCOM.py` is a Python 3 CLI script that automates the Android system settings and temporary changes for Allwinner devices.
* Usage: `python Mac-Change-Generic-SKYCOM.py --mac 90:0e:b3:bc:42:fd --mode both --reboot`

### 2. U-Boot env Patcher (`Patch-Env-Generic-SKYCOM.py` - Standard/Allwinner)
`Patch-Env-Generic-SKYCOM.py` handles standard U-Boot CRC32 checks and variable manipulation.
* Usage: `python Patch-Env-Generic-SKYCOM.py env.img --set mac_addr=90:0e:b3:bc:42:fd`

### 3. Amlogic U-Boot Patcher (`Patch-Env-Amlogic-SKYCOM.py` - Skycom/Amlogic)
`Patch-Env-Amlogic-SKYCOM.py` handles auto-detection of the 64KB environment block within the 8MB partition dump, and automatically patches the U-Boot `cmdline_keys` and `storeargs` macros to inject the new MAC address directly.
* Usage: `python Patch-Env-Amlogic-SKYCOM.py skycom_env.img --new-mac D0:76:58:54:93:99 --output skycom_env_patched.img`


