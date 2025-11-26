import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Declare launch arguments
    declared_arguments = [
        DeclareLaunchArgument(
            'use_localization',
            default_value='amcl',
            description='Localization method to use (amcl, emcl, cartographer)'
        ),
        DeclareLaunchArgument(
            'use_rviz',
            default_value='false',
            description='Whether to launch RViz'
        ),
        DeclareLaunchArgument(
            'map',
            default_value='/home/ws/ugv_ws/maps/second_floor.yaml',
            description='Full path to map yaml file'
        ),
    ]

    # Get package share directories
    ugv_vision_dir = get_package_share_directory('ugv_vision')
    ugv_nav_dir = get_package_share_directory('ugv_nav')

    # Include OAK-D Lite camera launch file
    oak_d_lite_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(ugv_vision_dir, 'launch', 'oak_d_lite.launch.py')
        )
    )

    # Include navigation launch file with 10-second delay
    nav_launch = TimerAction(
        period=10.0,
        actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(ugv_nav_dir, 'launch', 'nav.launch.py')
                ),
                launch_arguments={
                    'use_localization': LaunchConfiguration('use_localization'),
                    'use_rviz': LaunchConfiguration('use_rviz'),
                    'map': LaunchConfiguration('map'),
                }.items()
            )
        ]
    )

    return LaunchDescription(
        declared_arguments + [
            oak_d_lite_launch,
            nav_launch,
        ]
    )
