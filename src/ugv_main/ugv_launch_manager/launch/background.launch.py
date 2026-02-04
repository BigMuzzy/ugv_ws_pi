#!/usr/bin/env python3
"""
Background Launch File
Launches all common nodes that run continuously regardless of mode.
These processes are started once at launch manager startup and persist
through mode switches (mapping <-> navigation).

Includes:
- Robot state and joint publishers (TF)
- Motor control (bringup, driver, base_node)
- LIDAR driver
- Laser odometry

Note: robot_pose_publisher is NOT included here because it requires
a map frame which only exists during mapping or navigation modes.
It's started by mode_mapping.launch.py and mode_navigation.launch.py.
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    # Declare launch arguments
    pub_odom_tf_arg = DeclareLaunchArgument(
        'pub_odom_tf', default_value='true',
        description='Whether to publish the tf from odom to base_footprint'
    )

    use_rviz_arg = DeclareLaunchArgument(
        'use_rviz', default_value='false',
        description='Whether to launch RViz2'
    )

    rviz_config_arg = DeclareLaunchArgument(
        'rviz_config', default_value='bringup',
        description='Choose which rviz configuration to use'
    )

    # Include the robot state launch from the ugv_description package
    # This includes robot_state_publisher and joint_state_publisher
    robot_state_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('ugv_description'), 'launch', 'display.launch.py')
        ),
        launch_arguments={
            'use_rviz': LaunchConfiguration('use_rviz'),
            'rviz_config': LaunchConfiguration('rviz_config'),
        }.items()
    )

    # Robot initialization node
    bringup_node = Node(
        package='ugv_bringup',
        executable='ugv_bringup',
    )

    # Motor driver node
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

    # LIDAR driver
    laser_bringup_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('ldlidar'), 'launch', 'ldlidar.launch.py')
        )
    )

    # Laser odometry (rf2o)
    rf2o_laser_odometry_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('rf2o_laser_odometry'), 'launch', 'rf2o_laser_odometry.launch.py')
        )
    )

    return LaunchDescription([
        # Launch arguments
        pub_odom_tf_arg,
        use_rviz_arg,
        rviz_config_arg,
        # Robot state (TF)
        robot_state_launch,
        # Motor control
        bringup_node,
        driver_node,
        base_node,
        # LIDAR and odometry
        laser_bringup_launch,
        rf2o_laser_odometry_launch,
    ])
