#!/usr/bin/env python3
"""
SLAM Toolbox Launch File
Launches SLAM Toolbox for mapping mode
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch.conditions import IfCondition
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Declare launch argument for whether to launch RViz2
    use_rviz_arg = DeclareLaunchArgument(
        'use_rviz', 
        default_value='false',
        description='Whether to launch RViz2'
    )
    
    # Declare launch argument for whether to include bringup_lidar
    include_bringup_arg = DeclareLaunchArgument(
        'include_bringup',
        default_value='true',
        description='Whether to include bringup_lidar (set false if hardware already running)'
    )
    
    # Include launch description for bringup_lidar.launch.py
    bringup_lidar_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('ugv_bringup'), 
                'launch', 
                'bringup_lidar.launch.py'
            )
        ),
        launch_arguments={
            'use_rviz': LaunchConfiguration('use_rviz'),
            'rviz_config': 'slam_2d',
        }.items(),
        condition=IfCondition(LaunchConfiguration('include_bringup'))
    )
    
    # SLAM Toolbox node with online async SLAM mode
    slam_toolbox_node = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        parameters=[
            {
                'use_sim_time': False,
                'odom_frame': 'odom',
                'map_frame': 'map',
                'base_frame': 'base_footprint',
                'scan_topic': '/scan',
                'mode': 'mapping',
                
                # General Parameters
                'map_update_interval': 1.0,
                'resolution': 0.05,
                'max_laser_range': 12.0,
                'minimum_time_interval': 0.5,
                'transform_publish_period': 0.02,
                'tf_buffer_duration': 30.0,
                
                # Solver Parameters
                'solver_plugin': 'solver_plugins::CeresSolver',
                'ceres_linear_solver': 'SPARSE_NORMAL_CHOLESKY',
                'ceres_preconditioner': 'SCHUR_JACOBI',
                'ceres_trust_strategy': 'LEVENBERG_MARQUARDT',
                'ceres_dogleg_type': 'TRADITIONAL_DOGLEG',
                'ceres_loss_function': 'None',
                
                # Correlation Parameters
                'correlation_search_space_dimension': 0.5,
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
                'minimum_travel_distance': 0.2,
                'minimum_travel_heading': 0.2,
                'scan_buffer_size': 10,
                'scan_buffer_maximum_scan_distance': 10.0,
                'link_match_minimum_response_fine': 0.1,
                'link_scan_maximum_distance': 1.5,
                'max_variance': 0.02,
            }
        ],
        remappings=[
            ('/scan', '/scan'),
        ]
    )

    # Include launch description for robot_pose_publisher_launch.py
    robot_pose_publisher_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('robot_pose_publisher'), 
                'launch',
                'robot_pose_publisher_launch.py'
            )
        )
    )
    
    # Return launch description
    return LaunchDescription([
        use_rviz_arg,
        include_bringup_arg,
        bringup_lidar_launch,
        robot_pose_publisher_launch,
        slam_toolbox_node,
    ])