#!/bin/bash
# Script to install and manage the UGV ROS2 autostart service

SERVICE_FILE="ugv-ros2-autostart.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_FILE"

case "$1" in
    install)
        echo "Installing UGV ROS2 autostart service..."

        # Stop service if it's already running
        if sudo systemctl is-active --quiet $SERVICE_FILE; then
            echo "Service is running, stopping it..."
            sudo systemctl stop $SERVICE_FILE
        fi

        sudo cp $SERVICE_FILE $SERVICE_PATH
        sudo systemctl daemon-reload

        echo ""
        echo "Enabling network wait service..."
        # Detect and enable the appropriate network wait service
        if systemctl list-unit-files | grep -q "NetworkManager.service"; then
            echo "Detected NetworkManager, enabling NetworkManager-wait-online.service..."
            sudo systemctl enable NetworkManager-wait-online.service
            echo "NetworkManager-wait-online.service enabled!"
        elif systemctl list-unit-files | grep -q "systemd-networkd.service"; then
            echo "Detected systemd-networkd, enabling systemd-networkd-wait-online.service..."
            sudo systemctl enable systemd-networkd-wait-online.service
            echo "systemd-networkd-wait-online.service enabled!"
        else
            echo "Warning: Could not detect network manager (NetworkManager or systemd-networkd)"
            echo "You may need to manually enable a network-wait-online service"
        fi

        echo ""
        sudo systemctl enable $SERVICE_FILE
        echo "Service installed and enabled!"

        # Restart the service to apply changes
        echo ""
        echo "Starting service..."
        sudo systemctl start $SERVICE_FILE
        echo ""
        echo "Service is now running!"
        echo "To check status: sudo systemctl status $SERVICE_FILE"
        echo "To view logs: sudo journalctl -u $SERVICE_FILE -f"
        ;;

    uninstall)
        echo "Uninstalling UGV ROS2 autostart service..."
        sudo systemctl stop $SERVICE_FILE
        sudo systemctl disable $SERVICE_FILE
        sudo rm $SERVICE_PATH
        sudo systemctl daemon-reload
        echo "Service uninstalled!"
        ;;

    start)
        echo "Starting UGV ROS2 autostart service..."
        sudo systemctl start $SERVICE_FILE
        ;;

    stop)
        echo "Stopping UGV ROS2 autostart service..."
        sudo systemctl stop $SERVICE_FILE
        ;;

    restart)
        echo "Restarting UGV ROS2 autostart service..."
        sudo systemctl restart $SERVICE_FILE
        ;;

    status)
        sudo systemctl status $SERVICE_FILE
        ;;

    logs)
        echo "Showing service logs (Ctrl+C to exit)..."
        sudo journalctl -u $SERVICE_FILE -f
        ;;

    *)
        echo "UGV ROS2 Autostart Service Manager"
        echo "Usage: $0 {install|uninstall|start|stop|restart|status|logs}"
        echo ""
        echo "Commands:"
        echo "  install   - Install and enable the service to start on boot"
        echo "  uninstall - Stop and remove the service"
        echo "  start     - Start the service now"
        echo "  stop      - Stop the service"
        echo "  restart   - Restart the service"
        echo "  status    - Show service status"
        echo "  logs      - Show live service logs"
        exit 1
        ;;
esac
