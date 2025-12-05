"""Launch file for WebRTC-ROS2 bridge with SFU mode (Cloudflare Calls)."""
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
import os
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    """Generate launch description for WebRTC bridge in SFU mode."""
    # Get package share directory
    pkg_share = get_package_share_directory('webrtc_ros2_bridge')
    config_file = os.path.join(pkg_share, 'config', 'bridge_config.yaml')

    # Declare launch arguments
    robot_id_arg = DeclareLaunchArgument(
        'robot_id',
        default_value='robot_01',
        description='Unique robot identifier'
    )

    workers_endpoint_arg = DeclareLaunchArgument(
        'workers_endpoint',
        default_value='https://fleet-workers.mssemyonov.workers.dev',
        description='Cloudflare Workers endpoint URL'
    )

    fallback_to_p2p_arg = DeclareLaunchArgument(
        'fallback_to_p2p',
        default_value='true',
        description='Fallback to P2P mode if SFU connection fails'
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

    # Create bridge node with SFU mode enabled
    bridge_node = Node(
        package='webrtc_ros2_bridge',
        executable='bridge_node',
        name='webrtc_bridge_sfu',
        parameters=[{
            # SFU mode parameters
            'sfu.enabled': True,
            'sfu.robot_id': LaunchConfiguration('robot_id'),
            'sfu.workers_endpoint': LaunchConfiguration('workers_endpoint'),
            'sfu.fallback_to_p2p': LaunchConfiguration('fallback_to_p2p'),
            # Video parameters
            'video.device': LaunchConfiguration('video_device'),
            'video.width': LaunchConfiguration('video_width'),
            'video.height': LaunchConfiguration('video_height'),
            'video.fps': LaunchConfiguration('video_fps'),
            # Robot parameters
            'robot.cmd_vel_topic': LaunchConfiguration('cmd_vel_topic'),
            'robot.max_linear_speed': LaunchConfiguration('max_linear_speed'),
            'robot.max_angular_speed': LaunchConfiguration('max_angular_speed'),
            # Config file
            'config_file': config_file,
        }],
        output='screen',
        emulate_tty=True,
    )

    return LaunchDescription([
        robot_id_arg,
        workers_endpoint_arg,
        fallback_to_p2p_arg,
        video_device_arg,
        video_width_arg,
        video_height_arg,
        video_fps_arg,
        cmd_vel_topic_arg,
        max_linear_speed_arg,
        max_angular_speed_arg,
        bridge_node,
    ])
