#!/usr/bin/env python3
"""
Lifecycle Mode Launch File

Launches all lifecycle-managed nodes at startup in UNCONFIGURED state.
The mode_manager_node controls activation/deactivation via lifecycle service calls.

slam_toolbox is launched as a LifecycleNode with use_lifecycle_manager: true
(set in config/slam_toolbox.yaml). This tells the node to stay unconfigured
and wait for external lifecycle transitions from mode_manager.

Nodes launched:
  - slam_toolbox (LifecycleNode) — for MAPPING mode
  - map_server (LifecycleNode) — for NAVIGATION mode
  - amcl (LifecycleNode) — for NAVIGATION mode
  - Nav2 navigation stack (via navigation_launch.py, autostart=false)
  - robot_pose_publisher (regular Node, always running)
  - map_republisher (regular Node, always running, no-ops without map)
"""

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LifecycleNode, Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Package directories
    nav2_bringup_dir = get_package_share_directory('nav2_bringup')
    ugv_nav_dir = get_package_share_directory('ugv_nav')
    ugv_launch_dir = get_package_share_directory('ugv_launch_manager')

    # Config files
    default_params_file = os.path.join(ugv_nav_dir, 'param', 'amcl_teb.yaml')
    slam_params_file = os.path.join(ugv_launch_dir, 'config', 'slam_toolbox.yaml')

    # Declare arguments
    params_file_arg = DeclareLaunchArgument(
        'params_file',
        default_value=default_params_file,
        description='Nav2 parameters file'
    )

    map_republish_rate_arg = DeclareLaunchArgument(
        'map_republish_rate',
        default_value='1.0',
        description='Rate (Hz) at which to republish /map for web clients'
    )

    # ─── SLAM Toolbox as LifecycleNode (starts UNCONFIGURED) ───
    # use_lifecycle_manager: true in slam_toolbox.yaml tells the node to
    # stay unconfigured and wait for external lifecycle transitions.
    # No EmitEvent/ChangeState actions — mode_manager handles transitions.
    slam_toolbox_node = LifecycleNode(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        namespace='',
        output='screen',
        parameters=[slam_params_file],
        remappings=[
            ('/odom', '/odom_rf2o'),
        ],
    )

    # ─── Map Server as LifecycleNode (starts UNCONFIGURED) ───
    # yaml_filename is empty; mode_manager sets it via set_parameters before configure
    map_server_node = LifecycleNode(
        package='nav2_map_server',
        executable='map_server',
        name='map_server',
        namespace='',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'yaml_filename': '',
        }],
    )

    # ─── AMCL as LifecycleNode (starts UNCONFIGURED) ───
    # Uses the full Nav2 param file for AMCL configuration
    amcl_node = LifecycleNode(
        package='nav2_amcl',
        executable='amcl',
        name='amcl',
        namespace='',
        output='screen',
        parameters=[LaunchConfiguration('params_file')],
    )

    # ─── Nav2 Navigation Stack (autostart=false) ───
    # Includes ONLY navigation_launch.py (NOT bringup_launch.py or localization_launch.py)
    # This gives us lifecycle_manager_navigation + 9 nav2 nodes, all unconfigured.
    # mode_manager manages startup/shutdown via the lifecycle_manager service.
    nav2_navigation_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(nav2_bringup_dir, 'launch', 'navigation_launch.py')
        ),
        launch_arguments={
            'use_sim_time': 'false',
            'autostart': 'false',
            'params_file': default_params_file,
            'use_composition': 'False',
        }.items()
    )

    # ─── Robot Pose Publisher (regular Node, always running) ───
    # Tolerates missing map frame — simply fails TF lookups silently until
    # SLAM or AMCL provides the map→odom transform.
    robot_pose_publisher_node = Node(
        package='robot_pose_publisher',
        executable='robot_pose_publisher',
        name='robot_pose_publisher',
        output='screen',
        emulate_tty=True,
        parameters=[{
            'use_sim_time': False,
            'is_stamped': True,
            'map_frame': 'map',
            'base_frame': 'base_link',
        }],
    )

    # ─── Map Republisher (regular Node, always running) ───
    # No-ops when no map is published (checks self._last_map is None).
    # Ensures web clients receive the static map reliably via rosbridge.
    map_republisher_node = Node(
        package='ugv_launch_manager',
        executable='map_republisher',
        name='map_republisher',
        output='screen',
        parameters=[{
            'publish_rate': LaunchConfiguration('map_republish_rate'),
            'input_map_topic': '/map',
            'input_metadata_topic': '/map_metadata',
        }],
    )

    return LaunchDescription([
        # Arguments
        params_file_arg,
        map_republish_rate_arg,

        # Lifecycle nodes (start unconfigured, mode_manager controls them)
        slam_toolbox_node,
        map_server_node,
        amcl_node,

        # Nav2 stack (autostart=false, mode_manager calls lifecycle_manager)
        nav2_navigation_launch,

        # Helper nodes (always running)
        robot_pose_publisher_node,
        map_republisher_node,
    ])
