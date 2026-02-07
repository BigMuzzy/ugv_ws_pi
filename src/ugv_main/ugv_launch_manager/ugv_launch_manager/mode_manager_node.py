#!/usr/bin/env python3
"""
Mode Manager Node
Manages UGV operational modes via lifecycle node control.

Architecture:
- Background processes (always running, process-based): motors, LIDAR, TF, rosbridge, webrtc
- Lifecycle launch (always running): slam_toolbox, map_server, amcl, Nav2 (all start unconfigured)
- Mode switching: lifecycle transitions for all managed nodes

Modes: IDLE, MAPPING, NAVIGATION

Management approach:
- slam_toolbox: lifecycle-managed (use_lifecycle_manager=true)
- map_server: lifecycle-managed directly via lifecycle services
- amcl: lifecycle-managed directly via lifecycle services
- Nav2 stack (9 nodes): lifecycle-managed via lifecycle_manager_navigation startup/shutdown

Teleop compatibility:
- /teleop/start_slam: Switch to mapping mode
- /teleop/complete_slam: Save map + switch to navigation (with AMCL pose seeding)
- /teleop/get_slam_state: Get current SLAM state
- /teleop/restart_slam_toolbox: Restart SLAM via lifecycle deactivate/activate
"""

import json
import time
import threading
import os
import signal
import subprocess

import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy

from ugv_interface.srv import SwitchMode, GetMode, StopAll, MapSave, ListMaps
from ugv_interface.msg import ModeStatus
from std_srvs.srv import Trigger, Empty
from nav2_msgs.srv import ManageLifecycleNodes
from geometry_msgs.msg import PoseWithCovarianceStamped
from rcl_interfaces.srv import SetParameters
from rcl_interfaces.msg import Parameter, ParameterValue, ParameterType

import tf2_ros

from .lifecycle_client import LifecycleClient


class ModeManagerNode(Node):
    """Node that manages UGV operational modes via lifecycle node control."""

    VALID_MODES = ['idle', 'mapping', 'navigation']

    def __init__(self):
        super().__init__('mode_manager')

        self.get_logger().info("Initializing Mode Manager Node...")

        # Parameters
        self.declare_parameter('default_mode', 'idle')
        self.declare_parameter('debug', False)
        self.declare_parameter('transition_timeout', 10.0)
        self.declare_parameter('map_save_path', '/home/ws/ugv_ws/maps/current_map')
        self.declare_parameter('maps_directory', '/home/ws/ugv_ws/maps')

        default_mode = self.get_parameter('default_mode').value
        self.debug_mode = self.get_parameter('debug').value
        self.transition_timeout = self.get_parameter('transition_timeout').value
        self.map_save_path = self.get_parameter('map_save_path').value
        self.maps_directory = self.get_parameter('maps_directory').value

        if self.debug_mode:
            self.get_logger().info("DEBUG MODE ENABLED - subprocess output will be shown")

        # Callback group for nested service calls
        self.cb_group = ReentrantCallbackGroup()

        # Mode state
        self.current_mode = 'idle'
        self.previous_mode = 'idle'
        self.transition_in_progress = False
        self.transition_lock = threading.Lock()
        self.mode_start_time = time.time()
        self.current_mode_arguments = {}

        # SLAM tracking (for teleop compatibility)
        self._slam_enabled = False
        self._slam_started_at_ms = None
        self._slam_control_lock = threading.Lock()
        self._slam_control_in_progress = False

        # Last known pose from SLAM (for AMCL initial pose seeding)
        self._last_slam_pose = None

        # TF buffer for pose capture
        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        # Lifecycle clients for managed nodes (slam_toolbox, map_server, amcl)
        self.slam_lc = LifecycleClient(
            self, 'slam_toolbox', self.cb_group, self.transition_timeout
        )
        self.map_server_lc = LifecycleClient(
            self, 'map_server', self.cb_group, self.transition_timeout
        )
        self.amcl_lc = LifecycleClient(
            self, 'amcl', self.cb_group, self.transition_timeout
        )

        # Nav2 lifecycle manager client (manages 9 nav nodes via startup/shutdown)
        self.nav2_lifecycle_client = self.create_client(
            ManageLifecycleNodes,
            '/lifecycle_manager_navigation/manage_nodes',
            callback_group=self.cb_group,
        )

        # Initial pose publisher (for AMCL seeding after MAPPING→NAVIGATION)
        self.initial_pose_pub = self.create_publisher(
            PoseWithCovarianceStamped, '/initialpose', 10
        )

        # ModeStatus publisher (transient_local so late joiners get last status)
        status_qos = QoSProfile(depth=1)
        status_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
        status_qos.reliability = ReliabilityPolicy.RELIABLE
        self.mode_status_pub = self.create_publisher(
            ModeStatus, '/ugv/mode_status', status_qos
        )
        self.create_timer(1.0, self._publish_mode_status)

        # Background processes (process-based, unchanged)
        self.background_process = None
        self.webrtc_bridge_process = None
        self.rosbridge_process = None
        self.lifecycle_launch_process = None

        # Start persistent background processes
        self.start_background()
        self.start_webrtc_bridge()
        self.start_rosbridge()

        # Start the lifecycle launch file (boots all lifecycle nodes in unconfigured state)
        self._start_lifecycle_launch()

        # Create all service servers
        self.create_service(SwitchMode, '/ugv/switch_mode', self.switch_mode_callback)
        self.create_service(GetMode, '/ugv/get_mode', self.get_mode_callback)
        self.create_service(StopAll, '/ugv/stop_all', self.stop_all_callback)
        self.create_service(MapSave, '/ugv/save_map', self.save_map_callback)
        self.create_service(ListMaps, '/ugv/list_maps', self.list_maps_callback)

        # Teleop compatibility services
        self.create_service(Trigger, '/teleop/start_slam', self._on_start_slam)
        self.create_service(Trigger, '/teleop/complete_slam', self._on_complete_slam)
        self.create_service(Trigger, '/teleop/get_slam_state', self._on_get_slam_state)
        self.create_service(Empty, '/teleop/restart_slam_toolbox', self._on_restart_slam)

        self.get_logger().info("Mode Manager ready! Available services:")
        self.get_logger().info("  - /ugv/switch_mode")
        self.get_logger().info("  - /ugv/get_mode")
        self.get_logger().info("  - /ugv/stop_all")
        self.get_logger().info("  - /ugv/save_map")
        self.get_logger().info("  - /ugv/list_maps")
        self.get_logger().info("  - /ugv/mode_status (topic)")
        self.get_logger().info("  - /teleop/start_slam (Trigger)")
        self.get_logger().info("  - /teleop/complete_slam (Trigger)")
        self.get_logger().info("  - /teleop/get_slam_state (Trigger)")
        self.get_logger().info("  - /teleop/restart_slam_toolbox (Empty)")

        # Auto-start default mode
        if default_mode and default_mode not in ('none', 'idle'):
            self.get_logger().info(f"Auto-starting default mode: {default_mode}")
            self._auto_start_mode(default_mode)

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle Launch Management
    # ─────────────────────────────────────────────────────────────────────────

    def _start_lifecycle_launch(self):
        """Start mode_lifecycle.launch.py which boots all lifecycle nodes."""
        try:
            self.get_logger().info("Starting lifecycle launch (all managed nodes)...")
            cmd = ['ros2', 'launch', 'ugv_launch_manager', 'mode_lifecycle.launch.py']

            if self.debug_mode:
                self.lifecycle_launch_process = subprocess.Popen(
                    cmd, start_new_session=True
                )
            else:
                self.lifecycle_launch_process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            self.get_logger().info(
                f"Lifecycle launch started PID: {self.lifecycle_launch_process.pid}"
            )

            # Wait for nodes to register in the ROS graph
            self.get_logger().info("Waiting for lifecycle nodes to appear...")
            time.sleep(5.0)
            self.get_logger().info("Lifecycle nodes should now be available")

        except Exception as e:
            self.get_logger().error(f"Failed to start lifecycle launch: {e}")
            self.lifecycle_launch_process = None

    def _stop_lifecycle_launch(self):
        """Stop the lifecycle launch process."""
        if self.lifecycle_launch_process:
            try:
                pid = self.lifecycle_launch_process.pid
                self.get_logger().info(f"Stopping lifecycle launch (PID: {pid})...")
                try:
                    os.killpg(os.getpgid(pid), signal.SIGTERM)
                except ProcessLookupError:
                    return
                try:
                    self.lifecycle_launch_process.wait(timeout=10)
                    self.get_logger().info("Lifecycle launch terminated cleanly")
                except subprocess.TimeoutExpired:
                    self.get_logger().warn("Lifecycle launch did not terminate, force killing...")
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.lifecycle_launch_process.wait()
            except Exception as e:
                self.get_logger().error(f"Error stopping lifecycle launch: {e}")
            finally:
                self.lifecycle_launch_process = None

    # ─────────────────────────────────────────────────────────────────────────
    # ModeStatus Publisher
    # ─────────────────────────────────────────────────────────────────────────

    def _publish_mode_status(self):
        """Publish current mode status on timer."""
        msg = ModeStatus()
        msg.current_mode = self.current_mode
        msg.previous_mode = self.previous_mode
        msg.stamp = self.get_clock().now().to_msg()
        msg.transition_in_progress = self.transition_in_progress
        self.mode_status_pub.publish(msg)

    # ─────────────────────────────────────────────────────────────────────────
    # AMCL Initial Pose Seeding
    # ─────────────────────────────────────────────────────────────────────────

    def _capture_slam_pose(self):
        """Capture current robot pose from TF (map→base_link) before deactivating SLAM."""
        try:
            transform = self.tf_buffer.lookup_transform(
                'map', 'base_link',
                rclpy.time.Time(),
                timeout=rclpy.duration.Duration(seconds=2.0),
            )
            self._last_slam_pose = transform
            self.get_logger().info(
                f"Captured SLAM pose: x={transform.transform.translation.x:.3f}, "
                f"y={transform.transform.translation.y:.3f}"
            )
        except Exception as e:
            self.get_logger().warn(f"Failed to capture SLAM pose: {e}")
            self._last_slam_pose = None

    def _seed_amcl_initial_pose(self):
        """Publish /initialpose from captured SLAM pose for AMCL initialization."""
        if self._last_slam_pose is None:
            self.get_logger().warn("No SLAM pose available for AMCL seeding")
            return

        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = 'map'
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.pose.position.x = self._last_slam_pose.transform.translation.x
        msg.pose.pose.position.y = self._last_slam_pose.transform.translation.y
        msg.pose.pose.position.z = 0.0
        msg.pose.pose.orientation = self._last_slam_pose.transform.rotation

        # Reasonable covariance for a pose estimate from SLAM
        msg.pose.covariance = [0.0] * 36
        msg.pose.covariance[0] = 0.25    # x variance
        msg.pose.covariance[7] = 0.25    # y variance
        msg.pose.covariance[35] = 0.068  # yaw variance (~15 deg)

        # Publish multiple times to ensure delivery
        for _ in range(3):
            self.initial_pose_pub.publish(msg)
            time.sleep(0.1)

        self.get_logger().info("Published initial pose for AMCL from SLAM pose")

    # ─────────────────────────────────────────────────────────────────────────
    # SLAM Lifecycle Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _is_slam_active(self) -> bool:
        """Check if slam_toolbox lifecycle node is in ACTIVE state."""
        from lifecycle_msgs.msg import State
        state = self.slam_lc.get_state(timeout=2.0)
        return state == State.PRIMARY_STATE_ACTIVE

    # ─────────────────────────────────────────────────────────────────────────
    # Core Lifecycle Transition Logic
    # ─────────────────────────────────────────────────────────────────────────

    def _transition_to_idle(self):
        """Deactivate all lifecycle nodes.

        Best-effort: errors in one don't block others.
        """
        errors = []

        # 1. Deactivate slam_toolbox
        try:
            self.slam_lc.deactivate_and_cleanup()
        except Exception as e:
            errors.append(f"slam_toolbox: {e}")

        # 2. Shutdown Nav2 stack via lifecycle_manager
        try:
            self._shutdown_nav2(timeout=5.0)
        except Exception as e:
            errors.append(f"nav2: {e}")

        # 3. Deactivate AMCL
        try:
            self.amcl_lc.deactivate_and_cleanup()
        except Exception as e:
            errors.append(f"amcl: {e}")

        # 4. Deactivate map_server
        try:
            self.map_server_lc.deactivate_and_cleanup()
        except Exception as e:
            errors.append(f"map_server: {e}")

        # Update SLAM tracking
        self._slam_enabled = False
        self._slam_started_at_ms = None

        if errors:
            self.get_logger().warn(f"IDLE transition had errors: {errors}")
        return len(errors) == 0

    def _transition_to_mapping(self):
        """Activate slam_toolbox, deactivate navigation lifecycle nodes."""
        # 1. Ensure all nodes are idle
        self._transition_to_idle()

        # 2. Configure and activate slam_toolbox via lifecycle
        if not self.slam_lc.configure_and_activate():
            raise RuntimeError("Failed to activate slam_toolbox")

        self._slam_enabled = True
        self._slam_started_at_ms = int(time.time() * 1000)
        self.get_logger().info("MAPPING mode active: slam_toolbox running")

    def _transition_to_navigation(self, map_yaml_path: str):
        """Activate map_server, AMCL, and Nav2 stack."""
        # 0. Validate map exists
        if not os.path.exists(map_yaml_path):
            raise RuntimeError(f"Map file not found: {map_yaml_path}")

        was_mapping = (self.current_mode == 'mapping')

        # 1. Capture SLAM pose BEFORE deactivating (for AMCL seeding)
        if was_mapping:
            self._capture_slam_pose()

        # 2. Deactivate all nodes
        self._transition_to_idle()

        # 3. Set map_server yaml_filename parameter BEFORE configure
        self._set_remote_parameter('map_server', 'yaml_filename', map_yaml_path)

        # 4. Configure and activate map_server
        if not self.map_server_lc.configure_and_activate():
            raise RuntimeError("Failed to activate map_server")
        self.get_logger().info(f"map_server active with map: {map_yaml_path}")

        # 5. Configure and activate AMCL
        if not self.amcl_lc.configure_and_activate():
            raise RuntimeError("Failed to activate AMCL")
        self.get_logger().info("AMCL active")

        # 6. Seed AMCL with initial pose from SLAM
        if was_mapping and self._last_slam_pose is not None:
            time.sleep(0.5)  # Let AMCL fully initialize
            self._seed_amcl_initial_pose()

        # 7. Start Nav2 stack via lifecycle_manager_navigation
        self._startup_nav2(timeout=30.0)
        self.get_logger().info("NAVIGATION mode active: full Nav2 stack running")

    def _startup_nav2(self, timeout: float = 30.0):
        """Start Nav2 stack via lifecycle_manager_navigation STARTUP command."""
        if not self.nav2_lifecycle_client.wait_for_service(timeout_sec=5.0):
            raise RuntimeError("Nav2 lifecycle_manager service not available")

        self.get_logger().info("Sending STARTUP command to Nav2 lifecycle_manager...")
        request = ManageLifecycleNodes.Request()
        request.command = ManageLifecycleNodes.Request.STARTUP

        future = self.nav2_lifecycle_client.call_async(request)
        start = time.monotonic()
        while not future.done():
            rclpy.spin_once(self, timeout_sec=0.1)
            if time.monotonic() - start > timeout:
                raise RuntimeError(f"Nav2 startup timed out after {timeout}s")

        result = future.result()
        if not result.success:
            raise RuntimeError("Nav2 lifecycle_manager STARTUP returned failure")
        self.get_logger().info("Nav2 lifecycle startup completed successfully")

    def _shutdown_nav2(self, timeout: float = 5.0):
        """Shutdown Nav2 stack via lifecycle_manager_navigation SHUTDOWN command."""
        if not self.nav2_lifecycle_client.wait_for_service(timeout_sec=2.0):
            self.get_logger().info("Nav2 lifecycle_manager not available, skipping shutdown")
            return

        self.get_logger().info("Sending SHUTDOWN command to Nav2 lifecycle_manager...")
        request = ManageLifecycleNodes.Request()
        request.command = ManageLifecycleNodes.Request.SHUTDOWN

        future = self.nav2_lifecycle_client.call_async(request)
        start = time.monotonic()
        while not future.done():
            rclpy.spin_once(self, timeout_sec=0.1)
            if time.monotonic() - start > timeout:
                self.get_logger().warn(f"Nav2 shutdown timed out after {timeout}s")
                return

        result = future.result()
        if result.success:
            self.get_logger().info("Nav2 lifecycle shutdown completed successfully")
        else:
            self.get_logger().warn("Nav2 lifecycle shutdown returned failure")

    def _set_remote_parameter(self, node_name: str, param_name: str, value: str):
        """Set a parameter on a remote node before configuring it."""
        client = self.create_client(
            SetParameters,
            f'/{node_name}/set_parameters',
            callback_group=self.cb_group,
        )
        try:
            if not client.wait_for_service(timeout_sec=5.0):
                raise RuntimeError(
                    f"set_parameters service not available for {node_name}"
                )

            request = SetParameters.Request()
            param = Parameter()
            param.name = param_name
            param.value = ParameterValue()
            param.value.type = ParameterType.PARAMETER_STRING
            param.value.string_value = str(value)
            request.parameters = [param]

            future = client.call_async(request)
            start = time.monotonic()
            while not future.done():
                rclpy.spin_once(self, timeout_sec=0.1)
                if time.monotonic() - start > 5.0:
                    raise RuntimeError(
                        f"set_parameters timed out for {node_name}/{param_name}"
                    )

            result = future.result()
            if result and result.results and result.results[0].successful:
                self.get_logger().info(
                    f"Set {node_name}/{param_name} = {value}"
                )
            else:
                reason = ''
                if result and result.results:
                    reason = result.results[0].reason
                raise RuntimeError(
                    f"Failed to set {node_name}/{param_name}: {reason}"
                )
        finally:
            self.destroy_client(client)

    def _auto_start_mode(self, mode: str):
        """Automatically start a mode on initialization."""
        if mode not in self.VALID_MODES:
            self.get_logger().warn(
                f"Cannot auto-start unknown mode: {mode}. "
                f"Available: {self.VALID_MODES}"
            )
            return

        try:
            if mode == 'mapping':
                self._transition_to_mapping()
            elif mode == 'navigation':
                map_path = self.map_save_path + '.yaml'
                self._transition_to_navigation(map_path)
            else:
                return  # idle is default, nothing to do

            self.current_mode = mode
            self.mode_start_time = time.time()
            self.get_logger().info(f"Successfully auto-started {mode} mode")
        except Exception as e:
            self.get_logger().error(f"Failed to auto-start {mode} mode: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Service Callbacks
    # ─────────────────────────────────────────────────────────────────────────

    def switch_mode_callback(self, request, response):
        """Handle /ugv/switch_mode — lifecycle transitions instead of process kill/start."""
        requested_mode = request.mode
        previous_mode = self.current_mode

        self.get_logger().info(f"Mode switch requested: {previous_mode} -> {requested_mode}")

        # Validate mode
        if requested_mode not in self.VALID_MODES:
            response.success = False
            response.message = (
                f"Unknown mode: {requested_mode}. Available: {self.VALID_MODES}"
            )
            response.previous_mode = previous_mode
            response.current_mode = previous_mode
            self.get_logger().error(response.message)
            return response

        # Already in this mode
        if requested_mode == self.current_mode:
            response.success = True
            response.message = f"Already in {requested_mode} mode"
            response.previous_mode = previous_mode
            response.current_mode = requested_mode
            return response

        with self.transition_lock:
            self.transition_in_progress = True
            self._publish_mode_status()

            try:
                # Parse runtime argument overrides
                arguments = {}
                if hasattr(request, 'arg_names') and hasattr(request, 'arg_values'):
                    if len(request.arg_names) == len(request.arg_values):
                        for name, value in zip(request.arg_names, request.arg_values):
                            arguments[name] = value
                            self.get_logger().info(f"Override argument: {name}={value}")
                    elif len(request.arg_names) > 0 or len(request.arg_values) > 0:
                        self.get_logger().warn(
                            "Mismatched arg_names and arg_values lengths, ignoring"
                        )

                # Execute transition
                if requested_mode == 'idle':
                    self._transition_to_idle()
                elif requested_mode == 'mapping':
                    self._transition_to_mapping()
                elif requested_mode == 'navigation':
                    map_path = arguments.get(
                        'map_path', self.map_save_path + '.yaml'
                    )
                    self._transition_to_navigation(map_path)

                self.previous_mode = previous_mode
                self.current_mode = requested_mode
                self.mode_start_time = time.time()
                self.current_mode_arguments = arguments.copy()

                response.success = True
                response.message = f"Successfully switched to {requested_mode} mode"
                response.previous_mode = previous_mode
                response.current_mode = requested_mode
                self.get_logger().info(response.message)

            except Exception as e:
                self.get_logger().error(f"Mode transition failed: {e}")
                # Emergency fallback to IDLE
                try:
                    self._transition_to_idle()
                    self.current_mode = 'idle'
                except Exception:
                    pass

                response.success = False
                response.message = f"Transition failed: {e}"
                response.previous_mode = previous_mode
                response.current_mode = self.current_mode

            finally:
                self.transition_in_progress = False
                self._publish_mode_status()

        return response

    def get_mode_callback(self, request, response):
        """Handle /ugv/get_mode — report current mode status."""
        response.current_mode = self.current_mode
        response.is_active = self.current_mode != 'idle'
        response.available_modes = list(self.VALID_MODES)

        if self.mode_start_time:
            uptime = time.time() - self.mode_start_time
            self.get_logger().info(
                f"Current mode: {response.current_mode} (active for {uptime:.1f}s)"
            )

        return response

    def stop_all_callback(self, request, response):
        """Handle /ugv/stop_all — selective process and lifecycle stopping."""
        # If no flags set, stop everything (backwards compatibility)
        if not (
            request.stop_mode
            or request.stop_webrtc
            or request.stop_rosbridge
            or request.stop_background
        ):
            self.get_logger().info("Stop all: no flags set, stopping everything")
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
            self.get_logger().info(f"Stop all: stopping {', '.join(flags)}")

        errors = []
        stopped = []

        # Stop current mode (deactivate lifecycle nodes)
        if request.stop_mode:
            if self.current_mode != 'idle':
                try:
                    self._transition_to_idle()
                    self.previous_mode = self.current_mode
                    self.current_mode = 'idle'
                    self.current_mode_arguments = {}
                    stopped.append("mode (lifecycle nodes deactivated)")
                    self.get_logger().info("Mode stopped via lifecycle deactivation")
                except Exception as e:
                    errors.append(f"Failed to deactivate mode: {e}")
            else:
                self.get_logger().info("No active mode to stop")

        # Stop background processes (motors, LIDAR, TF)
        if request.stop_background:
            try:
                self.stop_background()
                # Also stop the lifecycle launch since background is gone
                self._stop_lifecycle_launch()
                stopped.append("background processes + lifecycle launch")
            except Exception as e:
                errors.append(f"Failed to stop background: {e}")

        # Stop WebRTC bridge
        if request.stop_webrtc:
            try:
                self.stop_webrtc_bridge()
                stopped.append("WebRTC bridge")
            except Exception as e:
                errors.append(f"Failed to stop WebRTC: {e}")

        # Stop ROSBridge server
        if request.stop_rosbridge:
            try:
                self.stop_rosbridge()
                stopped.append("ROSBridge server")
            except Exception as e:
                errors.append(f"Failed to stop ROSBridge: {e}")

        # Build response
        if errors:
            response.success = False
            if stopped:
                response.message = (
                    f"Stopped: {', '.join(stopped)}. Errors: {'; '.join(errors)}"
                )
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
        """Handle /ugv/save_map — save current map."""
        map_path = request.map_path

        if not map_path:
            if self.current_mode != 'mapping':
                response.success = False
                response.message = "Not in mapping mode and no map_path provided"
                self.get_logger().error(response.message)
                return response

            map_path = self.current_mode_arguments.get(
                'map_path', self.map_save_path
            )

        success, message = self._save_map(map_path)
        response.success = success
        response.message = message
        return response

    def list_maps_callback(self, request, response):
        """Handle /ugv/list_maps — list available maps in a directory."""
        maps_directory = request.maps_directory or self.maps_directory

        self.get_logger().info(f"Listing maps in: {maps_directory}")

        try:
            if not os.path.exists(maps_directory):
                response.success = False
                response.message = f"Maps directory does not exist: {maps_directory}"
                response.map_names = []
                response.map_paths = []
                return response

            if not os.path.isdir(maps_directory):
                response.success = False
                response.message = f"Path is not a directory: {maps_directory}"
                response.map_names = []
                response.map_paths = []
                return response

            map_files = {}
            for f in os.listdir(maps_directory):
                if f.endswith('.yaml'):
                    name = f[:-5]
                    yaml_path = os.path.join(maps_directory, f)
                    pgm_path = os.path.join(maps_directory, f"{name}.pgm")
                    if os.path.exists(pgm_path):
                        map_files[name] = yaml_path
                    else:
                        self.get_logger().warn(
                            f"Found {f} but missing .pgm file, skipping"
                        )

            sorted_maps = sorted(map_files.items())
            response.success = True
            response.map_names = [name for name, _ in sorted_maps]
            response.map_paths = [path for _, path in sorted_maps]
            response.message = f"Found {len(sorted_maps)} map(s) in {maps_directory}"
            self.get_logger().info(
                f"Listed {len(sorted_maps)} map(s): {response.map_names}"
            )

        except Exception as e:
            response.success = False
            response.message = f"Error listing maps: {e}"
            response.map_names = []
            response.map_paths = []
            self.get_logger().error(response.message)

        return response

    # ─────────────────────────────────────────────────────────────────────────
    # Teleop Compatibility Services
    # ─────────────────────────────────────────────────────────────────────────

    def _on_start_slam(self, request, response):
        """Switch to SLAM/mapping mode via lifecycle transitions.

        Non-blocking: runs transition in background thread to avoid
        rosbridge/rosapi timeout issues.
        """
        with self._slam_control_lock:
            if self._slam_control_in_progress:
                response.success = False
                response.message = "SLAM control already in progress"
                return response
            self._slam_control_in_progress = True

        def _do_start():
            try:
                self.get_logger().info("Starting SLAM mode (via /teleop/start_slam)...")

                with self.transition_lock:
                    self.transition_in_progress = True
                    self._publish_mode_status()
                    try:
                        self._transition_to_mapping()
                        self.previous_mode = self.current_mode
                        self.current_mode = 'mapping'
                        self.mode_start_time = time.time()
                        self.current_mode_arguments = {
                            'map_path': self.map_save_path
                        }
                        self.get_logger().info("SLAM mode started successfully")
                    except Exception as e:
                        self.get_logger().error(f"Failed to start SLAM: {e}")
                        self._slam_enabled = False
                        self._slam_started_at_ms = None
                    finally:
                        self.transition_in_progress = False
                        self._publish_mode_status()

            except Exception as exc:
                self.get_logger().error(f"Start SLAM failed: {exc}")
                self._slam_enabled = False
                self._slam_started_at_ms = None
            finally:
                with self._slam_control_lock:
                    self._slam_control_in_progress = False

        threading.Thread(target=_do_start, name="teleop_start_slam", daemon=True).start()
        response.success = True
        response.message = "Start SLAM requested"
        return response

    def _on_complete_slam(self, request, response):
        """Save map and switch to navigation mode with AMCL pose seeding.

        Synchronous: blocks until transition is complete.
        """
        try:
            if self.current_mode != 'mapping':
                response.success = False
                response.message = "SLAM (mapping mode) is not running"
                return response

            self.get_logger().info("Completing SLAM (via /teleop/complete_slam)...")

            # Get map save path
            map_path = self.current_mode_arguments.get(
                'map_path', self.map_save_path
            )

            # Capture SLAM pose BEFORE saving/deactivating
            self._capture_slam_pose()

            # Save the map
            save_success, save_message = self._save_map(map_path)
            if not save_success:
                response.success = False
                response.message = f"Failed to save map: {save_message}"
                return response

            self.get_logger().info(f"Map saved to {map_path}")

            # Transition to navigation with the saved map
            map_yaml_path = f"{map_path}.yaml"

            with self.transition_lock:
                self.transition_in_progress = True
                self._publish_mode_status()
                try:
                    # _transition_to_navigation will use the captured pose for AMCL seeding
                    # Note: _capture_slam_pose was already called above, and
                    # _transition_to_navigation checks self._last_slam_pose,
                    # but it also checks was_mapping. Since we're still in mapping
                    # mode at this point, it would try to capture again. We want to
                    # skip the redundant capture, so we do the transition steps manually.
                    self._transition_to_idle()

                    # Set map_server parameter
                    self._set_remote_parameter(
                        'map_server', 'yaml_filename', map_yaml_path
                    )

                    # Activate map_server
                    if not self.map_server_lc.configure_and_activate():
                        raise RuntimeError("Failed to activate map_server")

                    # Activate AMCL
                    if not self.amcl_lc.configure_and_activate():
                        raise RuntimeError("Failed to activate AMCL")

                    # Seed AMCL with SLAM pose
                    if self._last_slam_pose is not None:
                        time.sleep(0.5)
                        self._seed_amcl_initial_pose()

                    # Start Nav2
                    self._startup_nav2(timeout=30.0)

                    self.previous_mode = 'mapping'
                    self.current_mode = 'navigation'
                    self.mode_start_time = time.time()
                    self.current_mode_arguments = {'map_path': map_yaml_path}

                    response.success = True
                    response.message = (
                        f"Map saved to {map_path}.*; navigation started"
                    )
                    self.get_logger().info(response.message)

                except Exception as e:
                    self.get_logger().error(f"Navigation transition failed: {e}")
                    try:
                        self._transition_to_idle()
                        self.current_mode = 'idle'
                    except Exception:
                        pass
                    response.success = False
                    response.message = f"Map saved but navigation failed: {e}"

                finally:
                    self.transition_in_progress = False
                    self._publish_mode_status()

        except Exception as exc:
            self.get_logger().error(f"Complete SLAM failed: {exc}")
            response.success = False
            response.message = f"Complete SLAM failed: {exc}"

        return response

    def _on_get_slam_state(self, request, response):
        """Report SLAM state. Returns JSON in message field for compatibility."""
        running = (
            self._slam_enabled
            and self.current_mode == 'mapping'
            and self._is_slam_active()
        )
        started_at_ms = self._slam_started_at_ms if running else None

        response.success = True
        response.message = json.dumps({
            "running": bool(running),
            "startedAtMs": int(started_at_ms) if started_at_ms is not None else None,
        })
        return response

    def _on_restart_slam(self, request, response):
        """Restart SLAM via lifecycle deactivate + cleanup + configure + activate.

        Non-blocking: runs in background thread.
        """
        self.get_logger().info("Restart SLAM requested (via /teleop/restart_slam_toolbox)...")

        def _do_restart():
            with self._slam_control_lock:
                if self._slam_control_in_progress:
                    self.get_logger().warn("SLAM control already in progress, skipping restart")
                    return
                self._slam_control_in_progress = True

            try:
                with self.transition_lock:
                    self.transition_in_progress = True
                    self._publish_mode_status()
                    try:
                        # Deactivate + cleanup slam_toolbox
                        self.slam_lc.deactivate_and_cleanup()
                        time.sleep(0.5)

                        # Configure + activate slam_toolbox
                        if self.slam_lc.configure_and_activate():
                            self._slam_enabled = True
                            self._slam_started_at_ms = int(time.time() * 1000)
                            self.get_logger().info("SLAM restarted successfully")
                        else:
                            self.get_logger().error("Failed to restart SLAM")
                            self._slam_enabled = False
                            self._slam_started_at_ms = None
                    finally:
                        self.transition_in_progress = False
                        self._publish_mode_status()

            except Exception as exc:
                self.get_logger().error(f"Restart SLAM failed: {exc}")
            finally:
                with self._slam_control_lock:
                    self._slam_control_in_progress = False

        threading.Thread(target=_do_restart, name="teleop_restart_slam", daemon=True).start()
        return response

    # ─────────────────────────────────────────────────────────────────────────
    # Map Saving
    # ─────────────────────────────────────────────────────────────────────────

    def _save_map(self, map_path: str) -> tuple:
        """Save the current map using map_saver_cli.

        Returns:
            (success: bool, message: str)
        """
        try:
            self.get_logger().info(f"Saving map to: {map_path}")
            result = subprocess.run(
                ['ros2', 'run', 'nav2_map_server', 'map_saver_cli', '-f', map_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                message = f"Map saved to {map_path}.yaml and {map_path}.pgm"
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

    # ─────────────────────────────────────────────────────────────────────────
    # Background Process Management (unchanged from launch_manager_node.py)
    # ─────────────────────────────────────────────────────────────────────────

    def _start_process(self, cmd: list, description: str) -> subprocess.Popen:
        """Start a subprocess with proper process group isolation."""
        self.get_logger().info(f"Starting {description}...")
        if self.debug_mode:
            proc = subprocess.Popen(cmd, start_new_session=True)
        else:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        self.get_logger().info(f"{description} started PID: {proc.pid}")
        return proc

    def _stop_process(self, proc: subprocess.Popen, description: str, timeout: float = 10.0):
        """Stop a subprocess gracefully, then force kill."""
        if not proc:
            return
        try:
            pid = proc.pid
            self.get_logger().info(f"Stopping {description} (PID: {pid})...")
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                proc.wait(timeout=timeout)
                self.get_logger().info(f"{description} terminated cleanly")
            except subprocess.TimeoutExpired:
                self.get_logger().warn(f"{description} did not terminate, force killing...")
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
        except Exception as e:
            self.get_logger().error(f"Error stopping {description}: {e}")

    def start_background(self):
        """Start background processes (motors, LIDAR, TF)."""
        try:
            self.background_process = self._start_process(
                ['ros2', 'launch', 'ugv_launch_manager', 'background.launch.py'],
                "background processes (motors, LIDAR, TF)",
            )
        except Exception as e:
            self.get_logger().error(f"Failed to start background: {e}")
            self.background_process = None

    def stop_background(self):
        """Stop background processes."""
        self._stop_process(self.background_process, "background processes")
        self.background_process = None

    def start_rosbridge(self):
        """Start ROSBridge WebSocket server."""
        try:
            self.rosbridge_process = self._start_process(
                ['ros2', 'launch', 'ugv_launch_manager', 'rosbridge_websocket_custom.xml'],
                "ROSBridge server (with action goal cancellation)",
            )
        except Exception as e:
            self.get_logger().error(f"Failed to start ROSBridge: {e}")
            self.rosbridge_process = None

    def stop_rosbridge(self):
        """Stop ROSBridge server."""
        self._stop_process(self.rosbridge_process, "ROSBridge server", timeout=5.0)
        self.rosbridge_process = None

    def start_webrtc_bridge(self):
        """Start WebRTC ROS2 bridge."""
        try:
            self.webrtc_bridge_process = self._start_process(
                ['ros2', 'launch', 'webrtc_ros2_bridge', 'bridge.launch.py'],
                "WebRTC bridge",
            )
        except Exception as e:
            self.get_logger().error(f"Failed to start WebRTC bridge: {e}")
            self.webrtc_bridge_process = None

    def stop_webrtc_bridge(self):
        """Stop WebRTC bridge."""
        self._stop_process(self.webrtc_bridge_process, "WebRTC bridge", timeout=5.0)
        self.webrtc_bridge_process = None


def main(args=None):
    rclpy.init(args=args)
    node = ModeManagerNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        print("\nShutting down mode manager...")
    finally:
        # Clean shutdown before destroying node (logger still works)
        node.get_logger().info("Shutting down: deactivating lifecycle nodes...")
        try:
            node._transition_to_idle()
        except Exception:
            pass

        node.get_logger().info("Stopping all background services...")
        node._stop_lifecycle_launch()
        node.stop_background()
        node.stop_webrtc_bridge()
        node.stop_rosbridge()

        try:
            node.destroy_node()
        except Exception:
            pass
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
