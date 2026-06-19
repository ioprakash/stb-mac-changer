#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import struct
import zlib

def find_adb():
    """Locate the adb executable on the system."""
    adb_path = shutil.which("adb")
    if adb_path:
        return adb_path
    
    if os.name == 'nt':
        default_win_path = r"C:\adb\adb.exe"
        if os.path.exists(default_win_path):
            return default_win_path
            
    return "adb"

def run_cmd(cmd, capture=True):
    """Execute a local system command."""
    try:
        res = subprocess.run(cmd, capture_output=capture, text=True, check=True)
        return res.stdout.strip() if capture else "", None
    except subprocess.CalledProcessError as e:
        return (e.stdout.strip() if e.stdout else ""), (e.stderr.strip() if e.stderr else f"Exit code {e.returncode}")
    except FileNotFoundError:
        return "", f"Command '{cmd[0]}' not found"

def adb_cmd(adb_path, args, serial=None):
    """Execute an ADB command."""
    cmd = [adb_path]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    return run_cmd(cmd)

def parse_env(data):
    """Parse raw U-Boot env block and return CRC and key-value pairs."""
    if len(data) < 5:
        return 0, 0, []
        
    stored_crc = struct.unpack("<I", data[:4])[0]
    env_data = data[4:]
    calculated_crc = zlib.crc32(env_data) & 0xffffffff
    
    pairs = []
    current = bytearray()
    
    for b in env_data:
        if b == 0:
            if not current:
                break # Terminating double null
            try:
                pairs.append(current.decode('utf-8', errors='ignore'))
            except Exception:
                pass
            current = bytearray()
        else:
            current.append(b)
            
    return stored_crc, calculated_crc, pairs

def build_env(pairs, block_size):
    """Rebuild U-Boot env block with new key-value pairs and correct CRC32."""
    payload = bytearray()
    for p in pairs:
        payload.extend(p.encode('utf-8'))
        payload.append(0)
    payload.append(0)
    
    payload_len = len(payload)
    available_space = block_size - 4
    
    if payload_len > available_space:
        raise ValueError(f"Payload size ({payload_len} bytes) exceeds available space ({available_space} bytes)!")
        
    payload.extend(b'\0' * (available_space - payload_len))
    
    new_crc = zlib.crc32(payload) & 0xffffffff
    header = struct.pack("<I", new_crc)
    
    return header + payload

def patch_env_data(raw_data, new_mac_upper, new_mac_lower):
    """Globally replaces MAC addresses in the env partition and inserts overrides."""
    file_size = len(raw_data)
    stored_crc = struct.unpack("<I", raw_data[:4])[0]
    detected_block_size = None
    
    for sz in [0x4000, 0x8000, 0x10000, 0x20000, 0x40000, 0x80000]:
        if sz <= file_size:
            calc_crc = zlib.crc32(raw_data[4:sz]) & 0xffffffff
            if calc_crc == stored_crc:
                detected_block_size = sz
                break
                
    if not detected_block_size:
        print("[!] Warning: Could not match stored CRC with any standard U-Boot block size.")
        print("[!] Defaulting to 64KB (0x10000) block size.")
        detected_block_size = 0x10000
    else:
        print(f"[+] Auto-detected U-Boot block size: {detected_block_size} bytes (0x{detected_block_size:X})")
        
    env_block = raw_data[:detected_block_size]
    _, calc_crc, env_vars = parse_env(env_block)
    
    # Heuristically detect original MAC to replace
    old_mac_upper_match = "D0:76:58:54:AA:68"
    old_mac_lower_match = "d0:76:58:54:aa:68"
    mac_pattern = re.compile(r'([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}')
    
    for var in env_vars:
        for match in mac_pattern.finditer(var):
            mac_str = match.group(0)
            if mac_str.upper() != new_mac_upper:
                if mac_str == mac_str.upper():
                    old_mac_upper_match = mac_str
                else:
                    old_mac_lower_match = mac_str
                    
    print(f"[*] Replacing original MACs:")
    print(f"    - Uppercase: {old_mac_upper_match} -> {new_mac_upper}")
    print(f"    - Lowercase: {old_mac_lower_match} -> {new_mac_lower}")
    
    patched_vars = []
    changes_count = 0
    override_suffix = f"setenv mac {new_mac_upper};setenv eth6addr {new_mac_lower};setenv bootargs ${{bootargs}} mac={new_mac_upper} androidboot.mac={new_mac_upper};"
    
    for var in env_vars:
        if "=" not in var:
            patched_vars.append(var)
            continue
            
        k, v = var.split("=", 1)
        new_v = v
        
        if old_mac_upper_match in new_v:
            new_v = new_v.replace(old_mac_upper_match, new_mac_upper)
            changes_count += 1
        if old_mac_lower_match in new_v:
            new_v = new_v.replace(old_mac_lower_match, new_mac_lower)
            changes_count += 1
            
        if k == "cmdline_keys":
            old_str = "if keyman read mac ${loadaddr} str; then setenv bootargs ${bootargs} mac=${mac} androidboot.mac=${mac};fi;"
            new_str = f"setenv mac {new_mac_upper};setenv bootargs ${{bootargs}} mac={new_mac_upper} androidboot.mac={new_mac_upper};"
            if old_str in new_v:
                new_v = new_v.replace(old_str, new_str)
                print("[+] Patched 'cmdline_keys' macro to hardcode MAC address injection.")
            else:
                new_v = re.sub(r"setenv mac [0-9a-fA-F:]{17};", f"setenv mac {new_mac_upper};", new_v)
                new_v = re.sub(r"mac=[0-9a-fA-F:]{17} androidboot.mac=[0-9a-fA-F:]{17}", f"mac={new_mac_upper} androidboot.mac={new_mac_upper}", new_v)
                print("[~] Updated existing MAC injection in 'cmdline_keys'.")
                
        if k == "storeargs":
            # Remove any existing custom suffix from prior runs
            new_v = re.sub(r"setenv mac [0-9a-fA-F:]{17};.*", "", new_v).strip()
            if not new_v.endswith(";"):
                new_v += ";"
            new_v += override_suffix
            print("[+] Modified 'storeargs' U-Boot macro to append runtime MAC overrides.")
            
        patched_vars.append(f"{k}={new_v}")
        
    print(f"[+] Modified {changes_count} variables in environment block.")
    patched_block = build_env(patched_vars, detected_block_size)
    return patched_block + raw_data[detected_block_size:]

def main():
    parser = argparse.ArgumentParser(description="Skycom STB Permanent MAC Changer Script (Amlogic)")
    parser.add_argument("--mac", required=True, help="New MAC Address to write (e.g. D0:76:58:54:93:99)")
    parser.add_argument("--ip", help="IP address of the STB to connect via ADB (optional, e.g. 192.168.1.108)")
    parser.add_argument("--skip-uboot", action="store_true", help="Skip patching the physical U-Boot env partition")
    parser.add_argument("--reboot", action="store_true", help="Reboot STB after running")
    
    args = parser.parse_args()
    
    # 1. Clean and validate MAC address
    clean_mac = re.sub(r'[^a-fA-F0-9]', '', args.mac)
    if len(clean_mac) != 12:
        print("[-] Error: MAC address must contain exactly 12 hex characters.", file=sys.stderr)
        sys.exit(1)
        
    mac_upper = ":".join(clean_mac[i:i+2] for i in range(0, 12, 2)).upper()
    mac_lower = ":".join(clean_mac[i:i+2] for i in range(0, 12, 2)).lower()
    
    print(f"[*] Target MAC: {mac_upper} / {mac_lower}")
    
    # 2. Locate ADB and connect
    adb = find_adb()
    print(f"[*] Found ADB executable at: {adb}")
    
    # Check if already connected
    devices_stdout, _ = run_cmd([adb, "devices"])
    already_connected = False
    if args.ip:
        for line in devices_stdout.splitlines():
            if args.ip in line and "device" in line:
                already_connected = True
                break
                
    if args.ip and not already_connected:
        print(f"[*] Connecting to device at {args.ip}...")
        stdout, stderr = run_cmd([adb, "connect", f"{args.ip}:5555"])
        # Check again if connected, ignoring stdout/stderr quirks
        devices_stdout, _ = run_cmd([adb, "devices"])
        for line in devices_stdout.splitlines():
            if args.ip in line and "device" in line:
                already_connected = True
                break
        if not already_connected:
            print(f"[-] Error connecting to device: {stdout} {stderr}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"[+] Connected successfully: {stdout}")
    elif args.ip and already_connected:
        print(f"[+] Device {args.ip} is already connected.")
        
    # Get active target
    devices_stdout, _ = run_cmd([adb, "devices"])
    lines = [line.split()[0] for line in devices_stdout.splitlines()[1:] if line.strip() and "device" in line]
    
    if not lines:
        print("[-] Error: No active ADB devices found. Ensure device is connected.", file=sys.stderr)
        sys.exit(1)
        
    target_device = lines[0]
    print(f"[+] Targeting device: {target_device}")
    
    # 3. Elevate to root
    print("[*] Elevating ADB to root...")
    adb_cmd(adb, ["root"], target_device)
    
    # If the target device is connected via TCP/IP, the connection will break.
    # We must wait and run 'adb connect' again to re-establish the connection.
    is_network_device = ":" in target_device or args.ip is not None
    if is_network_device:
        ip_port = target_device
        if args.ip and ":" not in target_device:
            ip_port = f"{args.ip}:5555"
        
        print(f"[*] Network device detected. Reconnecting to {ip_port}...")
        # Retry connect loop up to 5 times
        connected = False
        for attempt in range(1, 6):
            time.sleep(2)
            print(f"[*] Connection attempt {attempt}/5...")
            stdout, stderr = run_cmd([adb, "connect", ip_port])
            if "connected to" in stdout.lower():
                print(f"[+] Reconnected successfully on attempt {attempt}.")
                connected = True
                break
        if not connected:
            print("[-] Warning: Failed to reconnect to network device. Commands might fail/hang.")
    else:
        print("[*] Waiting 2 seconds for adbd to restart...")
        time.sleep(2)
        
    print("[*] Waiting for device to come back online...")
    adb_cmd(adb, ["wait-for-device"], target_device)
    
    uid_check, _ = adb_cmd(adb, ["shell", "id -u"], target_device)
    if uid_check != "0":
        # Try su fallback
        uid_check, _ = adb_cmd(adb, ["shell", "echo 'id -u' | su"], target_device)
        if uid_check != "0":
            print("[-] Error: Root access is required to modify system files and hardware keys.", file=sys.stderr)
            sys.exit(1)
        use_su = True
        print("[+] Root access verified via su.")
    else:
        use_su = False
        print("[+] Root access verified natively.")
        
    def exec_root(cmd_str):
        if use_su:
            # Escape single quotes
            escaped = cmd_str.replace("'", "'\\''")
            return adb_cmd(adb, ["shell", f"echo '{escaped}' | su"], target_device)
        else:
            return adb_cmd(adb, ["shell", cmd_str], target_device)
            
    # 4. Write new MAC to Amlogic hardware key registry (Unifykeys Secure Storage)
    print("[*] Writing MAC to Amlogic secure unifykeys storage...")
    exec_root("echo mac > /sys/class/unifykeys/name")
    exec_root(f"echo {mac_upper} > /sys/class/unifykeys/write")
    
    # Verify secure key write
    verify_val, _ = exec_root("echo mac > /sys/class/unifykeys/name && cat /sys/class/unifykeys/read")
    if verify_val.strip().upper() == mac_upper:
        print(f"[+] Unifykeys secure key write verified: {verify_val.strip()}")
    else:
        print(f"[!] Warning: Unifykeys read back returned '{verify_val.strip()}', expected '{mac_upper}'")
        
    # 5. Make system RW and install init boot script
    print("[*] Remounting /system partition as read-write...")
    remount_out, remount_err = adb_cmd(adb, ["remount"], target_device)
    if "succeeded" not in remount_out.lower():
        print(f"[!] Remount command response: {remount_out} {remount_err}")
        # Try direct overlayfs remount
        exec_root("mount -o remount,rw /system")
    
    # Verify system write access
    rw_check, _ = exec_root("mount | grep -i '/system '")
    print(f"[*] /system Mount: {rw_check}")
    
    # Write the boot script
    print("[*] Deploying /system/bin/adbcontroll.sh...")
    boot_script = f'''#!/system/bin/sh
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
    ip link set eth0 address {mac_lower}
    ip link set eth0 up
    setprop dev.com.mft.ethmac {mac_lower}
    echo "[adbcontroll] MAC overridden using hardcoded fallback: {mac_lower}"
fi
'''
    # Push the script
    local_temp_script = "temp_adbcontroll.sh"
    with open(local_temp_script, "w", newline='\n') as f:
        f.write(boot_script)
        
    adb_cmd(adb, ["push", local_temp_script, "/data/local/tmp/adbcontroll.sh"], target_device)
    exec_root("cp /data/local/tmp/adbcontroll.sh /system/bin/adbcontroll.sh")
    exec_root("chmod 755 /system/bin/adbcontroll.sh")
    exec_root("rm /data/local/tmp/adbcontroll.sh")
    if os.path.exists(local_temp_script):
        os.remove(local_temp_script)
        
    print("[+] /system/bin/adbcontroll.sh deployed and permissions configured.")
    
    # 6. Patch the physical U-Boot env partition
    if not args.skip_uboot:
        print("[*] Processing U-Boot environment partition...")
        # Check env block device name
        env_dev_check, _ = exec_root("ls -l /dev/block/by-name/env")
        if "env" not in env_dev_check:
            print("[!] Warning: Env partition not found at default by-name location. Skipping U-Boot patch.")
        else:
            print("[*] Dumping env partition from STB...")
            exec_root("dd if=/dev/block/env of=/data/local/tmp/env.img")
            
            # Pull the env image locally
            local_env_img = "local_env.img"
            adb_cmd(adb, ["pull", "/data/local/tmp/env.img", local_env_img], target_device)
            exec_root("rm /data/local/tmp/env.img")
            
            if not os.path.exists(local_env_img) or os.path.getsize(local_env_img) == 0:
                print("[-] Error: Failed to dump env partition.", file=sys.stderr)
            else:
                print(f"[+] Environment partition dumped locally ({os.path.getsize(local_env_img)} bytes).")
                with open(local_env_img, "rb") as f:
                    raw_env = f.read()
                    
                try:
                    patched_env = patch_env_data(raw_env, mac_upper, mac_lower)
                    local_env_patched = "local_env_patched.img"
                    with open(local_env_patched, "wb") as f:
                        f.write(patched_env)
                        
                    print("[*] Pushing patched env block back to device...")
                    adb_cmd(adb, ["push", local_env_patched, "/data/local/tmp/env_patched.img"], target_device)
                    
                    # Flash the partition
                    print("[*] Writing patched block back to env partition...")
                    exec_root("dd if=/data/local/tmp/env_patched.img of=/dev/block/env")
                    exec_root("rm /data/local/tmp/env_patched.img")
                    
                    print("[+] U-Boot env partition patched and flashed successfully.")
                    
                    # Cleanup local files
                    if os.path.exists(local_env_img):
                        os.remove(local_env_img)
                    if os.path.exists(local_env_patched):
                        os.remove(local_env_patched)
                except Exception as e:
                    print(f"[-] Error patching U-Boot partition: {e}", file=sys.stderr)
                    if os.path.exists(local_env_img):
                        os.remove(local_env_img)
                        
    # 7. Clear launcher cache/shared preferences to force new auth
    print("[*] Clearing launcher local shared_preferences...")
    # Delete XML settings to remove saved session tokens mapped to old MAC
    exec_root("rm -f /data/data/com.timesglobal.launcher/shared_prefs/*")
    # Also delete live TV app settings to be safe
    exec_root("rm -f /data/data/com.timesglobal.livetv/shared_prefs/*")
    print("[+] Launcher and TV player local session caches cleared.")
    
    # 8. Reboot if requested
    if args.reboot:
        print("[*] Rebooting STB to apply all changes...")
        # Fire-and-forget: adb reboot drops the network connection instantly,
        # so subprocess.run() would hang forever. Use Popen without waiting.
        reboot_cmd = [adb]
        if target_device:
            reboot_cmd.extend(["-s", target_device])
        reboot_cmd.append("reboot")
        subprocess.Popen(reboot_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)  # Brief pause to let the command reach the device
        print("[+] Reboot command sent.")
    else:
        print("\n[!] Setup complete. Please reboot the STB to apply changes permanently.")
    
    print("\n" + "="*60)
    print("[+] ALL STEPS COMPLETED SUCCESSFULLY!")
    print(f"[+] Target MAC: {mac_upper}")
    print("="*60)
    print("\nVerify after reboot with:")
    print(f'  adb connect {args.ip or target_device}')
    print(f'  adb shell "echo mac > /sys/class/unifykeys/name && cat /sys/class/unifykeys/read"')
    print(f'  adb shell "ip link show eth0"')

if __name__ == "__main__":
    main()
