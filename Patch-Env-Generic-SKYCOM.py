#!/usr/bin/env python3
import argparse
import os
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
    
    # U-Boot env is terminated by a double null byte \0\0
    # or runs until the end of the partition.
    for b in env_data:
        if b == 0:
            if not current:
                # Double null byte indicates end of variables
                break
            try:
                pairs.append(current.decode('utf-8', errors='ignore'))
            except Exception:
                pass
            current = bytearray()
        else:
            current.append(b)
            
    return stored_crc, calculated_crc, pairs

def build_env(pairs, total_size):
    """Rebuild U-Boot env block with new key-value pairs and correct CRC32."""
    payload = bytearray()
    for p in pairs:
        payload.extend(p.encode('utf-8'))
        payload.append(0) # Null separator
    payload.append(0) # Terminating double null
    
    # Pad the remaining block size with null bytes
    payload_len = len(payload)
    available_space = total_size - 4 # Reserve 4 bytes for CRC
    
    if payload_len > available_space:
        raise ValueError(f"Payload size ({payload_len} bytes) exceeds available partition space ({available_space} bytes)!")
        
    payload.extend(b'\0' * (available_space - payload_len))
    
    # Calculate CRC32 of the padded payload
    new_crc = zlib.crc32(payload) & 0xffffffff
    header = struct.pack("<I", new_crc)
    
    return header + payload

def main():
    parser = argparse.ArgumentParser(description="U-Boot env Partition Checksum & Variable Patcher")
    parser.add_argument("input_file", help="Path to the dumped env partition image (e.g. env.img)")
    parser.add_argument("-o", "--output", help="Path to write the patched image (default: env_patched.img)")
    parser.add_argument("--set", action="append", help="Set a variable in key=value format (can be specified multiple times)")
    parser.add_argument("--delete", action="append", help="Delete a variable by key name")
    parser.add_argument("--dump", action="store_true", help="Print all environment variables and exit")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input_file):
        print(f"Error: Input file '{args.input_file}' not found.", file=sys.stderr)
        sys.exit(1)
        
    with open(args.input_file, "rb") as f:
        raw_data = f.read()
        
    file_size = len(raw_data)
    stored_crc, calc_crc, env_vars = parse_env(raw_data)
    
    print(f"[*] Read '{args.input_file}' ({file_size} bytes)")
    print(f"[*] Stored Checksum   : 0x{stored_crc:08X}")
    print(f"[*] Calculated Checksum: 0x{calc_crc:08X}")
    
    if stored_crc != calc_crc:
        print("[!] Warning: Checksum mismatch! The partition dump might be corrupted or not a valid U-Boot env block.")
    else:
        print("[+] Checksum matches successfully.")
        
    # If dump requested, print variables and exit
    if args.dump or (not args.set and not args.delete):
        print("\n--- Current U-Boot Environment Variables ---")
        for var in env_vars:
            print(var)
        print("--------------------------------------------")
        if args.dump:
            sys.exit(0)
            
    # Modify environment variables
    modified_vars = []
    keys_to_set = {}
    
    if args.set:
        for s in args.set:
            if "=" not in s:
                print(f"Error: Invalid format for --set '{s}'. Must be key=value", file=sys.stderr)
                sys.exit(1)
            k, v = s.split("=", 1)
            keys_to_set[k.strip()] = v.strip()
            
    keys_to_delete = set(args.delete) if args.delete else set()
    
    # Update existing variables and filter out deleted ones
    seen_keys = set()
    for var in env_vars:
        if "=" in var:
            k, v = var.split("=", 1)
            k = k.strip()
            if k in keys_to_delete:
                print(f"[-] Deleting: {k}")
                continue
            if k in keys_to_set:
                print(f"[~] Updating: {k} -> {keys_to_set[k]}")
                modified_vars.append(f"{k}={keys_to_set[k]}")
                seen_keys.add(k)
            else:
                modified_vars.append(var)
                seen_keys.add(k)
        else:
            modified_vars.append(var)
            
    # Add new variables
    for k, v in keys_to_set.items():
        if k not in seen_keys:
            print(f"[+] Adding: {k}={v}")
            modified_vars.append(f"{k}={v}")
            
    # Rebuild the image
    try:
        patched_data = build_env(modified_vars, file_size)
    except Exception as e:
        print(f"Error rebuilding environment: {e}", file=sys.stderr)
        sys.exit(1)
        
    output_path = args.output if args.output else "env_patched.img"
    with open(output_path, "wb") as f:
        f.write(patched_data)
        
    # Recalculate checksum for confirmation
    new_stored, new_calc, _ = parse_env(patched_data)
    print(f"\n[+] Patched image written to '{output_path}'")
    print(f"[+] New Checksum: 0x{new_calc:08X}")
    print("\n--- Instructions to Apply ---\n")
    print("1. Push the patched image back to the device:")
    print(f"   adb push {output_path} /data/local/tmp/env_patched.img")
    print("2. Write it directly back to the env partition using root:")
    print("   adb shell \"echo 'dd if=/data/local/tmp/env_patched.img of=/dev/block/mmcblk0p2' | su\"")
    print("3. Reboot the device:")
    print("   adb reboot")

if __name__ == "__main__":
    main()
