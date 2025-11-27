"""Unit tests for command handler module."""
import unittest
from unittest.mock import MagicMock, patch
import time

# Check if ROS2 packages are available
try:
    from geometry_msgs.msg import Twist
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False


class TestCommandHandler(unittest.TestCase):
    """Test cases for CommandHandler class."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock ROS2 node
        self.mock_node = MagicMock()
        self.mock_node.create_publisher = MagicMock(return_value=MagicMock())
        self.mock_node.create_timer = MagicMock(return_value=MagicMock())
        self.mock_node.get_logger = MagicMock(return_value=MagicMock())

    @unittest.skipUnless(ROS2_AVAILABLE, "ROS2 packages not available")
    def test_command_handler_import(self):
        """Test that command handler can be imported."""
        try:
            from webrtc_ros2_bridge.command_handler import CommandHandler
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Failed to import CommandHandler: {e}")

    @unittest.skipUnless(ROS2_AVAILABLE, "ROS2 packages not available")
    def test_clamp_function(self):
        """Test the clamp utility function."""
        from webrtc_ros2_bridge.command_handler import CommandHandler

        # Test clamp method
        self.assertEqual(CommandHandler._clamp(0.5, 0, 1), 0.5)
        self.assertEqual(CommandHandler._clamp(1.5, 0, 1), 1)
        self.assertEqual(CommandHandler._clamp(-0.5, 0, 1), 0)
        self.assertEqual(CommandHandler._clamp(-1.5, -1, 1), -1)

    @unittest.skipUnless(ROS2_AVAILABLE, "ROS2 packages not available")
    def test_command_handler_initialization(self):
        """Test CommandHandler initialization."""
        from webrtc_ros2_bridge.command_handler import CommandHandler

        handler = CommandHandler(
            node=self.mock_node,
            topic="/test_cmd_vel",
            max_linear=2.0,
            max_angular=3.0,
            timeout_ms=1000,
            publish_rate_hz=10
        )

        # Verify publisher was created
        self.mock_node.create_publisher.assert_called_once()

        # Verify timer was created
        self.mock_node.create_timer.assert_called_once()

        # Clean up
        handler.destroy()

    @unittest.skipUnless(ROS2_AVAILABLE, "ROS2 packages not available")
    def test_process_command_clamping(self):
        """Test that commands are clamped to limits."""
        from webrtc_ros2_bridge.command_handler import CommandHandler

        handler = CommandHandler(
            node=self.mock_node,
            max_linear=1.0,
            max_angular=2.0
        )

        # Test command that exceeds limits
        handler.process_command(5.0, 0, 0, 0, 0, 10.0)

        # The values should be clamped
        self.assertLessEqual(handler._current_twist.linear.x, 1.0)
        self.assertLessEqual(handler._current_twist.angular.z, 2.0)

        handler.destroy()

    @unittest.skipUnless(ROS2_AVAILABLE, "ROS2 packages not available")
    def test_emergency_stop(self):
        """Test emergency stop functionality."""
        from webrtc_ros2_bridge.command_handler import CommandHandler

        handler = CommandHandler(node=self.mock_node)

        # Set some velocity
        handler.process_command(0.5, 0, 0, 0, 0, 0.5)

        # Activate emergency stop
        handler.set_emergency_stop(True)
        self.assertTrue(handler._emergency_stop)

        # Commands should be ignored during emergency stop
        handler.process_command(1.0, 0, 0, 0, 0, 1.0)
        self.assertEqual(handler._current_twist.linear.x, 0.0)
        self.assertEqual(handler._current_twist.angular.z, 0.0)

        # Deactivate emergency stop
        handler.set_emergency_stop(False)
        self.assertFalse(handler._emergency_stop)

        handler.destroy()


class TestVideoSource(unittest.TestCase):
    """Test cases for VideoSource class."""

    def test_video_source_import(self):
        """Test that video source can be imported."""
        try:
            from webrtc_ros2_bridge.video_source import VideoSource
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Failed to import VideoSource: {e}")

    def test_test_pattern_creation(self):
        """Test test pattern creation."""
        from webrtc_ros2_bridge.video_source import create_test_pattern

        try:
            import numpy as np

            pattern = create_test_pattern(640, 480)
            if pattern is not None:
                self.assertEqual(pattern.shape, (480, 640, 3))
                self.assertEqual(pattern.dtype, np.uint8)
        except ImportError:
            # numpy not available, skip test
            self.skipTest("numpy not available")

    def test_video_source_properties(self):
        """Test VideoSource properties."""
        from webrtc_ros2_bridge.video_source import VideoSource

        source = VideoSource(
            device="/dev/video0",
            width=640,
            height=480,
            fps=30
        )

        self.assertEqual(source.width, 640)
        self.assertEqual(source.height, 480)
        self.assertEqual(source.fps, 30)
        self.assertFalse(source.is_running)


class TestWebRTCManager(unittest.TestCase):
    """Test cases for WebRTCManager class."""

    def test_webrtc_manager_import(self):
        """Test that WebRTC manager can be imported."""
        try:
            from webrtc_ros2_bridge.webrtc_manager import WebRTCManager
            self.assertTrue(True)
        except ImportError as e:
            self.fail(f"Failed to import WebRTCManager: {e}")

    def test_webrtc_manager_initialization(self):
        """Test WebRTCManager initialization."""
        from webrtc_ros2_bridge.webrtc_manager import WebRTCManager

        callback_called = False

        def on_command(*args):
            nonlocal callback_called
            callback_called = True

        manager = WebRTCManager(
            stun_servers=["stun:stun.l.google.com:19302"],
            on_command=on_command
        )

        self.assertEqual(manager.peer_count, 0)
        self.assertEqual(manager.connected_peers, [])


class TestSignalingServer(unittest.TestCase):
    """Test cases for SignalingServer class."""

    def test_signaling_server_import(self):
        """Test that signaling server can be imported."""
        try:
            from webrtc_ros2_bridge.signaling_server import SignalingServer
            self.assertTrue(True)
        except ImportError as e:
            # aiohttp might not be available
            if "aiohttp" in str(e):
                self.skipTest("aiohttp not available")
            self.fail(f"Failed to import SignalingServer: {e}")


if __name__ == '__main__':
    unittest.main()
