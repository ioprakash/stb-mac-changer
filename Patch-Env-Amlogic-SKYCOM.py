#!/usr/bin/env python3
import argparse
import os
import re
import struct
import sys
import zlib

def parse_env(data):
    """Parse raw U-Boot env block and return CRC and key-value pairs."""
    if len(data) < 5:
        return 0, 0, []
        
    # First 4 bytes: Little-Endian CRC32
    stored_crc = struct.unpack("<I", data[:4])[0]
    env_data = data[4:]
    
    # Calculate CRC32 of the actual payload
    calculated_crc = zlib.crc32(env_data) & 0xffffffff
    
    # Parse null-separated strings
    pairs = []
    current = bytearray()
    
    for b in env_data:
        if b == 0:
            if not current:
                break # Double null byte indicates end
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
        payload.append(0) # Null separator
    payload.append(0) # Terminating double null
    
    payload_len = len(payload)
    available_space = block_size - 4 # Reserve 4 bytes for CRC
    
    if payload_len > available_space:
        raise ValueError(f"Payload size ({payload_len} bytes) exceeds available space ({available_space} bytes)!")
        
    payload.extend(b'\0' * (available_space - payload_len))
    
    # Calculate CRC32
    new_crc = zlib.crc32(payload) & 0xffffffff
    header = struct.pack("<I", new_crc)
    
    return header + payload

def main():
    parser = argparse.ArgumentParser(description="Amlogic STB U-Boot env Patcher (Globally replaces MAC addresses)")
    parser.add_argument("input_file", help="Path to the dumped env partition image (e.g. skycom_env.img)")
    parser.add_argument("-o", "--output", help="Path to write the patched image (default: skycom_env_patched.img)")
    parser.add_argument("--new-mac", required=True, help="New MAC address to write (e.g. D0:76:58:54:93:99)")
    parser.add_argument("--dump", action="store_true", help="Dump all variables and exit")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input_file):
        print(f"Error: Input file '{args.input_file}' not found.", file=sys.stderr)
        sys.exit(1)
        
    with open(args.input_file, "rb") as f:
        raw_data = f.read()
        
    file_size = len(raw_data)
    
    # 1. Parse and Auto-detect environment block size
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
    
    print(f"[*] Read '{args.input_file}' ({file_size} bytes total)")
    print(f"[*] Checksum: Stored = 0x{stored_crc:08X}, Calculated = 0x{calc_crc:08X}")
    
    # Format target MAC formats
    clean_new_mac = re.sub(r'[^a-fA-F0-9]', '', args.new_mac)
    if len(clean_new_mac) != 12:
        print("Error: New MAC address must contain 12 hex characters.", file=sys.stderr)
        sys.exit(1)
        
    new_mac_upper = ":".join(clean_new_mac[i:i+2] for i in range(0, 12, 2)).upper()
    new_mac_lower = ":".join(clean_new_mac[i:i+2] for i in range(0, 12, 2)).lower()
    
    print(f"[*] Target MAC Addresses:")
    print(f"    - Uppercase format: {new_mac_upper}")
    print(f"    - Lowercase format: {new_mac_lower}")
    
    # Find old MAC addresses in the env variables
    old_mac_upper_match = None
    old_mac_lower_match = None
    mac_pattern = re.compile(r'([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}')
    
    for var in env_vars:
        for match in mac_pattern.finditer(var):
            mac_str = match.group(0)
            if mac_str.upper() != new_mac_upper:
                if mac_str == mac_str.upper():
                    old_mac_upper_match = mac_str
                else:
                    old_mac_lower_match = mac_str
                    
    if not old_mac_upper_match:
        old_mac_upper_match = "D0:76:58:54:AA:68"
    if not old_mac_lower_match:
        old_mac_lower_match = "d0:76:58:54:aa:68"
        
    print(f"[*] Detected original MAC addresses to replace:")
    print(f"    - Uppercase pattern: {old_mac_upper_match}")
    print(f"    - Lowercase pattern: {old_mac_lower_match}")
    
    if args.dump:
        print("\n--- Current U-Boot Environment ---")
        for var in env_vars:
            print(var)
        print("----------------------------------")
        sys.exit(0)
        
    # 2. Globally replace all occurrences of old MACs and add U-Boot overrides
    patched_vars = []
    changes_count = 0
    
    # We will append U-Boot commands to override bootargs after cmdline_keys reads from eFuse/Keyman
    override_suffix = f"setenv mac {new_mac_upper};setenv eth6addr {new_mac_lower};setenv bootargs ${{bootargs}} mac={new_mac_upper} androidboot.mac={new_mac_upper};"
    
    for var in env_vars:
        if "=" not in var:
            patched_vars.append(var)
            continue
            
        k, v = var.split("=", 1)
        new_v = v
        
        # Globally replace MAC strings in value
        if old_mac_upper_match in new_v:
            new_v = new_v.replace(old_mac_upper_match, new_mac_upper)
            changes_count += 1
        if old_mac_lower_match in new_v:
            new_v = new_v.replace(old_mac_lower_match, new_mac_lower)
            changes_count += 1
            
        # Specific override for cmdline_keys to bypass keyman reading of MAC
        if k == "cmdline_keys":
            old_str = "if keyman read mac ${loadaddr} str; then setenv bootargs ${bootargs} mac=${mac} androidboot.mac=${mac};fi;"
            new_str = f"setenv mac {new_mac_upper};setenv bootargs ${{bootargs}} mac={new_mac_upper} androidboot.mac={new_mac_upper};"
            if old_str in new_v:
                new_v = new_v.replace(old_str, new_str)
                print("[+] Patched 'cmdline_keys' to inject new MAC address directly.")
            else:
                # If already modified, do a simple regex/replace of the values inside
                new_v = re.sub(r"setenv mac [0-9a-fA-F:]{17};", f"setenv mac {new_mac_upper};", new_v)
                new_v = re.sub(r"mac=[0-9a-fA-F:]{17} androidboot.mac=[0-9a-fA-F:]{17}", f"mac={new_mac_upper} androidboot.mac={new_mac_upper}", new_v)
                print("[~] Updated existing MAC injection in 'cmdline_keys'.")
            
        # Specific override for storeargs to bypass eFuse keyman MAC logic
        if k == "storeargs":
            # Strip existing override if we ran the script before
            new_v = re.sub(r"setenv mac [0-9a-fA-F:]{17};.*", "", new_v)
            new_v = new_v.strip()
            # Ensure it ends with semicolon
            if not new_v.endswith(";"):
                new_v += ";"
            # Append the runtime setenv override
            new_v += override_suffix
            print(f"[+] Modified 'storeargs' U-Boot macro to append runtime MAC overrides.")
            
        patched_vars.append(f"{k}={new_v}")
        
    print(f"[+] Replaced MAC occurrences in {changes_count} variables.")
    
    # 3. Build patched block
    patched_block = build_env(patched_vars, detected_block_size)
    patched_full = patched_block + raw_data[detected_block_size:]
    
    output_path = args.output if args.output else "skycom_env_patched.img"
    with open(output_path, "wb") as f:
        f.write(patched_full)
        
    _, new_calc, _ = parse_env(patched_block)
    print(f"\n[+] Patched image written to '{output_path}'")
    print(f"[+] New Environment CRC32 Checksum: 0x{new_calc:08X}")
    print("\n--- Instructions to Apply to Skycom STB ---\n")
    print("1. Push the patched image back to the device:")
    print(f"   adb push {output_path} /data/local/tmp/env_patched.img")
    print("2. Write it directly back to the env partition using root:")
    print("   adb shell \"echo 'dd if=/data/local/tmp/env_patched.img of=/dev/block/env' | su\"")
    print("3. Reboot the device:")
    print("   adb reboot")

if __name__ == "__main__":
    main()
