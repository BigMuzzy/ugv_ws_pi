#!/usr/bin/env python3
"""
Lifecycle Mode Launch File

Launches all lifecycle-managed nodes at startup in UNCONFIGURED state.
The mode_manager_node controls activation/deactivation via lifecycle service calls.

Nodes launched:
  - slam_toolbox (LifecycleNode, use_lifecycle_manager=true) — for MAPPING mode
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

    # Default Nav2 param file (amcl + teb)
    default_params_file = os.path.join(ugv_nav_dir, 'param', 'amcl_teb.yaml')

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
    # use_lifecycle_manager=true enables lifecycle support in async_slam_toolbox_node.
    # Without it, the node runs as a standard node without lifecycle services.
    # All params ported from ugv_slam/slam_toolbox.launch.py.
    slam_toolbox_node = LifecycleNode(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        namespace='',
        output='screen',
        arguments=['--ros-args', '--log-level', 'info'],
        parameters=[{
            'use_sim_time': False,
            'use_lifecycle_manager': True,
            'odom_frame': 'odom',
            'map_frame': 'map',
            'base_frame': 'base_footprint',
            'scan_topic': '/scan',
            'mode': 'mapping',

            # General Parameters
            'map_update_interval': 0.5,
            'resolution': 0.05,
            'max_laser_range': 12.0,
            'min_laser_range': 0.1,
            'minimum_time_interval': 0.2,
            'transform_publish_period': 0.02,
            'tf_buffer_duration': 60.0,
            'transform_timeout': 0.5,

            # Message Filter Parameters
            'message_filter_queue_size': 100,
            'throttle_scans': 1,

            # Solver Parameters
            'solver_plugin': 'solver_plugins::CeresSolver',
            'ceres_linear_solver': 'SPARSE_NORMAL_CHOLESKY',
            'ceres_preconditioner': 'SCHUR_JACOBI',
            'ceres_trust_strategy': 'LEVENBERG_MARQUARDT',
            'ceres_dogleg_type': 'TRADITIONAL_DOGLEG',
            'ceres_loss_function': 'None',
            'num_threads': 4,

            # Correlation Parameters
            'correlation_search_space_dimension': 1.0,
            'correlation_search_space_resolution': 0.01,
            'correlation_search_space_smear_deviation': 0.1,

            # Loop Closure Parameters
            'loop_search_maximum_distance': 3.0,
            'do_loop_closing': True,
            'loop_match_minimum_chain_size': 10,
            'loop_match_maximum_variance_coarse': 3.0,
            'loop_match_minimum_response_coarse': 0.35,
            'loop_match_minimum_response_fine': 0.45,

            # Scan Matcher Parameters
            'use_scan_matching': True,
            'use_scan_barycenter': True,
            'minimum_travel_distance': 0.1,
            'minimum_travel_heading': 0.1,
            'scan_buffer_size': 20,
            'scan_buffer_maximum_scan_distance': 15.0,
            'link_match_minimum_response_fine': 0.1,
            'link_scan_maximum_distance': 2.0,
            'max_variance': 0.1,

            # Additional scan matching parameters
            'coarse_search_angle_offset': 0.349,
            'coarse_angle_resolution': 0.0349,
            'minimum_angle_penalty': 0.9,
            'minimum_distance_penalty': 0.5,
            'use_response_expansion': True,

            # Fine search parameters
            'fine_search_angle_offset': 0.00349,
            'distance_variance_penalty': 0.5,
            'angle_variance_penalty': 1.0,
        }],
        remappings=[
            ('/scan', '/scan'),
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
