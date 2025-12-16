# WiFi Network Management Scripts

These scripts help you register and manage WiFi networks on your ROS2 Robot.

## Scripts Overview

### 1. `register_network.sh` - Interactive Network Registration
**Purpose**: Interactively register a new WiFi network

**Usage**:
```bash
sudo ./register_network.sh
```

**Features**:
- Prompts for WiFi interface (wlan0, wlan1, etc.)
- Asks for SSID and password
- Configure auto-connect and priority settings
- User-friendly with colored output

---

### 2. `register_network_quick.sh` - Quick Network Registration
**Purpose**: Non-interactive network registration (good for scripts/automation)

**Usage**:
```bash
sudo ./register_network_quick.sh <interface> <ssid> <password> [autoconnect] [priority]
```

**Examples**:
```bash
# Register network without auto-connect
sudo ./register_network_quick.sh wlan0 "HomeWiFi" "mypassword123"

# Register network with auto-connect and priority 10
sudo ./register_network_quick.sh wlan0 "HomeWiFi" "mypassword123" yes 10

# Register on wlan1 interface
sudo ./register_network_quick.sh wlan1 "ROS2-Robot-Backup" "robotpass" yes 5
```

**Arguments**:
- `interface`: WiFi interface (wlan0, wlan1)
- `ssid`: Network name
- `password`: WiFi password
- `autoconnect`: Optional, yes/no (default: no)
- `priority`: Optional, number (higher = higher priority, default: 0)

---

### 3. `manage_networks.sh` - Network Management Menu
**Purpose**: Interactive menu to manage all WiFi networks

**Usage**:
```bash
./manage_networks.sh
```

**Features**:
1. List all WiFi connections
2. Show active connections
3. Connect to a network
4. Disconnect from a network
5. Delete a network
6. Scan for available networks
7. Show network details

---

## Common Tasks

### Register a new network for the same adapter as ROS2-Robot

Currently, ROS2-Robot is on **wlan0**. To add another network on the same interface:

```bash
sudo ./register_network.sh
# Then select: wlan0
# Enter your new network SSID and password
```

Or use the quick version:
```bash
sudo ./register_network_quick.sh wlan0 "NewNetwork" "newpassword" yes 0
```

### Connect to a different network

```bash
./manage_networks.sh
# Select option 3 (Connect to a network)
# Enter the network name
```

Or directly:
```bash
nmcli connection up "NetworkName"
```

### List all configured networks

```bash
nmcli connection show
```

### Check which network is currently active

```bash
nmcli connection show --active
```

### Set connection priority

Higher priority networks are preferred when multiple networks are available:

```bash
# Set high priority (prefer this network)
nmcli connection modify "NetworkName" connection.autoconnect-priority 100

# Set low priority
nmcli connection modify "NetworkName" connection.autoconnect-priority 0
```

### Enable/disable auto-connect

```bash
# Enable auto-connect
nmcli connection modify "NetworkName" connection.autoconnect yes

# Disable auto-connect
nmcli connection modify "NetworkName" connection.autoconnect no
```

---

## Current Network Configuration

Based on your system:
- **wlan0**: Currently has "ROS2-Robot" and "BlackHole"
- **wlan1**: Currently has "ROS2-Robot 1" (active)

---

## Troubleshooting

### Permission denied
Make sure to run with `sudo` for registration/modification:
```bash
sudo ./register_network.sh
```

### Can't find interface
List available interfaces:
```bash
nmcli device status
```

### Connection fails
Check if network is in range:
```bash
nmcli device wifi list
```

### Remove duplicate/old connections
```bash
nmcli connection delete "OldNetworkName"
```

---

## Notes

- All scripts use NetworkManager (nmcli) which is standard on Raspberry Pi OS
- Networks are stored in `/etc/NetworkManager/system-connections/`
- You can have multiple networks configured on the same interface
- The system will auto-connect to the highest priority network in range
