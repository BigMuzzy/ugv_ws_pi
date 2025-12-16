#!/bin/bash

# WiFi Network Management Script
# Manage, list, connect, and remove WiFi networks

set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

show_menu() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  WiFi Network Management${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    echo "1) List all WiFi connections"
    echo "2) Show active connections"
    echo "3) Connect to a network"
    echo "4) Disconnect from a network"
    echo "5) Delete a network"
    echo "6) Scan for available networks"
    echo "7) Show network details"
    echo "8) Exit"
    echo ""
}

list_wifi_connections() {
    echo -e "${GREEN}WiFi Connections:${NC}"
    nmcli connection show | grep wifi
    echo ""
}

show_active() {
    echo -e "${GREEN}Active Connections:${NC}"
    nmcli connection show --active
    echo ""
}

connect_network() {
    echo -e "${YELLOW}Available WiFi connections:${NC}"
    nmcli connection show | grep wifi
    echo ""
    read -p "Enter connection name to connect: " CONN_NAME

    if [ -z "$CONN_NAME" ]; then
        echo -e "${RED}Error: Connection name cannot be empty${NC}"
        return
    fi

    echo -e "${BLUE}Connecting to '$CONN_NAME'...${NC}"
    if nmcli connection up "$CONN_NAME"; then
        echo -e "${GREEN}✓ Successfully connected to '$CONN_NAME'${NC}"
    else
        echo -e "${RED}✗ Failed to connect${NC}"
    fi
    echo ""
}

disconnect_network() {
    echo -e "${YELLOW}Active connections:${NC}"
    nmcli connection show --active
    echo ""
    read -p "Enter connection name to disconnect: " CONN_NAME

    if [ -z "$CONN_NAME" ]; then
        echo -e "${RED}Error: Connection name cannot be empty${NC}"
        return
    fi

    echo -e "${BLUE}Disconnecting from '$CONN_NAME'...${NC}"
    if nmcli connection down "$CONN_NAME"; then
        echo -e "${GREEN}✓ Successfully disconnected from '$CONN_NAME'${NC}"
    else
        echo -e "${RED}✗ Failed to disconnect${NC}"
    fi
    echo ""
}

delete_network() {
    echo -e "${YELLOW}WiFi connections:${NC}"
    nmcli connection show | grep wifi
    echo ""
    read -p "Enter connection name to delete: " CONN_NAME

    if [ -z "$CONN_NAME" ]; then
        echo -e "${RED}Error: Connection name cannot be empty${NC}"
        return
    fi

    read -p "Are you sure you want to delete '$CONN_NAME'? (yes/no): " CONFIRM
    if [[ "$CONFIRM" =~ ^[Yy] ]]; then
        echo -e "${BLUE}Deleting '$CONN_NAME'...${NC}"
        if sudo nmcli connection delete "$CONN_NAME"; then
            echo -e "${GREEN}✓ Successfully deleted '$CONN_NAME'${NC}"
        else
            echo -e "${RED}✗ Failed to delete${NC}"
        fi
    else
        echo "Cancelled."
    fi
    echo ""
}

scan_networks() {
    echo -e "${BLUE}Scanning for available networks...${NC}"
    echo ""
    echo -e "${GREEN}Available WiFi Networks:${NC}"
    nmcli device wifi list
    echo ""
}

show_details() {
    echo -e "${YELLOW}WiFi connections:${NC}"
    nmcli connection show | grep wifi
    echo ""
    read -p "Enter connection name to show details: " CONN_NAME

    if [ -z "$CONN_NAME" ]; then
        echo -e "${RED}Error: Connection name cannot be empty${NC}"
        return
    fi

    echo ""
    echo -e "${GREEN}Details for '$CONN_NAME':${NC}"
    nmcli connection show "$CONN_NAME"
    echo ""
}

# Main loop
while true; do
    show_menu
    read -p "Select an option (1-8): " choice
    echo ""

    case $choice in
        1) list_wifi_connections ;;
        2) show_active ;;
        3) connect_network ;;
        4) disconnect_network ;;
        5) delete_network ;;
        6) scan_networks ;;
        7) show_details ;;
        8) echo "Exiting..."; exit 0 ;;
        *) echo -e "${RED}Invalid option. Please select 1-8.${NC}"; echo "" ;;
    esac

    read -p "Press Enter to continue..."
    clear
done
