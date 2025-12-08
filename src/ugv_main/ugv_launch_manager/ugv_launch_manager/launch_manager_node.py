#!/usr/bin/env python3
"""
Launch Manager Node
Provides ROS2 services to dynamically switch between operational modes
"""

import rclpy
from rclpy.node import Node
from ugv_interface.srv import SwitchMode, GetMode, StopAll, MapSave
from ament_index_python.packages import get_package_share_directory
import os
import yaml
import subprocess

from .launch_process_manager import LaunchProcessManager


class LaunchManagerNode(Node):
    """Node that manages dynamic launch file switching"""

    def __init__(self):
        super().__init__('launch_manager')

        self.get_logger().info("Initializing Launch Manager Node...")

        # Declare and get default_mode parameter
        self.declare_parameter('default_mode', 'idle')
        default_mode = self.get_parameter('default_mode').value

        # Process manager
        self.process_mgr = LaunchProcessManager(logger=self.get_logger())

        # Store current mode arguments for cleanup operations
        self.current_mode_arguments = {}

        # Start persistent background processes
        self.webrtc_bridge_process = None
        self.rosbridge_process = None
        self.start_webrtc_bridge()
        self.start_rosbridge()

        # Load mode configurations
        self.modes = self.load_mode_config()
        self.get_logger().info(f"Loaded {len(self.modes)} modes: {list(self.modes.keys())}")

        # Create service servers
        self.switch_mode_srv = self.create_service(
            SwitchMode,
            '/ugv/switch_mode',
            self.switch_mode_callback
        )

        self.get_mode_srv = self.create_service(
            GetMode,
            '/ugv/get_mode',
            self.get_mode_callback
        )

        self.stop_all_srv = self.create_service(
            StopAll,
            '/ugv/stop_all',
            self.stop_all_callback
        )

        self.save_map_srv = self.create_service(
            MapSave,
            '/ugv/save_map',
            self.save_map_callback
        )

        self.get_logger().info("Launch Manager ready! Available services:")
        self.get_logger().info("  - /ugv/switch_mode")
        self.get_logger().info("  - /ugv/get_mode")
        self.get_logger().info("  - /ugv/stop_all")
        self.get_logger().info("  - /ugv/save_map")

        # Auto-start default mode if specified
        if default_mode and default_mode != 'none':
            self.get_logger().info(f"Auto-starting default mode: {default_mode}")
            self.auto_start_mode(default_mode)

    def auto_start_mode(self, mode: str):
        """Automatically start a mode on initialization"""
        if mode not in self.modes:
            self.get_logger().warn(
                f"Cannot auto-start unknown mode: {mode}. "
                f"Available: {list(self.modes.keys())}"
            )
            return

        mode_config = self.modes[mode]

        # Start the mode
        if 'launch_package' in mode_config:
            package = mode_config['launch_package']
            launch_file = mode_config['launch_file']
            arguments = mode_config.get('arguments', {})

            if self.process_mgr.start_launch(package, launch_file, arguments):
                self.process_mgr.set_mode(mode)
                self.get_logger().info(f"Successfully auto-started {mode} mode")
            else:
                self.get_logger().error(f"Failed to auto-start {mode} mode")
        else:
            # Mode with no launch file (basic idle)
            self.process_mgr.set_mode(mode)
            self.get_logger().info(f"Set to {mode} mode (no process)")

    def start_rosbridge(self):
        """Start ROSBridge WebSocket server in background"""
        try:
            self.get_logger().info("Starting ROSBridge WebSocket server...")
            self.rosbridge_process = subprocess.Popen(
                [
                    'ros2', 'launch', 'rosbridge_server', 'rosbridge_websocket_launch.xml'
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            self.get_logger().info(
                f"ROSBridge server started with PID: {self.rosbridge_process.pid}"
            )
        except Exception as e:
            self.get_logger().error(f"Failed to start ROSBridge server: {e}")
            self.rosbridge_process = None

    def stop_rosbridge(self):
        """Stop ROSBridge WebSocket server"""
        if self.rosbridge_process:
            try:
                self.get_logger().info("Stopping ROSBridge server...")
                self.rosbridge_process.terminate()
                try:
                    self.rosbridge_process.wait(timeout=5)
                    self.get_logger().info("ROSBridge server terminated cleanly")
                except subprocess.TimeoutExpired:
                    self.get_logger().warn("ROSBridge server did not terminate, killing...")
                    self.rosbridge_process.kill()
                    self.rosbridge_process.wait()
            except Exception as e:
                self.get_logger().error(f"Error stopping ROSBridge server: {e}")

    def start_webrtc_bridge(self):
        """Start WebRTC ROS2 bridge in background"""
        try:
            self.get_logger().info("Starting WebRTC ROS2 bridge...")
            self.webrtc_bridge_process = subprocess.Popen(
                [
                    'ros2', 'launch', 'webrtc_ros2_bridge', 'bridge.launch.py'
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            self.get_logger().info(
                f"WebRTC bridge started with PID: {self.webrtc_bridge_process.pid}"
            )
        except Exception as e:
            self.get_logger().error(f"Failed to start WebRTC bridge: {e}")
            self.webrtc_bridge_process = None

    def stop_webrtc_bridge(self):
        """Stop WebRTC ROS2 bridge"""
        if self.webrtc_bridge_process:
            try:
                self.get_logger().info("Stopping WebRTC bridge...")
                self.webrtc_bridge_process.terminate()
                try:
                    self.webrtc_bridge_process.wait(timeout=5)
                    self.get_logger().info("WebRTC bridge terminated cleanly")
                except subprocess.TimeoutExpired:
                    self.get_logger().warn("WebRTC bridge did not terminate, killing...")
                    self.webrtc_bridge_process.kill()
                    self.webrtc_bridge_process.wait()
            except Exception as e:
                self.get_logger().error(f"Error stopping WebRTC bridge: {e}")

    def save_map(self, map_path: str) -> tuple[bool, str]:
        """Save the current map using map_saver CLI

        Returns:
            tuple[bool, str]: (success, message)
        """
        try:
            self.get_logger().info(f"Saving map to: {map_path}")

            # Use map_saver_cli to save the map
            result = subprocess.run(
                ['ros2', 'run', 'nav2_map_server', 'map_saver_cli', '-f', map_path],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                message = f"Map saved successfully to {map_path}.yaml and {map_path}.pgm"
                self.get_logger().info(message)
                return True, message
            else:
                message = f"Failed to save map: {result.stderr}"
                self.get_logger().error(message)
                return False, message

        except subprocess.TimeoutExpired:
            message = "Map saving timed out after 10 seconds"
            self.get_logger().error(message)
            return False, message
        except Exception as e:
            message = f"Error saving map: {e}"
            self.get_logger().error(message)
            return False, message

    def load_mode_config(self) -> dict:
        """Load mode definitions from YAML config"""
        try:
            config_path = os.path.join(
                get_package_share_directory('ugv_launch_manager'),
                'config',
                'modes.yaml'
            )

            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

            return config.get('modes', {})

        except Exception as e:
            self.get_logger().warn(f"Could not load modes.yaml: {e}")
            # Return default modes
            return self.get_default_modes()

    def get_default_modes(self) -> dict:
        """Get default mode configurations"""
        return {
            'idle': {
                'launch_package': 'ugv_vision',
                'launch_file': 'oak_d_lite.launch.py',
                'description': 'Camera only mode'
            },
            'mapping': {
                'launch_package': 'ugv_launch_manager',
                'launch_file': 'mode_mapping.launch.py',
                'description': 'SLAM mapping mode'
            },
            'navigation': {
                'launch_package': 'ugv_launch_manager',
                'launch_file': 'mode_navigation.launch.py',
                'arguments': {
                    'map': '/home/ws/ugv_ws/maps/second_floor.yaml'
                },
                'description': 'Navigation with AMCL'
            }
        }

    def switch_mode_callback(self, request, response):
        """Handle mode switch requests"""
        requested_mode = request.mode
        previous_mode = self.process_mgr.current_mode

        self.get_logger().info(f"Mode switch requested: {previous_mode} -> {requested_mode}")

        # Validate mode exists
        if requested_mode not in self.modes:
            response.success = False
            response.message = f"Unknown mode: {requested_mode}. Available: {list(self.modes.keys())}"
            response.previous_mode = previous_mode
            response.current_mode = previous_mode
            self.get_logger().error(response.message)
            return response

        # Stop current mode if active
        if self.process_mgr.is_active():
            self.get_logger().info(f"Stopping current mode: {previous_mode}")
            if not self.process_mgr.stop_launch():
                response.success = False
                response.message = "Failed to stop current mode"
                response.previous_mode = previous_mode
                response.current_mode = previous_mode
                return response

        # Start new mode (unless it's 'idle' with no process)
        mode_config = self.modes[requested_mode]

        if requested_mode != 'idle' or 'launch_package' in mode_config:
            self.get_logger().info(f"Starting new mode: {requested_mode}")

            package = mode_config['launch_package']
            launch_file = mode_config['launch_file']
            arguments = mode_config.get('arguments', {}).copy()

            # Merge service call arguments with defaults from config
            if hasattr(request, 'arg_names') and hasattr(request, 'arg_values'):
                if len(request.arg_names) == len(request.arg_values):
                    for name, value in zip(request.arg_names, request.arg_values):
                        arguments[name] = value
                        self.get_logger().info(f"Override argument: {name}={value}")
                elif len(request.arg_names) > 0 or len(request.arg_values) > 0:
                    self.get_logger().warn(
                        f"Mismatched arg_names and arg_values lengths, ignoring custom arguments"
                    )

            if self.process_mgr.start_launch(package, launch_file, arguments):
                self.process_mgr.set_mode(requested_mode)
                # Store arguments for cleanup operations (like map saving)
                self.current_mode_arguments = arguments.copy()
                response.success = True
                response.message = f"Successfully switched to {requested_mode} mode"
                response.previous_mode = previous_mode
                response.current_mode = requested_mode
                self.get_logger().info(response.message)
            else:
                response.success = False
                response.message = f"Failed to start {requested_mode} mode"
                response.previous_mode = previous_mode
                response.current_mode = previous_mode
                self.get_logger().error(response.message)
        else:
            # Idle mode with no active process
            self.process_mgr.set_mode('idle')
            self.current_mode_arguments = {}
            response.success = True
            response.message = "Switched to idle mode (all systems stopped)"
            response.previous_mode = previous_mode
            response.current_mode = 'idle'
            self.get_logger().info(response.message)

        return response

    def get_mode_callback(self, request, response):
        """Handle get mode status requests"""
        status = self.process_mgr.get_status()

        response.current_mode = status['mode']
        response.is_active = status['is_active']
        response.available_modes = list(self.modes.keys())

        uptime = status.get('uptime')
        if uptime:
            self.get_logger().info(
                f"Current mode: {response.current_mode} "
                f"(active for {uptime:.1f}s)"
            )

        return response

    def stop_all_callback(self, request, response):
        """Handle stop all request with selective process stopping"""
        # If no flags are set, stop everything (backwards compatibility)
        if not (request.stop_mode or request.stop_webrtc or request.stop_rosbridge):
            self.get_logger().info("Stop all requested - no flags set, stopping everything")
            request.stop_mode = True
            request.stop_webrtc = True
            request.stop_rosbridge = True
        else:
            flags = []
            if request.stop_mode:
                flags.append("mode")
            if request.stop_webrtc:
                flags.append("webrtc")
            if request.stop_rosbridge:
                flags.append("rosbridge")
            self.get_logger().info(f"Stop all requested - stopping: {', '.join(flags)}")

        errors = []
        stopped = []

        # Stop current mode process
        if request.stop_mode:
            if self.process_mgr.is_active():
                if self.process_mgr.stop_launch():
                    self.process_mgr.set_mode('idle')
                    self.current_mode_arguments = {}
                    stopped.append("mode processes")
                    self.get_logger().info("Mode processes stopped")
                else:
                    errors.append("Failed to stop mode processes")
                    self.get_logger().error("Failed to stop mode processes")
            else:
                self.get_logger().info("No active mode to stop")

        # Stop WebRTC bridge
        if request.stop_webrtc:
            try:
                self.stop_webrtc_bridge()
                stopped.append("WebRTC bridge")
            except Exception as e:
                error_msg = f"Failed to stop WebRTC bridge: {e}"
                errors.append(error_msg)
                self.get_logger().error(error_msg)

        # Stop ROSBridge server
        if request.stop_rosbridge:
            try:
                self.stop_rosbridge()
                stopped.append("ROSBridge server")
            except Exception as e:
                error_msg = f"Failed to stop ROSBridge server: {e}"
                errors.append(error_msg)
                self.get_logger().error(error_msg)

        # Build response
        if errors:
            response.success = False
            if stopped:
                response.message = f"Stopped: {', '.join(stopped)}. Errors: {'; '.join(errors)}"
            else:
                response.message = f"Failed to stop: {'; '.join(errors)}"
            self.get_logger().warning(response.message)
        elif stopped:
            response.success = True
            response.message = f"Successfully stopped: {', '.join(stopped)}"
            self.get_logger().info(response.message)
        else:
            response.success = True
            response.message = "No processes to stop"
            self.get_logger().info(response.message)

        return response

    def save_map_callback(self, request, response):
        """Handle manual map save requests"""
        map_path = request.map_path

        # If no map_path provided, use the current mapping mode's map_path
        if not map_path:
            if self.process_mgr.current_mode != 'mapping':
                response.success = False
                response.message = "Not in mapping mode and no map_path provided"
                self.get_logger().error(response.message)
                return response

            if 'map_path' not in self.current_mode_arguments:
                response.success = False
                response.message = "Current mapping mode has no map_path set"
                self.get_logger().error(response.message)
                return response

            map_path = self.current_mode_arguments['map_path']

        # Save the map
        success, message = self.save_map(map_path)
        response.success = success
        response.message = message

        return response


def main(args=None):
    rclpy.init(args=args)
    node = LaunchManagerNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # Clean shutdown
        if node.process_mgr.is_active():
            node.get_logger().info("Shutting down active launch process...")
            node.process_mgr.stop_launch()

        # Stop persistent background processes
        node.stop_webrtc_bridge()
        node.stop_rosbridge()

        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
