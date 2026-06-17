#!/usr/bin/env python3
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

def find_adb():
    """Locate the adb executable on the system."""
    adb_path = shutil.which("adb")
    if adb_path:
        return adb_path
    
    # Common Windows installation directory fallback
    if os.name == 'nt':
        default_win_path = r"C:\adb\adb.exe"
        if os.path.exists(default_win_path):
            return default_win_path
            
    return "adb"

def run_adb_cmd(adb_path, args, device_serial=None):
    """Execute an ADB command and return stdout/stderr."""
    cmd = [adb_path]
    if device_serial:
        cmd.extend(["-s", device_serial])
    cmd.extend(args)
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip(), None
    except subprocess.CalledProcessError as e:
        return e.stdout.strip(), e.stderr.strip()
    except FileNotFoundError:
        return "", f"Error: '{adb_path}' executable not found. Please ensure ADB is installed and added to PATH."

def get_connected_devices(adb_path):
    """Retrieve list of connected ADB device serial numbers."""
    stdout, stderr = run_adb_cmd(adb_path, ["devices"])
    if stderr:
        print(f"Error checking devices: {stderr}", file=sys.stderr)
        return []
    
    devices = []
    lines = stdout.splitlines()
    for line in lines[1:]:  # skip header "List of devices attached"
        if line.strip():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
    return devices

def validate_and_format_mac(mac):
    """Validate and format a MAC address to XX:XX:XX:XX:XX:XX."""
    # Strip any common delimiters like colons, hyphens, spaces
    clean_mac = re.sub(r'[^a-fA-F0-9]', '', mac)
    if len(clean_mac) != 12:
        return None
    
    # Re-assemble with colons in lower case
    formatted_mac = ":".join(clean_mac[i:i+2] for i in range(0, 12, 2)).lower()
    return formatted_mac

def get_current_mac(adb_path, device_serial, interface):
    """Get the current MAC address of a network interface from the device."""
    stdout, stderr = run_adb_cmd(adb_path, ["shell", f"ip link show {interface}"], device_serial)
    if stderr:
        return None
    
    match = re.search(r"link/ether\s+([0-9a-fA-F:]{17})", stdout)
    if match:
        return match.group(1).lower()
    return None

def change_mac_temp(adb_path, device_serial, interface, mac):
    """Temporarily change the MAC address using ip link (reverts on reboot)."""
    # Build the piped root command block
    cmd_string = f"ip link set {interface} down && ip link set {interface} address {mac} && ip link set {interface} up"
    # Pipe commands into `su` because `su -c` is not supported on this firmware
    su_cmd = f"echo '{cmd_string}' | su"
    
    print(f"[*] Sending temporary MAC change commands to {interface} via root su...")
    stdout, stderr = run_adb_cmd(adb_path, ["shell", su_cmd], device_serial)
    
    if stderr:
        print(f"[-] Root execution error: {stderr}", file=sys.stderr)
        return False
        
    if stdout and "invalid" in stdout.lower():
        print(f"[-] Warning/Error from su shell: {stdout}", file=sys.stderr)
        return False
        
    return True

def change_mac_perm(adb_path, device_serial, mac):
    """Permanently write the MAC address to Android global settings database (Option A)."""
    settings_cmd = f"settings put global ethernet_mac_addr {mac}"
    su_cmd = f"echo '{settings_cmd}' | su"
    
    print("[*] Writing new MAC address to global system settings database...")
    stdout, stderr = run_adb_cmd(adb_path, ["shell", su_cmd], device_serial)
    
    if stderr:
        print(f"[-] Settings write error: {stderr}", file=sys.stderr)
        return False
        
    # Verify write
    verify_out, verify_err = run_adb_cmd(adb_path, ["shell", "settings get global ethernet_mac_addr"], device_serial)
    if verify_out == mac:
        print(f"[+] Successfully wrote settings database key: 'ethernet_mac_addr' -> '{mac}'")
        return True
    else:
        print(f"[-] Verification failed. Settings value: '{verify_out}'", file=sys.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description="Automate STB Android MAC Address Changer (Root required)")
    parser.add_argument("-m", "--mac", required=True, help="Target MAC address (e.g., 90:0e:b3:bc:42:fd)")
    parser.add_argument("--mode", choices=["temp", "perm", "both"], default="both", 
                        help="Mode: 'temp' (resets on reboot), 'perm' (global settings write), or 'both' (default)")
    parser.add_argument("-i", "--interface", default="eth0", help="Network interface name (default: eth0)")
    parser.add_argument("-r", "--reboot", action="store_true", help="Reboot STB after running (recommended for permanent changes)")
    parser.add_argument("-d", "--device", help="Specific ADB device serial number (if multiple devices are connected)")
    
    args = parser.parse_args()
    
    # 1. Format MAC
    mac = validate_and_format_mac(args.mac)
    if not mac:      
        print(f"Error: Invalid MAC address format '{args.mac}'. Must be 12 hex characters.", file=sys.stderr)
        sys.exit(1)
        
    print(f"[*] Target MAC Address configured: {mac}")
    
    # 2. Find ADB
    adb_path = find_adb()
    print(f"[*] Using ADB executable at: {adb_path}")
    
    # 3. Check Connected Devices
    devices = get_connected_devices(adb_path)
    if not devices:
        print("[-] Error: No ADB devices found. Ensure USB debugging is enabled and the device is connected.", file=sys.stderr)
        sys.exit(1)
        
    device_serial = args.device
    if not device_serial:
        if len(devices) == 1:
            device_serial = devices[0]
        else:
            print("[!] Multiple devices detected. Please select one:")
            for idx, dev in enumerate(devices):
                print(f"  {idx + 1}. {dev}")
            try:
                choice = int(input("Enter device number: ")) - 1
                if 0 <= choice < len(devices):
                    device_serial = devices[choice]
                else:
                    print("Error: Invalid selection.", file=sys.stderr)
                    sys.exit(1)
            except ValueError:
                print("Error: Please enter a valid number.", file=sys.stderr)
                sys.exit(1)
                
    print(f"[+] Targeting Device Serial: {device_serial}")
    
    # 4. Get Current MAC
    initial_mac = get_current_mac(adb_path, device_serial, args.interface)
    if initial_mac:
        print(f"[*] Current {args.interface} MAC address: {initial_mac}")
    else:
        print(f"[!] Warning: Could not read MAC address for interface '{args.interface}' (interface may be down or missing).")
        
    # 5. Apply Changes
    success = False
    
    if args.mode in ["temp", "both"]:
        temp_success = change_mac_temp(adb_path, device_serial, args.interface, mac)
        if temp_success:
            print("[+] Temporary MAC change command applied successfully.")
            success = True
        else:
            print("[-] Temporary MAC change command failed.", file=sys.stderr)
            
    if args.mode in ["perm", "both"]:
        perm_success = change_mac_perm(adb_path, device_serial, mac)
        if perm_success:
            print("[+] Permanent settings database change applied successfully.")
            success = True
        else:
            print("[-] Permanent settings database change failed.", file=sys.stderr)
            
    # 6. Verify Temporary Change
    if args.mode in ["temp", "both"] and success:
        time.sleep(1)  # wait for network link restart
        new_mac = get_current_mac(adb_path, device_serial, args.interface)
        if new_mac == mac:
            print(f"[++] Verification SUCCESS: Interface {args.interface} MAC is now {new_mac}")
        else:
            print(f"[--] Verification WARNING: Interface {args.interface} MAC reads as {new_mac} (expected {mac})")
            
    # 7. Reboot if requested
    if args.reboot:
        print("[*] Rebooting STB as requested...")
        run_adb_cmd(adb_path, ["reboot"], device_serial)
        print("[+] Device reboot command sent. Wait for device to boot up to check persistent MAC change.")

if __name__ == "__main__":
    main()
