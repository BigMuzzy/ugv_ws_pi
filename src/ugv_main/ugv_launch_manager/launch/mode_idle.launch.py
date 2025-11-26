import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import LoadComposableNodes, Node
from launch_ros.descriptions import ComposableNode


def launch_setup(context, *args, **kwargs):
    """Set up the idle mode launch - camera with robot state and teleoperation"""
    # Get the name of the camera
    name = LaunchConfiguration("name").perform(context)
    # Get the depthai_ros_driver package directory
    depthai_prefix = get_package_share_directory("depthai_ros_driver")
    # Get the params_file
    params_file = LaunchConfiguration("params_file")

    # Get the URDF model path
    UGV_MODEL = os.environ['UGV_MODEL']
    urdf_file_name = UGV_MODEL + '.urdf'
    urdf_model_path = os.path.join(
        get_package_share_directory('ugv_description'),
        'urdf',
        urdf_file_name
    )

    # Robot state publisher node
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        namespace='ugv',
        arguments=[urdf_model_path]
    )

    # Joint state publisher node
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

    # Base node for cmd_vel control
    base_node = Node(
        package='ugv_base_node',
        executable='base_node',
        parameters=[{'pub_odom_tf': LaunchConfiguration('pub_odom_tf')}]
    )

    return [
        # Robot state and joint state publishers for TF frames
        robot_state_publisher_node,
        joint_state_publisher_node,
        # Motor control nodes for teleoperation
        bringup_node,
        driver_node,
        base_node,
        # Include the camera.launch.py from depthai_ros_driver
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(depthai_prefix, "launch", "camera.launch.py")
            ),
            launch_arguments={
                "name": name,
                "parent_frame": '3d_camera_link',
                "params_file": params_file,
                'use_rviz': 'False',
            }.items(),
        ),
        # Load the rectify_color_node composable node if rectify_rgb is True
        LoadComposableNodes(
            condition=IfCondition(LaunchConfiguration("rectify_rgb")),
            target_container=name + "_container",
            composable_node_descriptions=[
                ComposableNode(
                    package="image_proc",
                    plugin="image_proc::RectifyNode",
                    name="rectify_color_node",
                    remappings=[
                        ("image", name + "/rgb/image_raw"),
                        ("camera_info", name + "/rgb/camera_info"),
                        ("image_rect", name + "/rgb/image_rect"),
                        ("image_rect/compressed", name + "/rgb/image_rect/compressed"),
                        (
                            "image_rect/compressedDepth",
                            name + "/rgb/image_rect/compressedDepth",
                        ),
                        ("image_rect/theora", name + "/rgb/image_rect/theora"),
                    ],
                )
            ],
        )
    ]


def generate_launch_description():
    """Generate launch description for idle mode"""
    # Declare the launch arguments
    declared_arguments = [
        DeclareLaunchArgument("name", default_value="oak"),
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(
                get_package_share_directory("ugv_vision"),
                "config",
                "oak_d_lite.yaml"
            ),
        ),
        DeclareLaunchArgument("rectify_rgb", default_value="True"),
        DeclareLaunchArgument(
            "pub_odom_tf",
            default_value="true",
            description="Whether to publish the tf from odom to base_footprint"
        ),
    ]

    return LaunchDescription(
        declared_arguments + [OpaqueFunction(function=launch_setup)]
    )
