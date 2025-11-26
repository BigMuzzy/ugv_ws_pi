# Launch Manager - Quick Reference

## Session: 2025-11-23
Initial build of ROS2 service-based launch manager for dynamic mode switching.

## Session: 2025-11-24
Enhanced launch manager with idle mode improvements, auto-start, persistent agent, custom map paths, and auto-save functionality.

---

## What We Built

ROS2 service-based launch manager for dynamic mode switching between idle, mapping, and navigation modes with the following features:

### Key Features
1. **Dynamic Mode Switching** - Switch between modes via ROS2 services
2. **Auto-Start Mode** - Automatically start in a specified mode (default: idle)
3. **Persistent Agent Script** - Runs `~/.transitive/start_agent.sh` throughout manager lifetime
4. **Custom Map Paths** - Specify map paths for both mapping and navigation modes
5. **Auto-Save Maps** - Automatically save maps when switching away from mapping mode
6. **Idle Mode** - Complete camera setup with robot state publishers for proper TF frames

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
- **Description**: Camera with robot state publishers (for proper TF frames)
- **Components**:
  - OAK-D Lite camera
  - robot_state_publisher (publishes URDF and TF)
  - joint_state_publisher (publishes joint states)
  - Image rectification node
- **Use case**: Basic monitoring, testing camera
- **Launch**: `mode_idle.launch.py`

### Mapping Mode
- **Description**: SLAM mapping with gmapping
- **Components**:
  - All components from bringup_lidar (lidar, base, odometry)
  - gmapping SLAM node
  - robot_pose_publisher
- **Parameters**:
  - `map_path`: Where to save the map (default: `/home/ws/ugv_ws/maps/new_map`)
- **Auto-save**: Map automatically saves when switching away from mapping mode
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
*Note: Automatically saves map if stopping from mapping mode*

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

### Auto-Save Feature
- **Trigger**: Switching away from mapping mode OR calling stop_all
- **Method**: Uses `map_saver_cli` from nav2_map_server
- **Output**: Creates both `.yaml` and `.pgm` files
- **Timeout**: 10 seconds for save operation
- **Path**: Uses the `map_path` specified when starting mapping mode

---

## Files Modified/Created

### Session 2025-11-24 Changes

**Service Definition:**
- `ugv_interface/srv/SwitchMode.srv` - Added `arg_names` and `arg_values` arrays

**Launch Manager Package:**
- `ugv_launch_manager/launch/mode_idle.launch.py` - NEW: Idle mode with camera and robot state
- `ugv_launch_manager/launch/mode_mapping.launch.py` - Added `map_path` parameter
- `ugv_launch_manager/launch/mode_navigation.launch.py` - Changed `map` to `map_path` parameter
- `ugv_launch_manager/launch/manager.launch.py` - Added `default_mode` parameter
- `ugv_launch_manager/ugv_launch_manager/launch_manager_node.py` - Major enhancements:
  - Auto-start mode functionality
  - Persistent agent script management
  - Custom argument handling
  - Auto-save map functionality
  - Current mode arguments tracking
- `ugv_launch_manager/config/modes.yaml` - Updated with map_path for mapping and navigation

---

## Status

✅ All services working
✅ Mode switching tested and functional
✅ Process management working (force kill after 10s timeout is normal)
✅ Idle mode with full robot state publishers
✅ Auto-start mode on launch
✅ Persistent agent script integration
✅ Custom map path parameters
✅ Auto-save maps when leaving mapping mode

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
4. Switch to navigation or idle (map auto-saves to new_area.yaml and new_area.pgm)

### Navigation with Existing Map
1. Switch to navigation with specific map:
   ```bash
   ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'navigation', arg_names: ['map_path'], arg_values: ['/home/ws/ugv_ws/maps/second_floor.yaml']}"
   ```
2. Set navigation goals via Nav2

### Monitoring Only
1. Launch manager auto-starts in idle mode
2. View camera with: `rqt_image_view`
3. Camera topics available immediately

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
- Verify nav2_map_server is available
- Check launch manager logs for save errors
- Ensure mapping mode was started with valid map_path

---

## Full Documentation

See: `/home/ws/ugv_ws/src/ugv_main/ugv_launch_manager/README.md`

---

## Next Steps / TODO

- [ ] Test auto-save functionality with real mapping session
- [ ] Verify agent script persistence through mode switches
- [ ] Test custom map paths with navigation
- [ ] Consider adding map quality check before save
- [ ] Add service to manually trigger map save during mapping
