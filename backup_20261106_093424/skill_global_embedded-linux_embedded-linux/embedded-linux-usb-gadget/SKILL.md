---
name: embedded-linux-usb-gadget
description: "Use when debugging USB gadget networking on embedded Linux."
version: 1.0.0
tags: [embedded, linux, usb, gadget, openwrt, networking, debugging]
---

# USB Gadget on Embedded Linux

Use when setting up or debugging USB gadget modes (ethernet, serial, mass storage) on embedded Linux devices running OpenWrt or similar distributions.

## Procedure

### Diagnose USB gadget ethernet

1. **Check if the interface exists and is UP:**
   ```bash
   ip addr show usb0
   ```
   Expected: `state UP` with an IP address (e.g., 192.168.42.1/24).

2. **Check if the interface is in a bridge:**
   ```bash
   ls /sys/class/net/br-lan/brif/
   ```
   - If directory doesn't exist → no bridge
   - If exists → check if usb0 is listed

3. **Check the network config (OpenWrt UCI):**
   ```bash
   uci get network.lan.ipaddr
   uci get network.lan.ifname
   ```
   If usb0 is in `network.lan.ifname`, it's part of the LAN bridge.

4. **Verify connectivity from PC:**
   ```bash
   # On PC, find the RNDIS/NCM interface
   ip addr show | grep -A5 'enx\|usb0'
   
   # Ping the device
   ping 192.168.42.1
   
   # SSH into device
   ssh root@192.168.42.1
   ```

## Pitfalls

- **Interface already has IP**: If usb0 has a static IP (e.g., 192.168.42.1), adding it to a bridge does nothing — one interface can't belong to two configs. Use the IP that already works, or reconfigure the interface first.
  
- **SSH from the device itself**: Running `ssh root@192.168.1.100` on the phone tries to connect to the phone's own loopback, not the PC. SSH should be run **from the PC**, targeting the device's IP.

- **Bridge creation fails silently**: If you add usb0 to `network.lan.ifname` but br-lan doesn't exist or fails to create, the network restart may appear to succeed but leave the interface unconfigured. Check `dmesg` for errors and verify with `ip addr show br-lan`.

- **DHCP pool collision**: Stock OpenWrt dhcp.lan pool is .100-.249. If you set lan.ipaddr=192.168.1.100, move the pool to .110-.249 to avoid collision:
  ```bash
  uci set dhcp.lan.start=110
  uci set dhcp.lan.limit=140
  uci commit dhcp
  /etc/init.d/dnsmasq restart
  ```

- **Root password required for SSH**: Dropbear (OpenWrt's SSH daemon) requires a root password. Set it on the device:
  ```bash
  passwd
  ```

## Kernel Config Fragments

When managing kernel config for custom embedded builds:

- **Document WHY**: Each config option should have a comment explaining why it's needed. Future maintainers need the reasoning, not just the symbol.

- **Track provenance**: If an option is deliberately withheld (e.g., vendor tree won't compile with it), document this with the commit hash or build log that proved it. Example:
  ```
  # CONFIG_MEMCG is not set
  # Vendor mm/ tree refused to compile (bisect f6613d1 → 3f840e6 kept build green)
  ```

- **Test incrementally**: When adding new config options, test one at a time. If the build fails, you know which option broke it. Don't add 10 options and then bisect.

- **Re-affirm critical options**: If a config option is already in the vendor defconfig but is critical for your use case, re-affirm it in your fragment with a comment. This prevents a defconfig change from silently dropping your capability.
