# Skycom Amlogic STB MAC Changer - Step-by-Step Manual Process

This document describes the manual step-by-step terminal commands required to permanently change the MAC address of a Skycom Amlogic Set-Top Box (STB) without running the automated python wrapper script. 

If you prefer to perform each step yourself to observe the output at each layer, execute the following commands in sequence.

---

## Target Variables in Examples:
* **STB IP**: `192.168.1.108`
* **Target MAC (Uppercase)**: `D0:76:58:54:94:99`
* **Target MAC (Lowercase)**: `d0:76:58:54:94:99`

---

## Step 1: Establish ADB Root Session
On network-connected boxes, enabling root restarts the `adbd` daemon, which kills the TCP session. You must manually reconnect.

```bash
# Connect to the STB
adb connect 192.168.1.108:5555

# Restart ADB daemon as root
adb root

# Wait 3 seconds for the daemon to start, then reconnect
adb connect 192.168.1.108:5555

# Verify root status (should return "0")
adb shell id -u
```

---

## Step 2: Program Amlogic Secure Key Storage (`unifykeys`)
The hardware key manager registry (`unifykeys`) stores physical attributes like the MAC address. We write the target MAC directly to these registers:

```bash
# Set the target key register name to "mac"
adb shell "echo mac > /sys/class/unifykeys/name"

# Write the new MAC address (must be in uppercase)
adb shell "echo D0:76:58:54:94:99 > /sys/class/unifykeys/write"

# Verify that the registry has saved the new value
adb shell "echo mac > /sys/class/unifykeys/name && cat /sys/class/unifykeys/read"
```
*Expected output:* `D0:76:58:54:94:99`

---

## Step 3: Deploy Init Boot Hook Script
The device firmware is configured to run a shell script located at `/system/bin/adbcontroll.sh` as **root** during the system boot sequence. We overwrite this file to configure the network interfaces.

### 1. Remount the `/system` partition as read-write:
```bash
adb remount

# If "adb remount" fails, force remount the overlayfs partition directly:
adb shell "mount -o remount,rw /system"
```

### 2. Create the script:
Create a local file named `adbcontroll.sh` on your PC with the following content:
```bash
#!/system/bin/sh
# System boot hook to override physical MAC address and screen UI property on boot

target_mac=$(getprop ro.boot.mac)
if [ -n "$target_mac" ] && [ "$target_mac" != "unknown" ]; then
    lower_mac=$(echo "$target_mac" | tr '[:upper:]' '[:lower:]')
    ip link set eth0 down
    ip link set eth0 address "$lower_mac"
    ip link set eth0 up
    setprop dev.com.mft.ethmac "$lower_mac"
    echo "[adbcontroll] MAC overridden dynamically using U-Boot: $lower_mac"
else
    ip link set eth0 down
    ip link set eth0 address d0:76:58:54:94:99
    ip link set eth0 up
    setprop dev.com.mft.ethmac d0:76:58:54:94:99
    echo "[adbcontroll] MAC overridden using hardcoded fallback: d0:76:58:54:94:99"
fi
```

### 3. Transfer and set permissions on the STB:
```bash
# Push the script to temp storage
adb push adbcontroll.sh /data/local/tmp/adbcontroll.sh

# Copy it to the system binary location
adb shell "cp /data/local/tmp/adbcontroll.sh /system/bin/adbcontroll.sh"

# Grant execution permissions
adb shell "chmod 755 /system/bin/adbcontroll.sh"

# Clean up temp files
adb shell "rm /data/local/tmp/adbcontroll.sh"
```

---

## Step 4: Patch the U-Boot Environment Partition
The U-Boot bootloader passes `ro.boot.mac` to the kernel. We must dump the `/dev/block/env` partition, modify the variables, recalculate the CRC32 checksum, and write it back.

### 1. Dump the environment partition:
```bash
adb shell "dd if=/dev/block/env of=/data/local/tmp/env.img"
adb pull /data/local/tmp/env.img local_env.img
adb shell "rm /data/local/tmp/env.img"
```

### 2. Patch the partition image:
On your PC, run the python patcher to replace the original MAC address and modify the boot args macros:
```bash
python Patch-Env-Amlogic-SKYCOM.py local_env.img --new-mac D0:76:58:54:94:99 --output local_env_patched.img
```

### 3. Flash the patched image back to the partition:
```bash
adb push local_env_patched.img /data/local/tmp/env_patched.img
adb shell "dd if=/data/local/tmp/env_patched.img of=/dev/block/env"
adb shell "rm /data/local/tmp/env_patched.img"
```

---

## Step 5: Clear Launcher & TV App Session Cache
The apps store cached session tokens and device configurations mapped to the old MAC address. To force a new login handshake, delete these files:

```bash
adb shell "rm -f /data/data/com.timesglobal.launcher/shared_prefs/*"
adb shell "rm -f /data/data/com.timesglobal.livetv/shared_prefs/*"
```

---

## Step 6: Reboot and Verify
```bash
# Reboot the box
adb reboot

# Reconnect after reboot
adb connect 192.168.1.108:5555

# Verify all values read as the new target MAC:
adb shell "getprop dev.com.mft.ethmac"
adb shell "getprop ro.boot.mac"
adb shell "echo mac > /sys/class/unifykeys/name && cat /sys/class/unifykeys/read"
```
All commands should return the updated target MAC address `D0:76:58:54:94:99`.
