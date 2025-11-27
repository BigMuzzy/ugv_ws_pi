"""Launch file for WebRTC-ROS2 bridge."""
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
import os
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    """Generate launch description for WebRTC bridge."""
    # Get package share directory
    pkg_share = get_package_share_directory('webrtc_ros2_bridge')
    config_file = os.path.join(pkg_share, 'config', 'bridge_config.yaml')

    # Declare launch arguments
    host_arg = DeclareLaunchArgument(
        'host',
        default_value='0.0.0.0',
        description='Signaling server host address'
    )

    port_arg = DeclareLaunchArgument(
        'port',
        default_value='8080',
        description='Signaling server port'
    )

    video_device_arg = DeclareLaunchArgument(
        'video_device',
        default_value='/dev/video0',
        description='Camera device path'
    )

    video_width_arg = DeclareLaunchArgument(
        'video_width',
        default_value='640',
        description='Video frame width'
    )

    video_height_arg = DeclareLaunchArgument(
        'video_height',
        default_value='480',
        description='Video frame height'
    )

    video_fps_arg = DeclareLaunchArgument(
        'video_fps',
        default_value='30',
        description='Video frames per second'
    )

    cmd_vel_topic_arg = DeclareLaunchArgument(
        'cmd_vel_topic',
        default_value='/cmd_vel',
        description='Topic for velocity commands'
    )

    max_linear_speed_arg = DeclareLaunchArgument(
        'max_linear_speed',
        default_value='1.0',
        description='Maximum linear velocity (m/s)'
    )

    max_angular_speed_arg = DeclareLaunchArgument(
        'max_angular_speed',
        default_value='2.0',
        description='Maximum angular velocity (rad/s)'
    )

    # Create bridge node
    bridge_node = Node(
        package='webrtc_ros2_bridge',
        executable='bridge_node',
        name='webrtc_bridge',
        parameters=[{
            'server.host': LaunchConfiguration('host'),
            'server.port': LaunchConfiguration('port'),
            'video.device': LaunchConfiguration('video_device'),
            'video.width': LaunchConfiguration('video_width'),
            'video.height': LaunchConfiguration('video_height'),
            'video.fps': LaunchConfiguration('video_fps'),
            'robot.cmd_vel_topic': LaunchConfiguration('cmd_vel_topic'),
            'robot.max_linear_speed': LaunchConfiguration('max_linear_speed'),
            'robot.max_angular_speed': LaunchConfiguration('max_angular_speed'),
            'config_file': config_file,
        }],
        output='screen',
        emulate_tty=True,
    )

    return LaunchDescription([
        host_arg,
        port_arg,
        video_device_arg,
        video_width_arg,
        video_height_arg,
        video_fps_arg,
        cmd_vel_topic_arg,
        max_linear_speed_arg,
        max_angular_speed_arg,
        bridge_node,
    ])
