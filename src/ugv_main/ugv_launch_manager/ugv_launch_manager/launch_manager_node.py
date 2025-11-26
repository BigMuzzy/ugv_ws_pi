#!/usr/bin/env python3
"""
Launch Manager Node
Provides ROS2 services to dynamically switch between operational modes
"""

import rclpy
from rclpy.node import Node
from ugv_interface.srv import SwitchMode, GetMode, StopAll
from ament_index_python.packages import get_package_share_directory
import os
import yaml
import subprocess
from pathlib import Path

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

        # Start persistent agent script
        self.agent_process = None
        self.start_agent_script()

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

        self.get_logger().info("Launch Manager ready! Available services:")
        self.get_logger().info("  - /ugv/switch_mode")
        self.get_logger().info("  - /ugv/get_mode")
        self.get_logger().info("  - /ugv/stop_all")

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

    def start_agent_script(self):
        """Start the persistent agent script that runs throughout the manager's lifetime"""
        agent_script = Path.home() / '.transitive' / 'start_agent.sh'

        if not agent_script.exists():
            self.get_logger().warn(
                f"Agent script not found at {agent_script}. Skipping agent startup."
            )
            return

        if not os.access(agent_script, os.X_OK):
            self.get_logger().warn(
                f"Agent script at {agent_script} is not executable. Skipping agent startup."
            )
            return

        try:
            self.get_logger().info(f"Starting persistent agent script: {agent_script}")
            self.agent_process = subprocess.Popen(
                [str(agent_script)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )
            self.get_logger().info(
                f"Agent script started with PID: {self.agent_process.pid}"
            )
        except Exception as e:
            self.get_logger().error(f"Failed to start agent script: {e}")
            self.agent_process = None

    def stop_agent_script(self):
        """Stop the persistent agent script"""
        if self.agent_process:
            try:
                self.get_logger().info("Stopping persistent agent script...")
                self.agent_process.terminate()
                try:
                    self.agent_process.wait(timeout=5)
                    self.get_logger().info("Agent script terminated cleanly")
                except subprocess.TimeoutExpired:
                    self.get_logger().warn("Agent script did not terminate, killing...")
                    self.agent_process.kill()
                    self.agent_process.wait()
            except Exception as e:
                self.get_logger().error(f"Error stopping agent script: {e}")

    def save_map(self, map_path: str):
        """Save the current map using map_saver CLI"""
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
                self.get_logger().info(f"Map saved successfully to {map_path}.yaml and {map_path}.pgm")
            else:
                self.get_logger().error(f"Failed to save map: {result.stderr}")

        except subprocess.TimeoutExpired:
            self.get_logger().error("Map saving timed out after 10 seconds")
        except Exception as e:
            self.get_logger().error(f"Error saving map: {e}")

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
            # Save map if switching away from mapping mode
            if previous_mode == 'mapping' and 'map_path' in self.current_mode_arguments:
                map_path = self.current_mode_arguments['map_path']
                self.get_logger().info(f"Switching away from mapping mode, saving map...")
                self.save_map(map_path)

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
        """Handle stop all request"""
        self.get_logger().info("Stop all requested")

        if self.process_mgr.is_active():
            # Save map if stopping from mapping mode
            current_mode = self.process_mgr.current_mode
            if current_mode == 'mapping' and 'map_path' in self.current_mode_arguments:
                map_path = self.current_mode_arguments['map_path']
                self.get_logger().info(f"Stopping mapping mode, saving map...")
                self.save_map(map_path)

            if self.process_mgr.stop_launch():
                self.process_mgr.set_mode('idle')
                self.current_mode_arguments = {}
                response.success = True
                response.message = "All systems stopped"
                self.get_logger().info(response.message)
            else:
                response.success = False
                response.message = "Failed to stop systems"
                self.get_logger().error(response.message)
        else:
            response.success = True
            response.message = "No active systems to stop"
            self.get_logger().info(response.message)

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

        # Stop persistent agent script
        node.stop_agent_script()

        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
