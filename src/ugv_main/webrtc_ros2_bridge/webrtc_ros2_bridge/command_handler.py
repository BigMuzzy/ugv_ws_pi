"""Command handler for publishing cmd_vel messages to ROS2."""
import time
import threading

from geometry_msgs.msg import Twist


class CommandHandler:
    """Handle velocity commands and publish to ROS2 cmd_vel topic."""

    def __init__(
        self,
        node,
        topic="/cmd_vel",
        max_linear=1.0,
        max_angular=2.0,
        timeout_ms=500,
        publish_rate_hz=20
    ):
        """
        Initialize the command handler.

        Args:
            node: ROS2 node instance
            topic: Topic name for cmd_vel
            max_linear: Maximum linear velocity (m/s)
            max_angular: Maximum angular velocity (rad/s)
            timeout_ms: Command timeout in milliseconds
            publish_rate_hz: Rate at which to publish commands
        """
        self._node = node
        self._max_linear = max_linear
        self._max_angular = max_angular
        self._timeout_ms = timeout_ms
        self._publish_rate_hz = publish_rate_hz

        # Create publisher
        self._publisher = node.create_publisher(Twist, topic, 10)

        # Current command state
        self._current_twist = Twist()
        self._last_command_time = 0.0
        self._lock = threading.Lock()

        # Emergency stop state
        self._emergency_stop = False

        # Start publish timer
        period = 1.0 / publish_rate_hz
        self._timer = node.create_timer(period, self._publish_callback)

        node.get_logger().info(
            f"CommandHandler initialized on topic {topic} "
            f"(max_linear={max_linear}, max_angular={max_angular})"
        )

    def process_command(self, linear_x, linear_y, linear_z,
                        angular_x, angular_y, angular_z):
        """
        Process a velocity command from the WebRTC data channel.

        Args:
            linear_x: Linear velocity in x direction
            linear_y: Linear velocity in y direction
            linear_z: Linear velocity in z direction
            angular_x: Angular velocity around x axis
            angular_y: Angular velocity around y axis
            angular_z: Angular velocity around z axis
        """
        if self._emergency_stop:
            self._node.get_logger().warning("Emergency stop active, ignoring command")
            return

        # Clamp values to limits
        linear_x = self._clamp(linear_x, -self._max_linear, self._max_linear)
        linear_y = self._clamp(linear_y, -self._max_linear, self._max_linear)
        linear_z = self._clamp(linear_z, -self._max_linear, self._max_linear)
        angular_x = self._clamp(angular_x, -self._max_angular, self._max_angular)
        angular_y = self._clamp(angular_y, -self._max_angular, self._max_angular)
        angular_z = self._clamp(angular_z, -self._max_angular, self._max_angular)

        with self._lock:
            self._current_twist.linear.x = float(linear_x)
            self._current_twist.linear.y = float(linear_y)
            self._current_twist.linear.z = float(linear_z)
            self._current_twist.angular.x = float(angular_x)
            self._current_twist.angular.y = float(angular_y)
            self._current_twist.angular.z = float(angular_z)
            self._last_command_time = time.time()

    def set_emergency_stop(self, active):
        """
        Set emergency stop state.

        Args:
            active: True to activate emergency stop, False to deactivate
        """
        self._emergency_stop = active
        if active:
            self._stop()
            self._node.get_logger().warning("Emergency stop activated!")
        else:
            self._node.get_logger().info("Emergency stop deactivated")

    def _stop(self):
        """Send stop command (zero velocity)."""
        with self._lock:
            self._current_twist = Twist()
        self._publisher.publish(Twist())

    def _publish_callback(self):
        """Timer callback to publish velocity commands."""
        current_time = time.time()

        with self._lock:
            time_since_last = (current_time - self._last_command_time) * 1000

            # Check for timeout
            if time_since_last > self._timeout_ms and self._last_command_time > 0:
                # Stop robot if no recent commands
                if (self._current_twist.linear.x != 0 or
                        self._current_twist.linear.y != 0 or
                        self._current_twist.angular.z != 0):
                    self._node.get_logger().info(
                        "Command timeout - stopping robot"
                    )
                    self._current_twist = Twist()

            # Publish current twist (or zero if stopped)
            self._publisher.publish(self._current_twist)

    @staticmethod
    def _clamp(value, min_val, max_val):
        """Clamp a value between min and max."""
        return max(min_val, min(max_val, value))

    def destroy(self):
        """Clean up resources."""
        if self._timer:
            self._timer.cancel()
        self._stop()
