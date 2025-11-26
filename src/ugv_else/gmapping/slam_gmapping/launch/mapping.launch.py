from launch import LaunchDescription
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_sim_time = LaunchConfiguration('use_sim_time', default='false')
    return LaunchDescription([
        Node(
            package='slam_gmapping',
            executable='slam_gmapping',
            output='screen',
            parameters=[{
                'use_sim_time': use_sim_time,
                'linearUpdate': 0.1,      # Process scan after robot moves 10cm (was 1.0m)
                'angularUpdate': 0.1,     # Process scan after robot rotates ~5.7 degrees (was ~28.6 degrees)
                'temporalUpdate': 0.5,    # Process scan after 0.5 seconds even without movement
            }]
        ),
    ])
