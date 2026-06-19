#!/system/bin/sh
# System boot hook to override physical MAC address and screen UI property on boot

target_mac=$(getprop ro.boot.mac)
if [ -n "$target_mac" ] && [ "$target_mac" != "unknown" ]; then
    # Format target MAC as lowercase for interface matching
    lower_mac=$(echo "$target_mac" | tr '[:upper:]' '[:lower:]')
    ip link set eth0 down
    ip link set eth0 address "$lower_mac"
    ip link set eth0 up
    setprop dev.com.mft.ethmac "$lower_mac"
    echo "[adbcontroll] MAC overridden dynamically using U-Boot: $lower_mac"
else
    # Fallback to default target MAC if property is missing
    ip link set eth0 down
    ip link set eth0 address d0:76:58:54:93:99
    ip link set eth0 up
    setprop dev.com.mft.ethmac d0:76:58:54:93:99
    echo "[adbcontroll] MAC overridden using hardcoded fallback: d0:76:58:54:93:99"
fi
