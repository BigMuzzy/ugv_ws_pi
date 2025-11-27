"""Setup file for webrtc_ros2_bridge package."""
from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'webrtc_ros2_bridge'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob(os.path.join('launch', '*launch.py'))),
        (os.path.join('share', package_name, 'config'),
            glob(os.path.join('config', '*.yaml'))),
        (os.path.join('share', package_name, 'static'),
            glob(os.path.join('static', '*'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='dudu',
    maintainer_email='dudu@todo.todo',
    description='WebRTC-ROS2 bridge for robot teleoperation',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'bridge_node = webrtc_ros2_bridge.bridge_node:main',
            'signaling_server = webrtc_ros2_bridge.signaling_server:main',
        ],
    },
)
