# Launch Manager - Quick Reference

## Session: 2025-11-23
Initial build of ROS2 service-based launch manager for dynamic mode switching.

## Session: 2025-11-24
Enhanced launch manager with idle mode improvements, auto-start, persistent agent, custom map paths, and auto-save functionality.

## Session: 2025-11-26
Extracted auto-save from mapping mode and created manual save_map service for on-demand map saving.
Added teleoperation support to idle mode for robot control without mapping/navigation overhead.

## Session: 2025-11-29
Enhanced StopAll service with selective process stopping parameters.
Added ability to selectively stop background processes (agent, WebRTC bridge, ngrok) independently from mode processes.

---

## What We Built

ROS2 service-based launch manager for dynamic mode switching between idle, mapping, and navigation modes with the following features:

### Key Features
1. **Dynamic Mode Switching** - Switch between modes via ROS2 services
2. **Auto-Start Mode** - Automatically start in a specified mode (default: idle)
3. **Persistent Agent Script** - Runs `~/.transitive/start_agent.sh` throughout manager lifetime
4. **WebRTC Bridge & ngrok** - Background services for remote video streaming and tunneling
5. **Custom Map Paths** - Specify map paths for both mapping and navigation modes
6. **Manual Map Save** - Save maps on demand during mapping mode via service call
7. **Idle Mode with Teleoperation** - Camera, robot state, and motor control for lightweight operation
8. **Selective Process Stopping** - Stop individual background processes (agent, WebRTC, ngrok) or mode processes independently

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

**Stop everything (mode + all background processes):**
```bash
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll
```
*Note: When no parameters are specified, all processes are stopped for backwards compatibility*

**Stop only the current mode process:**
```bash
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll "{stop_mode: true, stop_agent: false, stop_webrtc: false, stop_ngrok: false}"
```

**Stop only background services (keep mode running):**
```bash
# Stop WebRTC bridge and ngrok only
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll "{stop_mode: false, stop_agent: false, stop_webrtc: true, stop_ngrok: true}"

# Stop only the transitive agent
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll "{stop_mode: false, stop_agent: true, stop_webrtc: false, stop_ngrok: false}"
```

**Stop mode and agent, but keep WebRTC/ngrok running:**
```bash
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll "{stop_mode: true, stop_agent: true, stop_webrtc: false, stop_ngrok: false}"
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

### Background Services
The launch manager starts and manages several background services that run independently of mode processes:

#### Persistent Agent Script
- **Path**: `~/.transitive/start_agent.sh`
- **Lifecycle**: Starts with launch manager, runs continuously until explicitly stopped
- **Behavior**: NOT affected by mode switches (keeps running)
- **Logging**: Check launch manager logs for agent PID and status
- **Stopping**: Use `/ugv/stop_all` with `stop_agent: true`

#### WebRTC Bridge
- **Purpose**: Provides video streaming via WebRTC for remote monitoring
- **Port**: 8080
- **Lifecycle**: Starts with launch manager, runs continuously until explicitly stopped
- **Behavior**: NOT affected by mode switches (keeps running)
- **Logging**: Check launch manager logs for WebRTC bridge PID and status
- **Stopping**: Use `/ugv/stop_all` with `stop_webrtc: true`

#### ngrok Tunnel
- **Purpose**: Provides public URL access to WebRTC bridge
- **Port**: Tunnels port 8080
- **Lifecycle**: Starts with launch manager, runs continuously until explicitly stopped
- **Behavior**: NOT affected by mode switches (keeps running)
- **Logging**: Check launch manager logs for ngrok PID and status
- **Stopping**: Use `/ugv/stop_all` with `stop_ngrok: true`

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

### Session 2025-11-26 Changes

**Service Definition:**
- `ugv_interface/srv/MapSave.srv` - Updated to use `map_path` with success/message response pattern

**Launch Manager Package:**
- `ugv_launch_manager/ugv_launch_manager/launch_manager_node.py` - Changed from auto-save to manual save:
  - Removed auto-save logic from `switch_mode_callback` and `stop_all_callback`
  - Added `/ugv/save_map` service and `save_map_callback` handler
  - Updated `save_map()` method to return success status tuple
  - Service supports both explicit map paths and using current mapping mode's path
- `ugv_launch_manager/launch/mode_idle.launch.py` - Added teleoperation support:
  - Added ugv_bringup node for robot initialization
  - Added ugv_driver node for motor control
  - Added base_node for cmd_vel control
  - Added pub_odom_tf launch argument
  - Idle mode now supports full teleoperation without mapping/navigation overhead

### Session 2025-11-29 Changes

**Service Definition:**
- `ugv_interface/srv/StopAll.srv` - Added selective stopping parameters:
  - `stop_mode`: Stop the current mode process
  - `stop_agent`: Stop the transitive agent
  - `stop_webrtc`: Stop the WebRTC bridge
  - `stop_ngrok`: Stop the ngrok tunnel
  - Backwards compatible: no flags set = stop everything

**Launch Manager Package:**
- `ugv_launch_manager/ugv_launch_manager/launch_manager_node.py` - Enhanced `stop_all_callback`:
  - Selective process stopping based on request flags
  - Backwards compatible default behavior (stop all when no flags set)
  - Detailed logging of which processes are being stopped
  - Error handling for each process stop operation
  - Informative success/error messages in response

---

## Status

✅ All services working
✅ Mode switching tested and functional
✅ Process management working (force kill after 10s timeout is normal)
✅ Idle mode with teleoperation support (camera + motor control)
✅ Auto-start mode on launch
✅ Persistent agent script integration
✅ WebRTC bridge and ngrok background services
✅ Custom map path parameters
✅ Manual map save service (`/ugv/save_map`) implemented
✅ Auto-save removed for better manual control
✅ Selective process stopping (`/ugv/stop_all` with flags)

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

**Background services not stopping:**
- Check if processes are actually running: `ps aux | grep -E "(ngrok|webrtc|start_agent)"`
- Review launch manager logs for error messages
- Use selective stop flags to stop individual services
- If stuck, try stopping all: `ros2 service call /ugv/stop_all ugv_interface/srv/StopAll`

**WebRTC bridge not accessible:**
- Check if bridge is running in launch manager logs
- Verify port 8080 is not blocked: `netstat -tuln | grep 8080`
- Check ngrok status and public URL: `curl http://localhost:4040/api/tunnels`

---

## Full Documentation

See: `/home/ws/ugv_ws/src/ugv_main/ugv_launch_manager/README.md`

---

## Next Steps / TODO

- [x] Add service to manually trigger map save during mapping (✅ 2025-11-26)
- [x] Remove auto-save for better manual control (✅ 2025-11-26)
- [x] Add selective process stopping to stop_all service (✅ 2025-11-29)
- [ ] Test manual save_map service with real mapping session
- [ ] Verify agent script persistence through mode switches
- [ ] Test custom map paths with navigation
- [ ] Test selective stopping of background services
- [ ] Consider adding map quality check before save
- [ ] Add option to save multiple map snapshots during same mapping session
- [ ] Add service to restart individual background services without restarting manager
