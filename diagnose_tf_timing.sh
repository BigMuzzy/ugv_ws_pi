#!/bin/bash
# TF Timing Diagnostic - Run on Raspberry Pi
# Diagnoses clock synchronization and TF cache issues

echo "=== TF Timing and Clock Synchronization Diagnostics ==="
echo ""

echo "1. System time and ROS time..."
echo "System time: $(date '+%s.%N')"
echo "Checking ROS time from /clock topic (if sim_time is enabled):"
timeout 2 ros2 topic echo /clock --once 2>/dev/null || echo "  No /clock topic (not using sim time - this is normal for real robot)"
echo ""

echo "2. Checking timestamps from different sources..."
echo ""
echo "LiDAR scan timestamp:"
timeout 2 ros2 topic echo /scan --once 2>/dev/null | grep -A 2 "stamp:" | head -3
echo ""
echo "TF timestamp (latest):"
timeout 2 ros2 topic echo /tf --once 2>/dev/null | grep -A 2 "stamp:" | head -3
echo ""
echo "Odometry timestamp:"
timeout 2 ros2 topic echo /odom --once 2>/dev/null | grep -A 2 "stamp:" | head -3
echo ""

echo "3. TF cache information..."
timeout 3 ros2 run tf2_ros tf2_echo map base_link 2>&1 | head -10
echo ""

echo "4. Checking for time source inconsistencies..."
cat << 'PYTHON' > /tmp/check_time_sync.py
#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage
import time

class TimeChecker(Node):
    def __init__(self):
        super().__init__('time_checker')
        self.scan_sub = self.create_subscription(LaserScan, '/scan', self.scan_cb, 10)
        self.odom_sub = self.create_subscription(Odometry, '/odom', self.odom_cb, 10)
        self.tf_sub = self.create_subscription(TFMessage, '/tf', self.tf_cb, 10)
        
        self.scan_time = None
        self.odom_time = None
        self.tf_time = None
        
        self.timer = self.create_timer(2.0, self.check_times)
        self.get_logger().info("Monitoring timestamps for 10 seconds...")
        
    def to_sec(self, stamp):
        return stamp.sec + stamp.nanosec * 1e-9
    
    def scan_cb(self, msg):
        self.scan_time = self.to_sec(msg.header.stamp)
        
    def odom_cb(self, msg):
        self.odom_time = self.to_sec(msg.header.stamp)
        
    def tf_cb(self, msg):
        if msg.transforms:
            self.tf_time = self.to_sec(msg.transforms[0].header.stamp)
    
    def check_times(self):
        now = time.time()
        self.get_logger().info(f"System time: {now:.3f}")
        
        if self.scan_time:
            diff = now - self.scan_time
            self.get_logger().info(f"  Scan time: {self.scan_time:.3f} (diff: {diff:.3f}s)")
            if abs(diff) > 1.0:
                self.get_logger().error(f"  ⚠️  SCAN TIMESTAMP IS {abs(diff):.1f}s OFF!")
                
        if self.odom_time:
            diff = now - self.odom_time
            self.get_logger().info(f"  Odom time: {self.odom_time:.3f} (diff: {diff:.3f}s)")
            if abs(diff) > 1.0:
                self.get_logger().error(f"  ⚠️  ODOM TIMESTAMP IS {abs(diff):.1f}s OFF!")
                
        if self.tf_time:
            diff = now - self.tf_time
            self.get_logger().info(f"  TF time:   {self.tf_time:.3f} (diff: {diff:.3f}s)")
            if abs(diff) > 1.0:
                self.get_logger().error(f"  ⚠️  TF TIMESTAMP IS {abs(diff):.1f}s OFF!")

def main():
    rclpy.init()
    node = TimeChecker()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
PYTHON

chmod +x /tmp/check_time_sync.py
echo "Running timestamp checker for 10 seconds..."
timeout 10 python3 /tmp/check_time_sync.py 2>&1 || echo "Could not run time checker"
echo ""

echo "5. Checking use_sim_time parameter..."
ros2 param get /controller_server use_sim_time 2>/dev/null || echo "  Controller server not running"
ros2 param get /global_costmap/global_costmap use_sim_time 2>/dev/null || echo "  Costmap not running"
echo ""

echo "=== Common Issues and Fixes ==="
echo ""
echo "Issue: 'timestamp is earlier than all data in transform cache'"
echo "  Cause 1: Sensor using hardware timestamps, TF using system time"
echo "  Fix: Configure sensor driver to use system time (ros::Time::now())"
echo ""
echo "  Cause 2: TF buffer size too small (default 10 seconds)"
echo "  Fix: Increase tf_buffer_duration in costmap configs to 30.0"
echo ""
echo "  Cause 3: Clock not synchronized (NTP issues)"
echo "  Fix: Check 'timedatectl status' and enable NTP"
echo ""
echo "  Cause 4: use_sim_time mismatch between nodes"
echo "  Fix: Ensure all nodes have same use_sim_time setting (should be false for real robot)"
echo ""
