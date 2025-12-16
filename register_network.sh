#!/bin/bash

# Script to register a new WiFi network for ROS2 Robot
# This allows you to configure additional networks on the same adapter

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  WiFi Network Registration Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run with sudo${NC}"
    echo "Usage: sudo $0"
    exit 1
fi

# Show available WiFi interfaces
echo -e "${GREEN}Available WiFi interfaces:${NC}"
nmcli device status | grep wifi
echo ""

# Get interface selection
echo -e "${YELLOW}Enter the WiFi interface to use (e.g., wlan0, wlan1):${NC}"
read -p "Interface: " INTERFACE

# Validate interface exists
if ! ip link show "$INTERFACE" &> /dev/null; then
    echo -e "${RED}Error: Interface $INTERFACE does not exist${NC}"
    exit 1
fi

# Get network SSID
echo ""
echo -e "${YELLOW}Enter the WiFi network SSID (network name):${NC}"
read -p "SSID: " SSID

if [ -z "$SSID" ]; then
    echo -e "${RED}Error: SSID cannot be empty${NC}"
    exit 1
fi

# Get password
echo ""
echo -e "${YELLOW}Enter the WiFi password:${NC}"
read -s -p "Password: " PASSWORD
echo ""

if [ -z "$PASSWORD" ]; then
    echo -e "${RED}Error: Password cannot be empty${NC}"
    exit 1
fi

# Ask for autoconnect preference
echo ""
echo -e "${YELLOW}Should this network auto-connect? (yes/no):${NC}"
read -p "Auto-connect: " AUTOCONNECT

if [[ "$AUTOCONNECT" =~ ^[Yy] ]]; then
    AUTOCONNECT_FLAG="yes"
else
    AUTOCONNECT_FLAG="no"
fi

# Ask for connection priority
echo ""
echo -e "${YELLOW}Enter connection priority (higher number = higher priority, default: 0):${NC}"
read -p "Priority: " PRIORITY

if [ -z "$PRIORITY" ]; then
    PRIORITY=0
fi

# Create the connection
echo ""
echo -e "${BLUE}Creating WiFi connection...${NC}"

nmcli connection add \
    type wifi \
    con-name "$SSID" \
    ifname "$INTERFACE" \
    ssid "$SSID" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "$PASSWORD" \
    connection.autoconnect "$AUTOCONNECT_FLAG" \
    connection.autoconnect-priority "$PRIORITY"

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✓ Successfully registered network '$SSID' on interface $INTERFACE${NC}"
    echo ""
    echo -e "${BLUE}Connection details:${NC}"
    echo "  SSID: $SSID"
    echo "  Interface: $INTERFACE"
    echo "  Auto-connect: $AUTOCONNECT_FLAG"
    echo "  Priority: $PRIORITY"
    echo ""
    echo -e "${YELLOW}To connect now, run:${NC}"
    echo "  nmcli connection up \"$SSID\""
    echo ""
    echo -e "${YELLOW}To list all connections:${NC}"
    echo "  nmcli connection show"
    echo ""
    echo -e "${YELLOW}To delete this connection:${NC}"
    echo "  nmcli connection delete \"$SSID\""
else
    echo -e "${RED}✗ Failed to create network connection${NC}"
    exit 1
fi
