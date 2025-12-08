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
from .cloudflare_calls import CloudflareCallsClient
from .signaling_client import SignalingClient
from .rosbridge_proxy import IntegratedSignalingClient
from .sfu_manager import SFUManager
from .video_source import VideoSource


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
        fleet_config = config.get("fleet", {})
        cloudflare_config = config.get("cloudflare", {})

        # Initialize command handler
        self._command_handler = CommandHandler(
            node=self,
            topic=robot_config.get("cmd_vel_topic", "/cmd_vel"),
            max_linear=robot_config.get("max_linear_speed", 1.0),
            max_angular=robot_config.get("max_angular_speed", 2.0),
            timeout_ms=robot_config.get("command_timeout_ms", 500),
            publish_rate_hz=robot_config.get("publish_rate_hz", 20)
        )

        # Get static files directory
        static_dir = self._get_static_dir()

        # Initialize Video Source (Shared if possible, but for now separate if needed)
        # If we use SFU, we need a video source.
        self._video_source = None
        
        # Log configuration for debugging
        self.get_logger().info(f"Fleet config: worker_url={fleet_config.get('worker_url')}, robot_id={fleet_config.get('robot_id')}")
        self.get_logger().info(f"Cloudflare config: app_id={'***' if cloudflare_config.get('app_id') else '(not set)'}")
        
        if cloudflare_config.get("app_id"):
             self._video_source = VideoSource(
                device=video_config.get("device", "/dev/video0"),
                width=video_config.get("width", 640),
                height=video_config.get("height", 480),
                fps=video_config.get("fps", 30),
                logger=self.get_logger()
            )

        # Initialize Cloudflare Calls Client
        self._calls_client = None
        self._sfu_manager = None
        if cloudflare_config.get("app_id"):
            self.get_logger().info("Initializing Cloudflare Calls client...")
            self._calls_client = CloudflareCallsClient(
                app_id=cloudflare_config.get("app_id"),
                app_token=cloudflare_config.get("app_token"),
                logger=self.get_logger()
            )
            self._sfu_manager = SFUManager(
                calls_client=self._calls_client,
                video_source=self._video_source,
                on_command=self._on_command,
                logger=self.get_logger()
            )
        else:
            self.get_logger().warning(
                "Cloudflare app_id not configured! Set CLOUDFLARE_APP_ID and CLOUDFLARE_APP_TOKEN "
                "environment variables or configure in bridge_config.yaml"
            )

        # Initialize Signaling Client (Fleet) with ROSBridge proxy
        self._signaling_client = None
        if fleet_config.get("worker_url") and self._calls_client:
            # Check if rosbridge proxy should be enabled
            enable_rosbridge_proxy = fleet_config.get("enable_rosbridge_proxy", True)
            rosbridge_url = fleet_config.get("rosbridge_url", "ws://localhost:9090")
            
            self.get_logger().info(f"Initializing Fleet signaling client to {fleet_config.get('worker_url')}...")
            self.get_logger().info(f"ROSBridge proxy: {'enabled' if enable_rosbridge_proxy else 'disabled'}, URL: {rosbridge_url}")
            
            self._signaling_client = IntegratedSignalingClient(
                worker_url=fleet_config.get("worker_url"),
                robot_id=fleet_config.get("robot_id", "robot1"),
                calls_client=self._calls_client,
                rosbridge_url=rosbridge_url,
                on_subscribe_cmd=self._on_subscribe_cmd,
                get_video_track_name=self._get_video_track_name,
                enable_rosbridge_proxy=enable_rosbridge_proxy,
                logger=self.get_logger()
            )
        elif fleet_config.get("worker_url") and not self._calls_client:
            self.get_logger().warning(
                "Fleet worker_url is configured but Cloudflare client not initialized - "
                "signaling client disabled"
            )

        # Start async event loop in separate thread
        self._loop = None
        self._loop_thread = None
        if self._signaling_client:
            self._start_async_loop()

        self.get_logger().info("WebRTC Bridge Node initialized")

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
        
        # Fleet parameters
        self.declare_parameter("fleet.worker_url", "", ParameterDescriptor(description="Fleet Worker WebSocket URL"))
        self.declare_parameter("fleet.robot_id", "robot1", ParameterDescriptor(description="Robot ID"))
        
        # Cloudflare parameters
        self.declare_parameter("cloudflare.app_id", "", ParameterDescriptor(description="Cloudflare Calls App ID"))
        self.declare_parameter("cloudflare.app_token", "", ParameterDescriptor(description="Cloudflare Calls App Token"))

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
            "fleet": {
                "worker_url": self.get_parameter("fleet.worker_url").value,
                "robot_id": self.get_parameter("fleet.robot_id").value,
            },
            "cloudflare": {
                "app_id": self.get_parameter("cloudflare.app_id").value,
                "app_token": self.get_parameter("cloudflare.app_token").value,
            },
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

        # Environment variables take highest precedence (override everything)
        env_fleet_url = os.environ.get("FLEET_WORKER_URL")
        env_robot_id = os.environ.get("ROBOT_ID")
        env_app_id = os.environ.get("CLOUDFLARE_APP_ID")
        env_app_token = os.environ.get("CLOUDFLARE_APP_TOKEN")
        
        if env_fleet_url:
            config["fleet"]["worker_url"] = env_fleet_url
        if env_robot_id:
            config["fleet"]["robot_id"] = env_robot_id
        if env_app_id:
            config["cloudflare"]["app_id"] = env_app_id
        if env_app_token:
            config["cloudflare"]["app_token"] = env_app_token

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

    def _start_async_loop(self):
        """Start asyncio event loop in separate thread."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            # Run initialization
            self._loop.run_until_complete(self._async_init())

            # Run event loop
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

    async def _async_init(self):
        """Initialize async components."""
        if self._calls_client:
            try:
                self.get_logger().info(f"Initializing Cloudflare Calls with App ID: {self._calls_client.app_id[:4]}...")
                await self._calls_client.create_session()
                if self._sfu_manager:
                    await self._sfu_manager.connect()
            except Exception as e:
                self.get_logger().error(f"Failed to initialize Cloudflare Calls: {e}")

        if self._signaling_client:
            # Start signaling client in background
            self.get_logger().info(f"Starting Signaling Client to {self._signaling_client.worker_url}")
            asyncio.create_task(self._signaling_client.start())

    async def _on_subscribe_cmd(self, session_id, channel):
        """Handle subscribe command from Fleet Worker."""
        self.get_logger().info(f"Subscribing to remote channel {channel} from session {session_id}")
        if self._sfu_manager:
            try:
                # Use SFUManager to subscribe to the remote DataChannel
                # This handles the full SDP renegotiation
                success = await self._sfu_manager.subscribe_to_datachannel(
                    remote_session_id=session_id,
                    channel_name=channel
                )
                if success:
                    self.get_logger().info(f"Successfully subscribed to channel {channel}")
                else:
                    self.get_logger().error(f"Failed to subscribe to channel {channel}")
            except Exception as e:
                self.get_logger().error(f"Failed to subscribe to channel: {e}")

    def _get_video_track_name(self):
        """Get the video track name from SFU manager for signaling."""
        if self._sfu_manager:
            return self._sfu_manager.video_track_name
        return None

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
        # Stop async loop
        if self._loop:
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
