"""ROS2 node for WebRTC-ROS2 bridge."""
import asyncio
import os
import threading

import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import ParameterDescriptor
from ament_index_python.packages import get_package_share_directory

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from .command_handler import CommandHandler
from .signaling_server import SignalingServer, AIOHTTP_AVAILABLE
from .webrtc_manager import AIORTC_AVAILABLE
from .sfu_client import CloudflareSFUClient


class WebRTCBridgeNode(Node):
    """ROS2 node for WebRTC teleoperation bridge."""

    def __init__(self):
        """Initialize the WebRTC bridge node."""
        super().__init__("webrtc_bridge")

        # Declare parameters
        self._declare_parameters()

        # Get configuration
        config = self._load_config()

        # Get parameter values
        robot_config = config.get("robot", {})
        video_config = config.get("video", {})
        webrtc_config = config.get("webrtc", {})
        server_config = config.get("server", {})

        # Initialize command handler
        self._command_handler = CommandHandler(
            node=self,
            topic=robot_config.get("cmd_vel_topic", "/cmd_vel"),
            max_linear=robot_config.get("max_linear_speed", 1.0),
            max_angular=robot_config.get("max_angular_speed", 2.0),
            timeout_ms=robot_config.get("command_timeout_ms", 500),
            publish_rate_hz=robot_config.get("publish_rate_hz", 20)
        )

        # Check mode: SFU or P2P
        sfu_config = config.get("sfu", {})
        use_sfu = sfu_config.get("enabled", False)
        
        self._sfu_client = None
        self._server = None
        self._loop = None
        self._loop_thread = None

        if use_sfu:
            # SFU mode - connect to Cloudflare Calls via Workers
            self.get_logger().info("Using SFU mode (Cloudflare Calls)")
            self._init_sfu_mode(sfu_config, video_config, webrtc_config)
        else:
            # P2P mode - traditional signaling server
            self.get_logger().info("Using P2P mode (signaling server)")
            self._init_p2p_mode(video_config, webrtc_config, server_config)

        # Start async event loop in separate thread
        if self._server or self._sfu_client:
            self._start_async_loop()

        self.get_logger().info("WebRTC Bridge Node initialized")

        if not AIORTC_AVAILABLE:
            self.get_logger().warning(
                "aiortc not available - WebRTC features disabled. "
                "Install with: pip install aiortc"
            )

    def _declare_parameters(self):
        """Declare ROS2 parameters."""
        # Server parameters
        self.declare_parameter(
            "server.host",
            "0.0.0.0",
            ParameterDescriptor(description="Signaling server host")
        )
        self.declare_parameter(
            "server.port",
            8080,
            ParameterDescriptor(description="Signaling server port")
        )

        # Video parameters
        self.declare_parameter(
            "video.device",
            "/dev/video0",
            ParameterDescriptor(description="Camera device")
        )
        self.declare_parameter(
            "video.width",
            640,
            ParameterDescriptor(description="Video width")
        )
        self.declare_parameter(
            "video.height",
            480,
            ParameterDescriptor(description="Video height")
        )
        self.declare_parameter(
            "video.fps",
            30,
            ParameterDescriptor(description="Video FPS")
        )

        # Robot parameters
        self.declare_parameter(
            "robot.cmd_vel_topic",
            "/cmd_vel",
            ParameterDescriptor(description="cmd_vel topic name")
        )
        self.declare_parameter(
            "robot.max_linear_speed",
            1.0,
            ParameterDescriptor(description="Maximum linear speed")
        )
        self.declare_parameter(
            "robot.max_angular_speed",
            2.0,
            ParameterDescriptor(description="Maximum angular speed")
        )
        self.declare_parameter(
            "robot.command_timeout_ms",
            500,
            ParameterDescriptor(description="Command timeout in ms")
        )
        self.declare_parameter(
            "robot.publish_rate_hz",
            20,
            ParameterDescriptor(description="Publish rate in Hz")
        )

        # Config file parameter
        self.declare_parameter(
            "config_file",
            "",
            ParameterDescriptor(description="Path to configuration file")
        )

        # SFU mode parameters
        self.declare_parameter(
            "sfu.enabled",
            False,
            ParameterDescriptor(description="Enable SFU mode (Cloudflare Calls)")
        )
        self.declare_parameter(
            "sfu.robot_id",
            "robot_01",
            ParameterDescriptor(description="Unique robot identifier")
        )
        self.declare_parameter(
            "sfu.workers_endpoint",
            "https://fleet-workers.mssemyonov.workers.dev",
            ParameterDescriptor(description="Cloudflare Workers endpoint URL")
        )
        self.declare_parameter(
            "sfu.fallback_to_p2p",
            True,
            ParameterDescriptor(description="Fallback to P2P if SFU fails")
        )

    def _load_config(self):
        """Load configuration from file or parameters."""
        config = {
            "server": {
                "host": self.get_parameter("server.host").value,
                "port": self.get_parameter("server.port").value,
            },
            "video": {
                "device": self.get_parameter("video.device").value,
                "width": self.get_parameter("video.width").value,
                "height": self.get_parameter("video.height").value,
                "fps": self.get_parameter("video.fps").value,
            },
            "robot": {
                "cmd_vel_topic": self.get_parameter("robot.cmd_vel_topic").value,
                "max_linear_speed": self.get_parameter("robot.max_linear_speed").value,
                "max_angular_speed": self.get_parameter("robot.max_angular_speed").value,
                "command_timeout_ms": self.get_parameter("robot.command_timeout_ms").value,
                "publish_rate_hz": self.get_parameter("robot.publish_rate_hz").value,
            },
            "webrtc": {
                "stun_servers": [
                    "stun:stun.l.google.com:19302",
                    "stun:stun1.l.google.com:19302",
                    "stun:stun.relay.metered.ca:80"
                ],
                # Metered.ca TURN servers (free tier) for NAT traversal
                "turn_servers": [
                    {
                        "url": "turn:global.relay.metered.ca:80",
                        "username": "bbded4f052d4c3c9e8e6342f",
                        "credential": "UWI3yEJTIVm+nT0J"
                    },
                    {
                        "url": "turn:global.relay.metered.ca:80?transport=tcp",
                        "username": "bbded4f052d4c3c9e8e6342f",
                        "credential": "UWI3yEJTIVm+nT0J"
                    },
                    {
                        "url": "turn:global.relay.metered.ca:443",
                        "username": "bbded4f052d4c3c9e8e6342f",
                        "credential": "UWI3yEJTIVm+nT0J"
                    },
                    {
                        "url": "turns:global.relay.metered.ca:443?transport=tcp",
                        "username": "bbded4f052d4c3c9e8e6342f",
                        "credential": "UWI3yEJTIVm+nT0J"
                    }
                ],
            },
            "sfu": {
                "enabled": self.get_parameter("sfu.enabled").value,
                "robot_id": self.get_parameter("sfu.robot_id").value,
                "workers_endpoint": self.get_parameter("sfu.workers_endpoint").value,
                "fallback_to_p2p": self.get_parameter("sfu.fallback_to_p2p").value,
            }
        }

        # Try to load from config file if specified
        config_file = self.get_parameter("config_file").value
        if config_file and YAML_AVAILABLE:
            if os.path.exists(config_file):
                try:
                    with open(config_file, "r") as f:
                        file_config = yaml.safe_load(f)
                        if file_config:
                            # Merge file config with parameter config
                            for key in file_config:
                                if key in config:
                                    config[key].update(file_config[key])
                                else:
                                    config[key] = file_config[key]
                    self.get_logger().info(f"Loaded config from {config_file}")
                except Exception as e:
                    self.get_logger().warning(f"Failed to load config file: {e}")

        return config

    def _get_static_dir(self):
        """Get path to static files directory."""
        try:
            share_dir = get_package_share_directory("webrtc_ros2_bridge")
            static_dir = os.path.join(share_dir, "static")
            if os.path.isdir(static_dir):
                return static_dir
        except Exception:
            pass

        # Fall back to looking relative to this file
        package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        static_dir = os.path.join(package_dir, "static")
        if os.path.isdir(static_dir):
            return static_dir

        return None

    def _init_sfu_mode(self, sfu_config, video_config, webrtc_config):
        """Initialize SFU mode with Cloudflare Calls."""
        if not AIORTC_AVAILABLE:
            self.get_logger().error(
                "aiortc not available - SFU mode disabled. Install with: pip install aiortc"
            )
            if sfu_config.get("fallback_to_p2p", True):
                self.get_logger().warning("Falling back to P2P mode")
                server_config = {"host": "0.0.0.0", "port": 8080}
                self._init_p2p_mode(video_config, webrtc_config, server_config)
            return

        robot_id = sfu_config.get(\"robot_id\", \"robot_01\")
        workers_endpoint = sfu_config.get(\"workers_endpoint\", \"https://fleet-workers.mssemyonov.workers.dev\")
        
        self.get_logger().info(f\"Initializing SFU client for robot: {robot_id}\")
        self.get_logger().info(f\"Workers endpoint: {workers_endpoint}\")
        
        # Note: Video track will be set up in async loop after VideoSource is created
        self._sfu_client = CloudflareSFUClient(
            robot_id=robot_id,
            workers_endpoint=workers_endpoint,
            video_track=None,  # Will be set later
            on_command=self._on_sfu_command,
            on_emergency_stop=self._on_sfu_emergency_stop,
            logger=self.get_logger(),
            fallback_mode=False
        )
        
        # Store config for later use
        self._video_config = video_config
        self._sfu_config = sfu_config

    def _init_p2p_mode(self, video_config, webrtc_config, server_config):
        \"\"\"Initialize P2P mode with signaling server.\"\"\"
        # Get static files directory
        static_dir = self._get_static_dir()

        # Initialize signaling server
        if AIOHTTP_AVAILABLE:
            self._server = SignalingServer(
                host=server_config.get(\"host\", \"0.0.0.0\"),
                port=server_config.get(\"port\", 8080),
                static_dir=static_dir,
                on_command=self._on_command,
                on_emergency_stop=self._on_emergency_stop,
                video_config=video_config,
                webrtc_config=webrtc_config,
                logger=self.get_logger()
            )
        else:
            self._server = None
            self.get_logger().error(
                "aiohttp not available - signaling server disabled"
            )

    def _start_async_loop(self):
        """Start asyncio event loop in separate thread."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            # Start server (P2P mode) or connect SFU client
            if self._server:
                self._loop.run_until_complete(self._server.start())
            elif self._sfu_client:
                # Connect to SFU in async loop
                async def connect_sfu():
                    success = await self._sfu_client.connect()
                    if not success:
                        self.get_logger().error(\"Failed to connect to SFU\")
                        if self._sfu_config.get(\"fallback_to_p2p\", True):
                            self.get_logger().warning(\"Falling back to P2P mode\")
                            # TODO: Implement P2P fallback here
                
                self._loop.run_until_complete(connect_sfu())

            # Run event loop
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

    def _on_sfu_command(self, linear, angular):
        \"\"\"Handle velocity command from SFU DataChannel.\"\"\"
        # SFU sends simplified commands (linear, angular only)
        self._command_handler.process_command(
            linear, 0.0, 0.0,  # linear x, y, z
            0.0, 0.0, angular  # angular x, y, z
        )

    def _on_sfu_emergency_stop(self):
        \"\"\"Handle emergency stop from SFU.\"\"\"
        self._command_handler.set_emergency_stop(True)

    def _on_command(self, linear_x, linear_y, linear_z,
                    angular_x, angular_y, angular_z):
        """Handle velocity command from WebRTC."""
        self._command_handler.process_command(
            linear_x, linear_y, linear_z,
            angular_x, angular_y, angular_z
        )

    def _on_emergency_stop(self, active):
        """Handle emergency stop from WebRTC."""
        self._command_handler.set_emergency_stop(active)

    def destroy_node(self):
        """Clean up resources."""
        # Stop server or SFU client
        if self._loop:
            if self._server:
                asyncio.run_coroutine_threadsafe(
                    self._server.stop(),
                    self._loop
                ).result(timeout=5.0)
            elif self._sfu_client:
                asyncio.run_coroutine_threadsafe(
                    self._sfu_client.disconnect(),
                    self._loop
                ).result(timeout=5.0)

            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._loop_thread:
                self._loop_thread.join(timeout=2.0)

        # Clean up command handler
        if self._command_handler:
            self._command_handler.destroy()

        super().destroy_node()


def main(args=None):
    """Main entry point."""
    rclpy.init(args=args)

    node = WebRTCBridgeNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
