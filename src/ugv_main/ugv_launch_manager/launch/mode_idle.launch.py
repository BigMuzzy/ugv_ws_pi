#!/usr/bin/env python3
"""
Idle Mode Launch File
Launches minimal teleoperation support (motor control, TF frames)
No camera, no LIDAR, no SLAM, no navigation
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """Generate launch description for idle mode - teleoperation only"""
    
    # Get the URDF model path
    UGV_MODEL = os.environ.get('UGV_MODEL', 'ugv_beast')
    urdf_file_name = UGV_MODEL + '.urdf'
    urdf_model_path = os.path.join(
        get_package_share_directory('ugv_description'),
        'urdf',
        urdf_file_name
    )

    # Declare launch arguments
    pub_odom_tf_arg = DeclareLaunchArgument(
        'pub_odom_tf',
        default_value='true',
        description='Whether to publish the tf from odom to base_footprint'
    )

    # Robot state publisher node - publishes TF from URDF
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        namespace='ugv',
        arguments=[urdf_model_path]
    )

    # Joint state publisher node - publishes joint states
    joint_state_publisher_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        namespace='ugv',
        name='joint_state_publisher',
        arguments=[urdf_model_path]
    )

    # Bringup node for robot initialization
    bringup_node = Node(
        package='ugv_bringup',
        executable='ugv_bringup',
    )

    # Driver node for motor control
    driver_node = Node(
        package='ugv_bringup',
        executable='ugv_driver',
    )

    # Base node for cmd_vel control - handles teleoperation
    base_node = Node(
        package='ugv_base_node',
        executable='base_node',
        parameters=[{'pub_odom_tf': LaunchConfiguration('pub_odom_tf')}]
    )

    return LaunchDescription([
        pub_odom_tf_arg,
        # Robot state and joint state publishers for TF frames
        robot_state_publisher_node,
        joint_state_publisher_node,
        # Motor control nodes for teleoperation
        bringup_node,
        driver_node,
        base_node,
    ])
