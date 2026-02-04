#!/usr/bin/env python3
"""
Launch Manager Node
Provides ROS2 services to dynamically switch between operational modes

Architecture:
- Background processes (always running): motors, LIDAR, TF, rosbridge, webrtc
- Mode processes (switched): SLAM (mapping) or Nav2 (navigation)

Hybrid shutdown approach:
- Nav2: Uses lifecycle_manager for graceful shutdown, then process kill
- SLAM: Uses process kill (SIGINT)
"""

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from ugv_interface.srv import SwitchMode, GetMode, StopAll, MapSave, ListMaps
from nav2_msgs.srv import ManageLifecycleNodes
from ament_index_python.packages import get_package_share_directory
import os
import signal
import yaml
import subprocess

from .launch_process_manager import LaunchProcessManager


class LaunchManagerNode(Node):
    """Node that manages dynamic launch file switching"""

    def __init__(self):
        super().__init__('launch_manager')

        self.get_logger().info("Initializing Launch Manager Node...")

        # Declare and get default_mode parameter
        self.declare_parameter('default_mode', 'none')
        default_mode = self.get_parameter('default_mode').value

        # Declare and get debug parameter
        self.declare_parameter('debug', False)
        self.debug_mode = self.get_parameter('debug').value

        if self.debug_mode:
            self.get_logger().info("DEBUG MODE ENABLED - All subprocess output will be shown")

        # Callback group for service clients (allows nested service calls)
        self.callback_group = ReentrantCallbackGroup()

        # Process manager for mode switching
        self.process_mgr = LaunchProcessManager(
            logger=self.get_logger(),
            debug=self.debug_mode
        )

        # Store current mode arguments for cleanup operations
        self.current_mode_arguments = {}

        # Nav2 lifecycle manager client (created lazily when needed)
        self.nav2_lifecycle_client = None

        # Start persistent background processes
        self.background_process = None
        self.webrtc_bridge_process = None
        self.rosbridge_process = None
        
        # Start background processes (motors, LIDAR, TF)
        self.start_background()
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

        self.list_maps_srv = self.create_service(
            ListMaps,
            '/ugv/list_maps',
            self.list_maps_callback
        )

        self.get_logger().info("Launch Manager ready! Available services:")
        self.get_logger().info("  - /ugv/switch_mode")
        self.get_logger().info("  - /ugv/get_mode")
        self.get_logger().info("  - /ugv/stop_all")
        self.get_logger().info("  - /ugv/save_map")
        self.get_logger().info("  - /ugv/list_maps")

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

    def start_background(self):
        """Start background processes (motors, LIDAR, TF) that persist across mode switches"""
        try:
            self.get_logger().info("Starting background processes (motors, LIDAR, TF)...")

            # In debug mode, show output; otherwise silence it
            if self.debug_mode:
                self.background_process = subprocess.Popen(
                    [
                        'ros2', 'launch', 'ugv_launch_manager', 'background.launch.py'
                    ],
                    start_new_session=True
                )
            else:
                self.background_process = subprocess.Popen(
                    [
                        'ros2', 'launch', 'ugv_launch_manager', 'background.launch.py'
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            self.get_logger().info(
                f"Background processes started with PID: {self.background_process.pid}"
            )
        except Exception as e:
            self.get_logger().error(f"Failed to start background processes: {e}")
            self.background_process = None

    def stop_background(self):
        """Stop background processes (motors, LIDAR, TF)"""
        if self.background_process:
            try:
                pid = self.background_process.pid
                self.get_logger().info(f"Stopping background processes (PID: {pid})...")

                # Kill the entire process group
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except ProcessLookupError:
                    return  # Already dead

                try:
                    self.background_process.wait(timeout=10)
                    self.get_logger().info("Background processes terminated cleanly")
                except subprocess.TimeoutExpired:
                    self.get_logger().warn("Background processes did not terminate, force killing...")
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.background_process.wait()
            except Exception as e:
                self.get_logger().error(f"Error stopping background processes: {e}")
            finally:
                self.background_process = None

    def shutdown_nav2_lifecycle(self, timeout: float = 5.0) -> bool:
        """
        Gracefully shutdown Nav2 nodes using the lifecycle_manager service.
        
        This sends a SHUTDOWN command to Nav2's lifecycle_manager which will
        transition all managed nodes through their lifecycle states cleanly.
        
        Args:
            timeout: Seconds to wait for the service call
            
        Returns:
            True if shutdown was successful, False otherwise
        """
        try:
            # Create client if not exists
            if self.nav2_lifecycle_client is None:
                self.nav2_lifecycle_client = self.create_client(
                    ManageLifecycleNodes,
                    '/lifecycle_manager_navigation/manage_nodes',
                    callback_group=self.callback_group
                )
            
            # Check if service is available
            if not self.nav2_lifecycle_client.wait_for_service(timeout_sec=2.0):
                self.get_logger().warn(
                    "Nav2 lifecycle_manager service not available, "
                    "falling back to process kill"
                )
                return False
            
            self.get_logger().info("Sending SHUTDOWN command to Nav2 lifecycle_manager...")
            
            # Create request with SHUTDOWN command (command=3)
            request = ManageLifecycleNodes.Request()
            request.command = ManageLifecycleNodes.Request.SHUTDOWN  # 3
            
            # Call service synchronously
            future = self.nav2_lifecycle_client.call_async(request)
            
            # Wait for result with timeout
            start_time = self.get_clock().now()
            while not future.done():
                rclpy.spin_once(self, timeout_sec=0.1)
                elapsed = (self.get_clock().now() - start_time).nanoseconds / 1e9
                if elapsed > timeout:
                    self.get_logger().warn(
                        f"Nav2 lifecycle shutdown timed out after {timeout}s"
                    )
                    return False
            
            result = future.result()
            if result.success:
                self.get_logger().info("Nav2 lifecycle shutdown completed successfully")
                return True
            else:
                self.get_logger().warn("Nav2 lifecycle shutdown returned failure")
                return False
                
        except Exception as e:
            self.get_logger().warn(f"Error during Nav2 lifecycle shutdown: {e}")
            return False

    def start_rosbridge(self):
        """Start ROSBridge WebSocket server in background"""
        try:
            self.get_logger().info("Starting ROSBridge WebSocket server...")

            # In debug mode, show output; otherwise silence it
            if self.debug_mode:
                self.rosbridge_process = subprocess.Popen(
                    [
                        'ros2', 'launch', 'ugv_launch_manager', 'rosbridge_websocket_custom.xml'
                    ],
                    start_new_session=True
                )
            else:
                self.rosbridge_process = subprocess.Popen(
                    [
                        'ros2', 'launch', 'ugv_launch_manager', 'rosbridge_websocket_custom.xml'
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            self.get_logger().info(
                f"ROSBridge server started with PID: {self.rosbridge_process.pid} "
                "(with action goal cancelation support)"
            )
        except Exception as e:
            self.get_logger().error(f"Failed to start ROSBridge server: {e}")
            self.rosbridge_process = None

    def stop_rosbridge(self):
        """Stop ROSBridge WebSocket server"""
        if self.rosbridge_process:
            try:
                pid = self.rosbridge_process.pid
                self.get_logger().info(f"Stopping ROSBridge server (PID: {pid})...")

                # Kill the entire process group
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except ProcessLookupError:
                    return  # Already dead

                try:
                    self.rosbridge_process.wait(timeout=5)
                    self.get_logger().info("ROSBridge server terminated cleanly")
                except subprocess.TimeoutExpired:
                    self.get_logger().warn("ROSBridge server did not terminate, force killing...")
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.rosbridge_process.wait()
            except Exception as e:
                self.get_logger().error(f"Error stopping ROSBridge server: {e}")
            finally:
                self.rosbridge_process = None

    def start_webrtc_bridge(self):
        """Start WebRTC ROS2 bridge in background"""
        try:
            self.get_logger().info("Starting WebRTC ROS2 bridge...")

            # In debug mode, show output; otherwise silence it
            if self.debug_mode:
                self.webrtc_bridge_process = subprocess.Popen(
                    [
                        'ros2', 'launch', 'webrtc_ros2_bridge', 'bridge.launch.py'
                    ],
                    start_new_session=True
                )
            else:
                self.webrtc_bridge_process = subprocess.Popen(
                    [
                        'ros2', 'launch', 'webrtc_ros2_bridge', 'bridge.launch.py'
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
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
                pid = self.webrtc_bridge_process.pid
                self.get_logger().info(f"Stopping WebRTC bridge (PID: {pid})...")

                # Kill the entire process group
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except ProcessLookupError:
                    return  # Already dead

                try:
                    self.webrtc_bridge_process.wait(timeout=5)
                    self.get_logger().info("WebRTC bridge terminated cleanly")
                except subprocess.TimeoutExpired:
                    self.get_logger().warn("WebRTC bridge did not terminate, force killing...")
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.webrtc_bridge_process.wait()
            except Exception as e:
                self.get_logger().error(f"Error stopping WebRTC bridge: {e}")
            finally:
                self.webrtc_bridge_process = None

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
        """Get default mode configurations (fallback if modes.yaml fails to load)"""
        return {
            'mapping': {
                'launch_package': 'ugv_launch_manager',
                'launch_file': 'mode_mapping.launch.py',
                'description': 'SLAM mapping mode'
            },
            'navigation': {
                'launch_package': 'ugv_launch_manager',
                'launch_file': 'mode_navigation.launch.py',
                'arguments': {
                    'map_path': '/home/ws/ugv_ws/maps/second_floor.yaml'
                },
                'description': 'Navigation with Nav2'
            }
        }

    def switch_mode_callback(self, request, response):
        """Handle mode switch requests between mapping and navigation
        
        Hybrid shutdown approach:
        - Navigation mode: Uses Nav2 lifecycle_manager for graceful shutdown first
        - Mapping mode: Uses process kill (SIGINT)
        """
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

        # Stop current mode if active (SLAM or Nav2)
        if self.process_mgr.is_active():
            self.get_logger().info(f"Stopping current mode: {previous_mode}")
            
            # Hybrid approach: Use lifecycle shutdown for Nav2, process kill for SLAM
            if previous_mode == 'navigation':
                # Gracefully shutdown Nav2 via lifecycle_manager first
                self.get_logger().info("Using Nav2 lifecycle manager for graceful shutdown...")
                lifecycle_success = self.shutdown_nav2_lifecycle(timeout=5.0)
                if lifecycle_success:
                    self.get_logger().info("Nav2 lifecycle shutdown successful, cleaning up process...")
                else:
                    self.get_logger().warn("Nav2 lifecycle shutdown failed, falling back to process kill")
            
            # Always call stop_launch to clean up the process
            if not self.process_mgr.stop_launch():
                response.success = False
                response.message = "Failed to stop current mode"
                response.previous_mode = previous_mode
                response.current_mode = previous_mode
                return response

        # Start new mode
        mode_config = self.modes[requested_mode]
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
        if not (request.stop_mode or request.stop_webrtc or request.stop_rosbridge or request.stop_background):
            self.get_logger().info("Stop all requested - no flags set, stopping everything")
            request.stop_mode = True
            request.stop_webrtc = True
            request.stop_rosbridge = True
            request.stop_background = True
        else:
            flags = []
            if request.stop_mode:
                flags.append("mode")
            if request.stop_background:
                flags.append("background")
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
                current_mode = self.process_mgr.current_mode
                
                # Hybrid approach: Use lifecycle shutdown for Nav2
                if current_mode == 'navigation':
                    self.get_logger().info("Using Nav2 lifecycle manager for graceful shutdown...")
                    self.shutdown_nav2_lifecycle(timeout=5.0)
                
                if self.process_mgr.stop_launch():
                    self.process_mgr.set_mode('none')
                    self.current_mode_arguments = {}
                    stopped.append("mode processes")
                    self.get_logger().info("Mode processes stopped")
                else:
                    errors.append("Failed to stop mode processes")
                    self.get_logger().error("Failed to stop mode processes")
            else:
                self.get_logger().info("No active mode to stop")

        # Stop background processes (motors, LIDAR, TF)
        if request.stop_background:
            try:
                self.stop_background()
                stopped.append("background processes")
            except Exception as e:
                error_msg = f"Failed to stop background processes: {e}"
                errors.append(error_msg)
                self.get_logger().error(error_msg)

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

    def list_maps_callback(self, request, response):
        """Handle list maps requests"""
        maps_directory = request.maps_directory

        # Use default directory if not provided
        if not maps_directory:
            maps_directory = '/home/ws/ugv_ws/maps'

        self.get_logger().info(f"Listing maps in directory: {maps_directory}")

        try:
            # Check if directory exists
            if not os.path.exists(maps_directory):
                response.success = False
                response.message = f"Maps directory does not exist: {maps_directory}"
                response.map_names = []
                response.map_paths = []
                self.get_logger().error(response.message)
                return response

            if not os.path.isdir(maps_directory):
                response.success = False
                response.message = f"Path is not a directory: {maps_directory}"
                response.map_names = []
                response.map_paths = []
                self.get_logger().error(response.message)
                return response

            # Find all .yaml files (map configuration files)
            map_files = {}
            for file in os.listdir(maps_directory):
                if file.endswith('.yaml'):
                    # Remove .yaml extension to get map name
                    map_name = file[:-5]
                    yaml_path = os.path.join(maps_directory, file)

                    # Check if corresponding .pgm file exists
                    pgm_path = os.path.join(maps_directory, f"{map_name}.pgm")
                    if os.path.exists(pgm_path):
                        map_files[map_name] = yaml_path
                    else:
                        self.get_logger().warn(
                            f"Found {file} but missing corresponding .pgm file, skipping"
                        )

            # Sort map names alphabetically
            sorted_maps = sorted(map_files.items())

            response.success = True
            response.map_names = [name for name, _ in sorted_maps]
            response.map_paths = [path for _, path in sorted_maps]
            response.message = f"Found {len(sorted_maps)} map(s) in {maps_directory}"

            self.get_logger().info(
                f"Successfully listed {len(sorted_maps)} map(s): {response.map_names}"
            )

        except Exception as e:
            response.success = False
            response.message = f"Error listing maps: {e}"
            response.map_names = []
            response.map_paths = []
            self.get_logger().error(response.message)

        return response


def main(args=None):
    rclpy.init(args=args)
    node = LaunchManagerNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("\nShutting down launch manager...")
    finally:
        # Clean shutdown - do this BEFORE destroying the node
        # so logger still works
        if node.process_mgr.is_active():
            node.get_logger().info("Shutting down active launch process...")
            node.process_mgr.stop_launch()

        # Stop persistent background processes
        node.get_logger().info("Stopping all background services...")
        node.stop_background()
        node.stop_webrtc_bridge()
        node.stop_rosbridge()

        # Now destroy the node and shutdown rclpy
        try:
            node.destroy_node()
        except:
            pass  # Ignore errors if already destroyed

        try:
            if rclpy.ok():
                rclpy.shutdown()
        except:
            pass  # Ignore errors if already shutdown


if __name__ == '__main__':
    main()
