# Launch Manager - Quick Reference

## Overview

ROS2 service-based launch manager for dynamic mode switching between idle, mapping, and navigation modes with the following features:

### Key Features
1. **Dynamic Mode Switching** - Switch between modes via ROS2 services
2. **Auto-Start Mode** - Automatically start in a specified mode (default: idle)
3. **Persistent Agent Script** - Runs `~/.transitive/start_agent.sh` throughout manager lifetime
4. **Custom Map Paths** - Specify map paths for both mapping and navigation modes
5. **Manual Map Save** - Save maps on demand during mapping mode via service call
6. **Idle Mode with Teleoperation** - Camera, robot state, and motor control for lightweight operation

---

## Quick Start

### Start Launch Manager
```bash
# Start with default mode (idle)
ros2 launch ugv_launch_manager manager.launch.py

# Start with no mode
ros2 launch ugv_launch_manager manager.launch.py default_mode:=none

# Start directly in mapping
ros2 launch ugv_launch_manager manager.launch.py default_mode:=mapping
```

---

## Available Modes

### Idle Mode
- **Description**: Camera with robot state publishers and teleoperation support
- **Components**:
  - OAK-D Lite camera
  - robot_state_publisher (publishes URDF and TF)
  - joint_state_publisher (publishes joint states)
  - Image rectification node
  - ugv_bringup node (robot initialization)
  - ugv_driver node (motor driver)
  - base_node (cmd_vel control for teleoperation)
- **Use case**: Basic monitoring, testing camera, teleoperation without mapping/navigation
- **Launch**: `mode_idle.launch.py`

### Mapping Mode
- **Description**: SLAM mapping with gmapping
- **Components**:
  - All components from bringup_lidar (lidar, base, odometry)
  - gmapping SLAM node
  - robot_pose_publisher
- **Parameters**:
  - `map_path`: Where to save the map (default: `/home/ws/ugv_ws/maps/new_map`)
- **Manual save**: Use `/ugv/save_map` service to save map on demand
- **Launch**: `mode_mapping.launch.py`

### Navigation Mode
- **Description**: Nav2 with AMCL localization
- **Components**:
  - All components from bringup_lidar
  - Nav2 navigation stack
  - AMCL localization
  - robot_pose_publisher
- **Parameters**:
  - `map_path`: Map file to use (default: `/home/ws/ugv_ws/maps/second_floor.yaml`)
  - `use_localization`: amcl, emcl, cartographer (default: amcl)
  - `use_localplan`: teb, dwa (default: teb)
- **Launch**: `mode_navigation.launch.py`

---

## Service Commands

### Check Current Mode
```bash
ros2 service call /ugv/get_mode ugv_interface/srv/GetMode
```

### Switch Modes

**Idle mode (default):**
```bash
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'idle'}"
```

**Mapping with default map path:**
```bash
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'mapping'}"
```

**Mapping with custom map path:**
```bash
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'mapping', arg_names: ['map_path'], arg_values: ['/home/ws/ugv_ws/maps/floor1']}"
```

**Navigation with default map:**
```bash
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'navigation'}"
```

**Navigation with custom map:**
```bash
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'navigation', arg_names: ['map_path'], arg_values: ['/home/ws/ugv_ws/maps/floor1.yaml']}"
```

### Stop All Systems
```bash
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll
```

### Save Map During Mapping

**Save with current map_path (from mapping mode):**
```bash
ros2 service call /ugv/save_map ugv_interface/srv/MapSave "{map_path: ''}"
```

**Save to custom path:**
```bash
ros2 service call /ugv/save_map ugv_interface/srv/MapSave "{map_path: '/home/ws/ugv_ws/maps/my_custom_map'}"
```
*Note: Must be in mapping mode to use empty map_path*

---

## Architecture

### Persistent Agent Script
- **Path**: `~/.transitive/start_agent.sh`
- **Lifecycle**: Starts with launch manager, runs continuously, stops with manager
- **Behavior**: NOT affected by mode switches (keeps running)
- **Logging**: Check launch manager logs for agent PID and status

### Mode Configuration
- **Config file**: `ugv_launch_manager/config/modes.yaml`
- **Default arguments**: Set in YAML, can be overridden via service call
- **Argument merging**: Service arguments override YAML defaults

### Manual Map Save Feature
- **Trigger**: Manual service call to `/ugv/save_map`
- **Method**: Uses `map_saver_cli` from nav2_map_server
- **Output**: Creates both `.yaml` and `.pgm` files
- **Timeout**: 10 seconds for save operation
- **Path**: Can specify custom path or use current mapping mode's `map_path`

---

## Rebuild Instructions

After modifying service definitions or launch files:

```bash
# Clean build for interface changes
rm -rf build/ugv_interface install/ugv_interface
colcon build --packages-select ugv_interface

# Build launch manager
colcon build --packages-select ugv_launch_manager --symlink-install

# Source workspace
source /home/ws/ugv_ws/install/setup.bash

# Restart launch manager
ros2 launch ugv_launch_manager manager.launch.py
```

---

## Typical Workflow

### Mapping a New Area
1. Start launch manager (auto-starts in idle mode)
2. Switch to mapping mode with custom map path:
   ```bash
   ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'mapping', arg_names: ['map_path'], arg_values: ['/home/ws/ugv_ws/maps/new_area']}"
   ```
3. Drive robot around to create map
4. Save map when satisfied with coverage:
   ```bash
   ros2 service call /ugv/save_map ugv_interface/srv/MapSave "{map_path: ''}"
   ```
   (Empty map_path uses the current mapping mode's path: `/home/ws/ugv_ws/maps/new_area`)
5. Continue mapping or switch to another mode

### Navigation with Existing Map
1. Switch to navigation with specific map:
   ```bash
   ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'navigation', arg_names: ['map_path'], arg_values: ['/home/ws/ugv_ws/maps/second_floor.yaml']}"
   ```
2. Set navigation goals via Nav2

### Monitoring and Teleoperation
1. Launch manager auto-starts in idle mode
2. View camera with: `rqt_image_view`
3. Camera topics available immediately
4. Teleoperate robot with keyboard or joystick (publishes to `/cmd_vel`)
   - Example: `ros2 run teleop_twist_keyboard teleop_twist_keyboard`

---

## Troubleshooting

**Service field errors:**
- Ensure ugv_interface is rebuilt and workspace is sourced
- Restart launch manager after rebuilding interface

**Camera not visible:**
- Check robot state publishers are running: `ros2 node list`
- Verify TF frames: `ros2 run tf2_tools view_frames`

**Agent script not starting:**
- Check script exists: `ls -la ~/.transitive/start_agent.sh`
- Verify executable: `chmod +x ~/.transitive/start_agent.sh`
- Check launch manager logs for agent PID

**Map not saving:**
- Verify nav2_map_server is available: `ros2 pkg list | grep nav2_map_server`
- Check launch manager logs for save errors
- Ensure you're in mapping mode or provide explicit map_path
- Verify map topic is being published: `ros2 topic echo /map --once`

---

## Full Documentation

See: `/home/ws/ugv_ws/src/ugv_main/ugv_launch_manager/README.md`

---

## Future Improvements

- [ ] Test manual save_map service with real mapping session
- [ ] Verify agent script persistence through mode switches
- [ ] Test custom map paths with navigation
- [ ] Consider adding map quality check before save
- [ ] Add option to save multiple map snapshots during same mapping session
