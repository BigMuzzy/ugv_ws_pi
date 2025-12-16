#!/bin/bash

# Quick WiFi network registration script (non-interactive)
# Usage: sudo ./register_network_quick.sh <interface> <ssid> <password> [autoconnect] [priority]
# Example: sudo ./register_network_quick.sh wlan0 "MyNetwork" "mypassword123" yes 10

set -e

# Check arguments
if [ $# -lt 3 ]; then
    echo "Usage: sudo $0 <interface> <ssid> <password> [autoconnect] [priority]"
    echo ""
    echo "Arguments:"
    echo "  interface    - WiFi interface (e.g., wlan0, wlan1)"
    echo "  ssid         - Network SSID (network name)"
    echo "  password     - WiFi password"
    echo "  autoconnect  - Optional: yes/no (default: no)"
    echo "  priority     - Optional: connection priority, higher = preferred (default: 0)"
    echo ""
    echo "Example:"
    echo "  sudo $0 wlan0 \"HomeNetwork\" \"password123\" yes 10"
    exit 1
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run with sudo"
    exit 1
fi

INTERFACE="$1"
SSID="$2"
PASSWORD="$3"
AUTOCONNECT="${4:-no}"
PRIORITY="${5:-0}"

# Validate interface exists
if ! ip link show "$INTERFACE" &> /dev/null; then
    echo "Error: Interface $INTERFACE does not exist"
    exit 1
fi

# Validate interface is WiFi
if ! nmcli device status | grep -q "^$INTERFACE.*wifi"; then
    echo "Error: $INTERFACE is not a WiFi interface"
    exit 1
fi

# Create the connection
echo "Creating WiFi connection for '$SSID' on $INTERFACE..."

nmcli connection add \
    type wifi \
    con-name "$SSID" \
    ifname "$INTERFACE" \
    ssid "$SSID" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$PASSWORD" \
    connection.autoconnect "$AUTOCONNECT" \
    connection.autoconnect-priority "$PRIORITY"

if [ $? -eq 0 ]; then
    echo "✓ Successfully registered network '$SSID'"
    echo ""
    echo "To connect: nmcli connection up \"$SSID\""
    echo "To list all: nmcli connection show"
    echo "To delete: nmcli connection delete \"$SSID\""
else
    echo "✗ Failed to create network connection"
    exit 1
fi
