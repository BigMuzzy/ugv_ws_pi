#!/usr/bin/env python3
"""
Map Republisher Node

Republishes the /map topic periodically so web clients reliably receive it.

Problem:
- nav2_map_server publishes /map with transient-local durability (latched).
- Some rosbridge/roslibjs setups won't deliver the already-latched sample to a
  newly connected browser client, so after a UI refresh it can look like there's
  no map.

Solution:
- Subscribe to /map with transient-local durability to receive the cached map.
- Periodically republish the map with updated timestamps.
- This ensures new web clients always get the map quickly (within ~1 second).

Note: This is only needed during navigation mode with a static map.
During SLAM, slam_toolbox continuously publishes /map updates.
"""

from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from nav_msgs.msg import OccupancyGrid, MapMetaData


class MapRepublisherNode(Node):
    """Node that republishes the /map topic for web client compatibility."""

    def __init__(self):
        super().__init__('map_republisher')

        # Declare parameters
        self.declare_parameter('publish_rate', 1.0)  # Hz
        self.declare_parameter('input_map_topic', '/map')
        self.declare_parameter('input_metadata_topic', '/map_metadata')

        publish_rate = self.get_parameter('publish_rate').value
        input_map_topic = self.get_parameter('input_map_topic').value
        input_metadata_topic = self.get_parameter('input_metadata_topic').value

        # Cached messages
        self._last_map: Optional[OccupancyGrid] = None
        self._last_metadata: Optional[MapMetaData] = None
        self._map_received = False

        # QoS profile for subscribing - transient_local to receive latched messages
        sub_qos = QoSProfile(depth=1)
        sub_qos.reliability = ReliabilityPolicy.RELIABLE
        sub_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        # QoS profile for publishing - also transient_local for compatibility
        # with consumers like AMCL that expect transient_local
        pub_qos = QoSProfile(depth=1)
        pub_qos.reliability = ReliabilityPolicy.RELIABLE
        pub_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        # Create subscribers
        self._map_sub = self.create_subscription(
            OccupancyGrid,
            input_map_topic,
            self._on_map,
            sub_qos
        )
        self._metadata_sub = self.create_subscription(
            MapMetaData,
            input_metadata_topic,
            self._on_metadata,
            sub_qos
        )

        # Create publishers - republish on the same topics
        # The republished messages will have updated timestamps
        self._map_pub = self.create_publisher(OccupancyGrid, input_map_topic, pub_qos)
        self._metadata_pub = self.create_publisher(MapMetaData, input_metadata_topic, pub_qos)

        # Timer for periodic republishing
        period = 1.0 / max(0.1, float(publish_rate))
        self._timer = self.create_timer(period, self._republish)

        self.get_logger().info(
            f"Map republisher started: republishing {input_map_topic} @ {publish_rate:.2f} Hz"
        )

    def _on_map(self, msg: OccupancyGrid) -> None:
        """Cache received map message."""
        self._last_map = msg
        if not self._map_received:
            self._map_received = True
            self.get_logger().info(
                f"Received map: {msg.info.width}x{msg.info.height} @ "
                f"{msg.info.resolution:.3f} m/px"
            )

    def _on_metadata(self, msg: MapMetaData) -> None:
        """Cache received map metadata message."""
        self._last_metadata = msg

    def _republish(self) -> None:
        """Republish cached map with updated timestamp."""
        if self._last_map is None:
            return

        # Update timestamp to current time
        # Some consumers care about timestamp monotonicity
        self._last_map.header.stamp = self.get_clock().now().to_msg()
        self._map_pub.publish(self._last_map)

        if self._last_metadata is not None:
            # MapMetaData has no header, just publish it
            self._metadata_pub.publish(self._last_metadata)


def main(args=None):
    rclpy.init(args=args)
    node = MapRepublisherNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
