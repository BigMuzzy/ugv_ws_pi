#!/usr/bin/env python3
"""
SLAM-Only Launch File

Launches just the slam_toolbox async node for MAPPING mode.
Used by mode_manager_node.py as a subprocess — slam_toolbox does not
support ROS2 lifecycle, so it is managed via process start/stop.

Does NOT include robot_pose_publisher or bringup — those are handled
by mode_lifecycle.launch.py and background.launch.py respectively.
"""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    # SLAM Toolbox node — all params ported from ugv_slam/slam_toolbox.launch.py
    slam_toolbox_node = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        arguments=['--ros-args', '--log-level', 'info'],
        parameters=[
            {
                'use_sim_time': False,
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
            }
        ],
        remappings=[
            ('/scan', '/scan'),
            ('/odom', '/odom_rf2o'),
        ],
    )

    return LaunchDescription([
        slam_toolbox_node,
    ])
