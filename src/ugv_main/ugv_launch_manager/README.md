# UGV Launch Manager

## Overview
Dynamic launch management system that enables remote switching between operational modes via ROS2 services. Manages UGV operational modes (idle, mapping, navigation) along with persistent background services (WebRTC bridge, ROSBridge server).

## Implementation Summary

### Current Implementation (Updated 2025-12-11)

Complete ROS2 service-based launch management system with mode switching, background service management, and map operations.

**Packages Modified:**
- `ugv_interface` - Added service definitions (SwitchMode, GetMode, StopAll, MapSave, ListMaps)
- `ugv_launch_manager` - New package for launch management

**Key Components:**
1. **Launch Manager Node** ([launch_manager_node.py](ugv_launch_manager/launch_manager_node.py))
   - ROS2 node providing services for mode control
   - Manages subprocess lifecycle for operational modes
   - Manages persistent background services (WebRTC, ROSBridge)
   - Handles map saving and listing operations
   - Supports auto-start of default mode via parameter

2. **Launch Process Manager** ([launch_process_manager.py](ugv_launch_manager/launch_process_manager.py))
   - Handles subprocess creation and termination for mode processes
   - Graceful shutdown with SIGINT, force kill with SIGKILL after timeout
   - Process health monitoring and uptime tracking

3. **Service Definitions** (in `ugv_interface/srv/`)
   - `SwitchMode.srv` - Switch between modes with optional runtime arguments
   - `GetMode.srv` - Query current mode status
   - `StopAll.srv` - Selectively stop mode/WebRTC/ROSBridge processes
   - `MapSave.srv` - Save current map during mapping mode
   - `ListMaps.srv` - List available maps in directory

4. **Mode Configuration** ([modes.yaml](config/modes.yaml))
   - YAML-based mode definitions with launch arguments
   - Configurable default arguments per mode

5. **Mode Launch Files:**
   - [mode_idle.launch.py](launch/mode_idle.launch.py) - Camera, robot state, teleoperation
   - [mode_mapping.launch.py](launch/mode_mapping.launch.py) - SLAM mapping with gmapping
   - [mode_navigation.launch.py](launch/mode_navigation.launch.py) - Nav2 navigation with AMCL
   - [manager.launch.py](launch/manager.launch.py) - Starts the launch manager node

## Available Modes

### 1. idle
- **Description**: Camera, robot state, and teleoperation
- **Components**:
  - OAK-D Lite camera with RGB and depth streams
  - Robot state publisher (TF frames)
  - Joint state publisher
  - Motor control nodes (bringup, driver, base_node)
  - Teleoperation support via `/cmd_vel`
- **Use Case**: Basic operation with camera feed and manual control

### 2. mapping
- **Description**: SLAM mapping with gmapping
- **Reproduces**: `ros2 launch ugv_slam gmapping.launch.py use_rviz:=false`
- **Components**: Lidar bringup, gmapping SLAM, robot_pose_publisher
- **Default Arguments**:
  - `map_path`: `/home/ws/ugv_ws/maps/new_map`
  - `use_rviz`: `false`
- **Use Case**: Create new maps of the environment

### 3. navigation
- **Description**: Navigation with AMCL localization
- **Reproduces**: `ros2 launch ugv_nav nav.launch.py use_localization:=amcl use_rviz:=false map:=/home/ws/ugv_ws/maps/second_floor.yaml`
- **Components**: Lidar bringup, Nav2, AMCL localization, robot_pose_publisher
- **Default Arguments**:
  - `map_path`: `/home/ws/ugv_ws/maps/second_floor.yaml`
  - `use_localization`: `amcl`
  - `use_localplan`: `teb`
  - `use_rviz`: `false`
- **Use Case**: Autonomous navigation on existing maps

## Usage

### Start Launch Manager
```bash
# Start with default mode (idle)
ros2 launch ugv_launch_manager manager.launch.py

# Auto-start in a specific mode
ros2 launch ugv_launch_manager manager.launch.py default_mode:=mapping
```

**Auto-start behavior:**
- The `default_mode` parameter automatically starts the specified mode on launch
- Set to `none` to start without any mode active
- Default is `idle`

### Check Current Mode
```bash
ros2 service call /ugv/get_mode ugv_interface/srv/GetMode
```

**Response:**
```yaml
current_mode: 'idle'
is_active: true
available_modes: ['idle', 'mapping', 'navigation']
```

### Switch to Mapping Mode
```bash
# Basic mode switch
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'mapping'}"

# With custom map path
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'mapping', arg_names: ['map_path'], arg_values: ['/home/ws/ugv_ws/maps/my_map']}"
```

**Response:**
```yaml
success: true
message: 'Successfully switched to mapping mode'
previous_mode: 'idle'
current_mode: 'mapping'
```

### Switch to Navigation Mode
```bash
# Basic mode switch (uses default map)
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'navigation'}"

# With custom map path
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'navigation', arg_names: ['map_path'], arg_values: ['/home/ws/ugv_ws/maps/custom_map.yaml']}"
```

### Save Current Map
```bash
# Save to specific path
ros2 service call /ugv/save_map ugv_interface/srv/MapSave "{map_path: '/home/ws/ugv_ws/maps/my_new_map'}"

# Save to current mapping mode's map_path (if in mapping mode)
ros2 service call /ugv/save_map ugv_interface/srv/MapSave "{map_path: ''}"
```

### List Available Maps
```bash
# List maps in default directory
ros2 service call /ugv/list_maps ugv_interface/srv/ListMaps "{maps_directory: ''}"

# List maps in specific directory
ros2 service call /ugv/list_maps ugv_interface/srv/ListMaps "{maps_directory: '/home/ws/ugv_ws/maps'}"
```

**Response:**
```yaml
success: true
message: "Found 3 map(s) in /home/ws/ugv_ws/maps"
map_names: ['map1', 'map2', 'second_floor']
map_paths: ['/home/ws/ugv_ws/maps/map1.yaml', '/home/ws/ugv_ws/maps/map2.yaml', '/home/ws/ugv_ws/maps/second_floor.yaml']
```

### Stop Systems
```bash
# Stop all systems (mode, WebRTC, ROSBridge)
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll "{stop_mode: true, stop_webrtc: true, stop_rosbridge: true}"

# Stop only current mode
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll "{stop_mode: true, stop_webrtc: false, stop_rosbridge: false}"

# Backwards compatible (stops everything if no flags set)
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll "{}"
```

## Service Definitions

### /ugv/switch_mode
Switch between operational modes with optional runtime arguments.

**Request:**
```yaml
string mode           # 'idle', 'mapping', or 'navigation'
string[] arg_names    # Optional: argument names to override (e.g., ['map_path'])
string[] arg_values   # Optional: argument values (e.g., ['/path/to/map'])
```

**Response:**
```yaml
bool success
string message
string previous_mode
string current_mode
```

### /ugv/get_mode
Query current mode status.

**Request:** _(empty)_

**Response:**
```yaml
string current_mode
bool is_active
string[] available_modes
```

### /ugv/stop_all
Selectively stop mode processes and/or background services.

**Request:**
```yaml
bool stop_mode        # Stop the current mode process
bool stop_webrtc      # Stop the WebRTC bridge
bool stop_rosbridge   # Stop the ROSBridge server
```

**Response:**
```yaml
bool success
string message
```

### /ugv/save_map
Save the current map during mapping mode.

**Request:**
```yaml
string map_path  # Path to save map (without extension). Empty = use current mapping mode map_path
```

**Response:**
```yaml
bool success
string message
```

### /ugv/list_maps
List available maps in a directory.

**Request:**
```yaml
string maps_directory  # Directory to search. Empty = use default /home/ws/ugv_ws/maps
```

**Response:**
```yaml
bool success
string message
string[] map_names   # Map names (without extensions)
string[] map_paths   # Full paths to .yaml files
```

## Architecture

### Background Services
The launch manager automatically starts and manages persistent background services:

1. **WebRTC Bridge** (`webrtc_ros2_bridge`)
   - Started on manager initialization
   - Provides WebRTC video streaming
   - Can be stopped/restarted via `/ugv/stop_all` service

2. **ROSBridge Server** (custom configuration with action goal cancelation)
   - Started on manager initialization
   - WebSocket server for web frontend communication
   - Custom launch file: `rosbridge_websocket_custom.xml`
   - Can be stopped/restarted via `/ugv/stop_all` service

### Process Management
- **Mode Processes**: Uses Python `subprocess.Popen` with process groups
  - Graceful shutdown: Sends SIGINT, waits 10 seconds
  - Force cleanup: Sends SIGKILL if graceful shutdown fails
  - Process health monitoring and uptime tracking

- **Background Services**: Managed separately from mode processes
  - Started once on manager initialization
  - Can be selectively stopped via service flags
  - Independent of mode switching

### Mode Launch Files
Each mode launch file is tailored for its specific operational requirements:

- **[mode_idle.launch.py](launch/mode_idle.launch.py)**:
  - Complete idle mode setup with camera, robot state, and motor control
  - Enables manual teleoperation

- **[mode_mapping.launch.py](launch/mode_mapping.launch.py)**:
  - Wrapper for `gmapping.launch.py`
  - Supports configurable map save path

- **[mode_navigation.launch.py](launch/mode_navigation.launch.py)**:
  - Wrapper for `nav.launch.py`
  - Supports configurable map path and planner selection

Sensor bringup (lidar, etc.) is handled by the wrapped launch files where needed.

## File Locations

### Package Structure
```
ugv_launch_manager/
├── config/
│   └── modes.yaml                      # Mode configuration
├── launch/
│   ├── manager.launch.py               # Launch manager starter
│   ├── mode_mapping.launch.py          # Mapping mode wrapper
│   └── mode_navigation.launch.py       # Navigation mode wrapper
├── ugv_launch_manager/
│   ├── __init__.py
│   ├── launch_manager_node.py          # Main service node
│   └── launch_process_manager.py       # Process management
├── package.xml
├── setup.py
└── README.md                            # This file

ugv_interface/
└── srv/
    ├── SwitchMode.srv
    ├── GetMode.srv
    └── StopAll.srv
```

## Configuration

### Mode Configuration
Edit [config/modes.yaml](config/modes.yaml) to add or modify modes:

```yaml
modes:
  mode_name:
    launch_package: 'package_name'
    launch_file: 'launch_file.launch.py'
    arguments:                          # Optional
      arg_name: 'value'
    description: 'Mode description'
```

**Example** (current configuration):
```yaml
modes:
  idle:
    launch_package: 'ugv_launch_manager'
    launch_file: 'mode_idle.launch.py'
    description: 'Camera only mode'

  mapping:
    launch_package: 'ugv_launch_manager'
    launch_file: 'mode_mapping.launch.py'
    arguments:
      map_path: '/home/ws/ugv_ws/maps/new_map'
    description: 'SLAM mapping mode with all sensors'

  navigation:
    launch_package: 'ugv_launch_manager'
    launch_file: 'mode_navigation.launch.py'
    arguments:
      map_path: '/home/ws/ugv_ws/maps/second_floor.yaml'
    description: 'Navigation with AMCL localization'
```

### Launch Manager Parameters
Configure the launch manager via [launch/manager.launch.py](launch/manager.launch.py):

- **`default_mode`**: Mode to auto-start on initialization
  - Default: `'idle'`
  - Set to `'none'` to start without any mode
  - Options: `'idle'`, `'mapping'`, `'navigation'`, `'none'`

## Known Behavior

### Force Kill Warning
When switching modes, you may see:
```
[WARN] Force killing process (PID: XXXXX)...
```

This is **expected behavior** when complex launch files with multiple nodes don't shut down gracefully within the 10-second timeout. The system ensures cleanup by sending SIGKILL.

### Background Service Management
- WebRTC and ROSBridge services persist across mode switches
- They are only stopped when explicitly requested via `/ugv/stop_all` service
- This ensures continuous connectivity to the web frontend during mode transitions

## Build Instructions

```bash
# Build both packages
colcon build --packages-select ugv_interface ugv_launch_manager --symlink-install

# Or build just launch manager (if service definitions haven't changed)
colcon build --packages-select ugv_launch_manager --symlink-install

# Source workspace
source install/setup.bash
```

## Features

### Implemented ✅
- [x] Dynamic mode switching via ROS2 services
- [x] Process lifecycle management with graceful/force shutdown
- [x] Background service management (WebRTC, ROSBridge)
- [x] Selective service stopping via flags
- [x] Runtime argument overrides for mode parameters
- [x] Map saving functionality during mapping mode
- [x] Map listing from directory
- [x] Auto-start default mode on initialization
- [x] Process health monitoring and uptime tracking
- [x] YAML-based mode configuration

### Potential Improvements
1. **Configurable Timeout** - Make shutdown timeout configurable via parameter
2. **Process Health Checks** - Automatic restart of crashed processes
3. **Enhanced Status Monitoring** - Real-time process health metrics
4. **Logging Levels** - Configurable logging verbosity
5. **Mode Validation** - Pre-flight checks before mode switches
6. **Service Lifecycle Events** - Publish events on mode changes for frontend updates

## Troubleshooting

### Services Not Available
```bash
# Check if launch manager is running
ros2 node list | grep launch_manager

# Restart launch manager
ros2 launch ugv_launch_manager manager.launch.py
```

### Mode Switch Fails
```bash
# Check current mode status
ros2 service call /ugv/get_mode ugv_interface/srv/GetMode

# Stop all systems first
ros2 service call /ugv/stop_all ugv_interface/srv/StopAll

# Try switch again
ros2 service call /ugv/switch_mode ugv_interface/srv/SwitchMode "{mode: 'mapping'}"
```

### Check Launch Manager Logs
The launch manager logs show:
- Mode switch requests
- Process start/stop events
- PID information
- Error messages

## Frontend Integration (ROSBridge)

The launch manager is designed to work with web frontends via ROSBridge. Below are example service call payloads:

### Service Call Examples

<details>
<summary>Get Current Mode Status</summary>

```json
{
  "service": "/ugv/get_mode",
  "type": "ugv_interface/srv/GetMode",
  "request": {}
}
```

**Response:**
```json
{
  "current_mode": "mapping",
  "is_active": true,
  "available_modes": ["idle", "mapping", "navigation"]
}
```
</details>

<details>
<summary>Switch to Idle Mode</summary>

```json
{
  "service": "/ugv/switch_mode",
  "type": "ugv_interface/srv/SwitchMode",
  "request": {
    "mode": "idle",
    "arg_names": [],
    "arg_values": []
  }
}
```
</details>

<details>
<summary>Switch to Mapping Mode (with custom map path)</summary>

```json
{
  "service": "/ugv/switch_mode",
  "type": "ugv_interface/srv/SwitchMode",
  "request": {
    "mode": "mapping",
    "arg_names": ["map_path"],
    "arg_values": ["/home/ws/ugv_ws/maps/new_map"]
  }
}
```
</details>

<details>
<summary>Switch to Navigation Mode (with custom map)</summary>

```json
{
  "service": "/ugv/switch_mode",
  "type": "ugv_interface/srv/SwitchMode",
  "request": {
    "mode": "navigation",
    "arg_names": ["map_path"],
    "arg_values": ["/home/ws/ugv_ws/maps/my_floor.yaml"]
  }
}
```
</details>

<details>
<summary>Save Current Map</summary>

```json
{
  "service": "/ugv/save_map",
  "type": "ugv_interface/srv/MapSave",
  "request": {
    "map_path": "/home/ws/ugv_ws/maps/my_map"
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Map saved successfully to /home/ws/ugv_ws/maps/my_map.yaml and /home/ws/ugv_ws/maps/my_map.pgm"
}
```
</details>

<details>
<summary>List Available Maps</summary>

```json
{
  "service": "/ugv/list_maps",
  "type": "ugv_interface/srv/ListMaps",
  "request": {
    "maps_directory": ""
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Found 3 map(s) in /home/ws/ugv_ws/maps",
  "map_names": ["floor1", "floor2", "second_floor"],
  "map_paths": [
    "/home/ws/ugv_ws/maps/floor1.yaml",
    "/home/ws/ugv_ws/maps/floor2.yaml",
    "/home/ws/ugv_ws/maps/second_floor.yaml"
  ]
}
```
</details>

<details>
<summary>Stop Only Current Mode</summary>

```json
{
  "service": "/ugv/stop_all",
  "type": "ugv_interface/srv/StopAll",
  "request": {
    "stop_mode": true,
    "stop_webrtc": false,
    "stop_rosbridge": false
  }
}
```
</details>

<details>
<summary>Stop All Systems</summary>

```json
{
  "service": "/ugv/stop_all",
  "type": "ugv_interface/srv/StopAll",
  "request": {
    "stop_mode": true,
    "stop_webrtc": true,
    "stop_rosbridge": true
  }
}
```
</details>

## History

### 2025-12-11
- Added map operations: save and list maps
- Implemented background service management (WebRTC, ROSBridge)
- Added selective stopping via `/ugv/stop_all` flags
- Added runtime argument override support
- Added auto-start default mode parameter
- Enhanced idle mode with full teleoperation support
- Updated documentation to reflect current state

### 2025-11-23
- Initial implementation of ROS2 Launch Service API
- Created service definitions in ugv_interface
- Implemented launch manager node and process manager
- Created mode configuration and launch files
- Simplified mode files to be direct wrappers
- Successfully tested mode switching

---

**Design Evolution:**
Previous approaches tried:
1. Master launch file in ugv_bringup (failed - circular dependencies)
2. Separate ugv_master package (worked but not dynamic)
3. Bash script approach (worked but not ROS2-integrated)
4. **ROS2 Launch Service API** (current - fully functional with complete feature set)
