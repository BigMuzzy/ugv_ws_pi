# UGV Mode Manager — ROS2 Design Document

## Overview

Design a `mode_manager` ROS2 package that orchestrates dynamic switching between operation modes (MAPPING, NAVIGATION, TELEOPERATION, IDLE) on a ROS2-based UGV. Uses the **Lifecycle Node** pattern to activate/deactivate managed subsystems without loading/unloading nodes.

**Localization strategy**: Uses the traditional AMCL + map_server approach for NAVIGATION mode (not slam_toolbox localization). slam_toolbox is used only for MAPPING.

## System Architecture

### Always-On Base Layer (never transitions, always active)
- `robot_state_publisher` — TF tree
- Sensor drivers (LiDAR, IMU, cameras) — publish data regardless of mode
- `ros2_control` hardware interface — motor control
- `twist_mux` — cmd_vel priority multiplexer (safety layer)
- `mode_manager` node — the orchestrator itself

### Mode-Managed Layer (lifecycle-controlled)
- `slam_toolbox` — lifecycle node, used only in MAPPING mode
- `map_server` — lifecycle node, serves saved OccupancyGrid map in NAVIGATION mode
- `amcl` — lifecycle node, particle filter localization in NAVIGATION mode
- Nav2 stack (via `nav2_lifecycle_manager`) — controller_server, planner_server, bt_navigator, costmap nodes, etc.

### Mode Definitions

```
Mode          slam_toolbox     map_server     AMCL          Nav2 Stack    cmd_vel Source
────          ────────────     ──────────     ────          ──────────    ──────────────
IDLE          inactive         inactive       inactive      inactive      none
MAPPING       active           inactive       inactive      inactive      teleop (joystick)
NAVIGATION    inactive         active         active        active        nav2 (controller_server)
TELEOP        inactive         inactive       inactive      inactive      teleop (joystick)
```

### MAPPING -> NAVIGATION Transition (most complex)

This is the critical handoff. The sequence is:

1. **Save map from slam_toolbox**:
   - Call `/slam_toolbox/serialize_map` to save pose graph (for potential future SLAM use)
   - Call `/map_saver/save_map` service (from `nav2_map_server`) to save OccupancyGrid as `.pgm` + `.yaml`
2. **Deactivate slam_toolbox**: lifecycle deactivate -> cleanup
3. **Activate map_server**: configure (with path to saved map .yaml) -> activate
4. **Activate AMCL**: configure -> activate (needs /map topic from map_server)
5. **Start Nav2**: call `nav2_lifecycle_manager` startup (manages controller, planner, BT, costmaps)

AMCL needs an initial pose estimate. Options:
- Use the last known pose from slam_toolbox as the initial pose for AMCL (publish to `/initialpose`)
- Rely on the operator to set initial pose via RViz2
- Configure AMCL with `set_initial_pose: true` and provide `initial_pose_x/y/yaw` from slam_toolbox's last output

### twist_mux Priority Configuration (always enforced)

```yaml
# twist_mux.yaml
twist_mux:
  ros__parameters:
    topics:
      navigation:
        topic: nav_cmd_vel
        timeout: 0.5
        priority: 10
      teleop:
        topic: teleop_cmd_vel
        timeout: 0.5
        priority: 20       # higher = takes precedence
      emergency_stop:
        topic: estop_cmd_vel
        timeout: 0.1
        priority: 100      # always wins
```

Teleop always overrides Nav2, e-stop always overrides everything. Safety-critical — do NOT remove twist_mux even if modes seem mutually exclusive.

## mode_manager Node Specification

### Package Structure

```
mode_manager/
├── CMakeLists.txt (or setup.py for Python)
├── package.xml
├── config/
│   └── mode_manager.yaml          # mode definitions, managed node names
├── launch/
│   └── mode_manager.launch.py     # launch mode_manager + twist_mux
├── msg/
│   └── ModeStatus.msg             # current mode + timestamp
├── srv/
│   └── SetMode.srv                # request mode transition
├── src/ (or mode_manager/)
│   ├── mode_manager_node.cpp      # main node (or .py)
│   └── lifecycle_client.cpp       # helper to call lifecycle services
└── test/
    └── test_mode_transitions.py   # integration tests
```

### Custom Interfaces

```
# srv/SetMode.srv
string mode            # IDLE, MAPPING, NAVIGATION, TELEOP
---
bool success
string message         # human-readable result or error
string previous_mode
```

```
# msg/ModeStatus.msg
string current_mode
string previous_mode
builtin_interfaces/Time timestamp
bool transition_in_progress
```

### Node Parameters (config/mode_manager.yaml)

```yaml
mode_manager:
  ros__parameters:
    initial_mode: "IDLE"

    # Names of lifecycle nodes to manage directly
    slam_toolbox_node: "slam_toolbox"
    map_server_node: "map_server"
    amcl_node: "amcl"

    # Nav2 lifecycle manager service names
    nav2_lifecycle_manager_startup_service: "/lifecycle_manager_navigation/manage_nodes"

    # Transition timeout (seconds)
    transition_timeout: 10.0

    # Map saving configuration
    auto_save_map_on_mode_switch: true
    map_save_path: "/maps/latest_map"
    map_yaml_path: "/maps/latest_map.yaml"    # map_server loads this

    # Whether to auto-set AMCL initial pose from slam_toolbox's last pose
    auto_set_initial_pose: true

    # Valid transitions (for safety)
    allowed_transitions:
      - "IDLE->MAPPING"
      - "IDLE->NAVIGATION"      # requires a previously saved map
      - "IDLE->TELEOP"
      - "MAPPING->IDLE"
      - "MAPPING->NAVIGATION"   # saves map, deactivates SLAM, activates map_server+AMCL+Nav2
      - "NAVIGATION->IDLE"
      - "NAVIGATION->TELEOP"
      - "TELEOP->IDLE"
      - "TELEOP->NAVIGATION"    # requires a previously saved map
```

### ROS2 Interfaces Published/Subscribed

| Direction | Name | Type | Description |
|---|---|---|---|
| Service | `/mode_manager/set_mode` | `mode_manager/srv/SetMode` | Request mode transition |
| Publisher | `/mode_manager/status` | `mode_manager/msg/ModeStatus` | Current mode (latched/transient_local) |
| Publisher | `/initialpose` | `geometry_msgs/msg/PoseWithCovarianceStamped` | Set AMCL initial pose from SLAM |
| Client | `/slam_toolbox/change_state` | `lifecycle_msgs/srv/ChangeState` | Lifecycle control for SLAM |
| Client | `/slam_toolbox/get_state` | `lifecycle_msgs/srv/GetState` | Query SLAM state |
| Client | `/map_server/change_state` | `lifecycle_msgs/srv/ChangeState` | Lifecycle control for map_server |
| Client | `/amcl/change_state` | `lifecycle_msgs/srv/ChangeState` | Lifecycle control for AMCL |
| Client | `/lifecycle_manager_navigation/manage_nodes` | `std_srvs/srv/Trigger` | Nav2 startup/shutdown |
| Client | `/slam_toolbox/serialize_map` | `slam_toolbox/srv/SerializePoseGraph` | Save pose graph |
| Client | `/map_saver/save_map` | `nav2_msgs/srv/SaveMap` | Save OccupancyGrid .pgm/.yaml |

### Transition Logic (Pseudocode)

```python
class ModeManager(Node):

    current_mode = "IDLE"
    transition_lock = Lock()
    last_slam_pose = None  # Track last known pose from /tf for AMCL init

    def handle_set_mode(self, request, response):
        target_mode = request.mode.upper()

        if target_mode == self.current_mode:
            response.success = True
            response.message = f"Already in {target_mode}"
            return response

        if not self.is_transition_allowed(self.current_mode, target_mode):
            response.success = False
            response.message = f"Transition {self.current_mode} -> {target_mode} not allowed"
            return response

        # NAVIGATION requires a saved map (unless coming from MAPPING which saves it)
        if target_mode == "NAVIGATION" and self.current_mode != "MAPPING":
            if not self.map_file_exists():
                response.success = False
                response.message = "No saved map available. Run MAPPING first."
                return response

        with self.transition_lock:
            self.publish_status(transition_in_progress=True)

            try:
                # Step 1: Teardown current mode
                self.teardown_mode(self.current_mode)

                # Step 2: Intermediate step for MAPPING -> NAVIGATION
                if self.current_mode == "MAPPING" and target_mode == "NAVIGATION":
                    self.save_map_and_record_pose()

                # Step 3: Setup target mode
                self.setup_mode(target_mode)

                previous = self.current_mode
                self.current_mode = target_mode
                self.publish_status(transition_in_progress=False)

                response.success = True
                response.previous_mode = previous
                response.message = f"Switched to {target_mode}"

            except TransitionError as e:
                self.emergency_idle()
                response.success = False
                response.message = str(e)

        return response

    def teardown_mode(self, current_mode):
        if current_mode == "MAPPING":
            self.deactivate_slam()

        elif current_mode == "NAVIGATION":
            self.shutdown_nav2()        # Nav2 stack via lifecycle_manager
            self.deactivate_amcl()      # AMCL lifecycle
            self.deactivate_map_server() # map_server lifecycle

        elif current_mode == "TELEOP":
            pass  # nothing to teardown

    def save_map_and_record_pose(self):
        """Called during MAPPING -> NAVIGATION transition before SLAM is deactivated."""
        # 1. Record current robot pose from /tf (map->base_link)
        self.last_slam_pose = self.lookup_transform("map", "base_link")

        # 2. Save pose graph (slam_toolbox format, for future use)
        self.call_serialize_map(self.map_save_path)

        # 3. Save OccupancyGrid as .pgm + .yaml (for map_server)
        self.call_save_map(self.map_save_path)

    def setup_mode(self, mode):
        if mode == "MAPPING":
            self.configure_and_activate_slam()

        elif mode == "NAVIGATION":
            # 1. Start map_server with saved map
            self.configure_map_server(self.map_yaml_path)
            self.activate_map_server()

            # 2. Start AMCL
            self.configure_and_activate_amcl()

            # 3. Set initial pose if available
            if self.auto_set_initial_pose and self.last_slam_pose:
                self.publish_initial_pose(self.last_slam_pose)

            # 4. Start Nav2 stack (planner, controller, BT, costmaps)
            self.startup_nav2()

        elif mode == "TELEOP":
            pass  # twist_mux routes teleop; nothing to start

        elif mode == "IDLE":
            pass  # everything already torn down

    # === Lifecycle helper methods ===

    def configure_and_activate_slam(self):
        self.call_change_state("slam_toolbox", Transition.CONFIGURE)
        self.wait_for_state("slam_toolbox", State.INACTIVE)
        self.call_change_state("slam_toolbox", Transition.ACTIVATE)
        self.wait_for_state("slam_toolbox", State.ACTIVE)

    def deactivate_slam(self):
        self.call_change_state("slam_toolbox", Transition.DEACTIVATE)
        self.wait_for_state("slam_toolbox", State.INACTIVE)
        self.call_change_state("slam_toolbox", Transition.CLEANUP)
        self.wait_for_state("slam_toolbox", State.UNCONFIGURED)

    def configure_map_server(self, yaml_path):
        # Set the yaml_filename parameter before configuring
        self.set_remote_parameter("map_server", "yaml_filename", yaml_path)
        self.call_change_state("map_server", Transition.CONFIGURE)
        self.wait_for_state("map_server", State.INACTIVE)

    def activate_map_server(self):
        self.call_change_state("map_server", Transition.ACTIVATE)
        self.wait_for_state("map_server", State.ACTIVE)

    def deactivate_map_server(self):
        self.call_change_state("map_server", Transition.DEACTIVATE)
        self.call_change_state("map_server", Transition.CLEANUP)

    def configure_and_activate_amcl(self):
        self.call_change_state("amcl", Transition.CONFIGURE)
        self.wait_for_state("amcl", State.INACTIVE)
        self.call_change_state("amcl", Transition.ACTIVATE)
        self.wait_for_state("amcl", State.ACTIVE)

    def deactivate_amcl(self):
        self.call_change_state("amcl", Transition.DEACTIVATE)
        self.call_change_state("amcl", Transition.CLEANUP)

    def startup_nav2(self):
        # Call /lifecycle_manager_navigation startup service
        # This manages controller_server, planner_server, bt_navigator, costmap nodes
        ...

    def shutdown_nav2(self):
        # Call /lifecycle_manager_navigation shutdown service
        ...

    def publish_initial_pose(self, pose):
        # Publish to /initialpose for AMCL
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = "map"
        msg.pose.pose = pose
        # Set reasonable covariance
        self.initial_pose_pub.publish(msg)
```

### Error Handling and Safety

1. **Transition timeout**: If any lifecycle transition doesn't complete within `transition_timeout` seconds, abort and go to IDLE
2. **Emergency IDLE**: On any transition failure, attempt to deactivate all managed nodes and enter IDLE
3. **twist_mux safety net**: Even if mode_manager crashes, twist_mux still enforces cmd_vel priorities — teleop override always works
4. **Transition locking**: Only one transition at a time; reject concurrent requests
5. **State verification**: After each transition, verify node states match expected values via `GetState` service calls
6. **Map existence check**: IDLE->NAVIGATION and TELEOP->NAVIGATION require a previously saved map; reject if no map exists

### Critical Implementation Notes

- **map_server configuration**: `map_server` needs `yaml_filename` parameter set BEFORE the configure transition. Use `set_parameters` service to set the map path before calling configure.

- **AMCL initial pose**: After activating AMCL, it needs an initial pose estimate. The mode_manager captures the last robot pose from `/tf` (map->base_link) before deactivating slam_toolbox, then publishes it to `/initialpose` after AMCL is active. Without this, AMCL starts with a uniform distribution and takes time to converge.

- **Nav2 lifecycle manager**: Nav2's `lifecycle_manager` already handles the lifecycle of all Nav2 nodes (controller_server, planner_server, etc.). You call its startup/shutdown service — do NOT manage individual Nav2 nodes yourself. However, map_server and AMCL may or may not be included in Nav2's lifecycle_manager depending on your Nav2 config. If they are included, let Nav2 manage them. If not, mode_manager manages them directly (as shown above).

- **Nav2 lifecycle_manager configuration**: Check whether your Nav2 `lifecycle_manager` config includes `map_server` and `amcl` in its `node_names` list. If it does, you should NOT manage them separately — just call Nav2's startup/shutdown. If it doesn't (common when you want mode_manager to have more granular control), manage them directly as shown above.

- **Map saving**: Use `nav2_map_server`'s `map_saver_cli` or the `/map_saver/save_map` service to save the OccupancyGrid. The slam_toolbox `serialize_map` saves in its own pose-graph format; you need BOTH if you want to resume SLAM later from the saved graph.

### slam_toolbox vs AMCL Comparison (design rationale)

| Feature | AMCL (chosen for NAVIGATION) | slam_toolbox localization |
|---|---|---|
| Algorithm | Particle filter (MCL) | Pose graph optimization |
| Map format | OccupancyGrid (.pgm + .yaml) | Pose graph (serialized) |
| CPU usage | Lower | Higher |
| Maturity | Very mature, widely deployed | Mature |
| Integration | Native Nav2, well-documented | Works but less standard for Nav2 |
| Separation | Clean separation: SLAM for mapping, AMCL for nav | Same tool for both (dual mode) |

The traditional approach (AMCL + map_server) was chosen for cleaner separation of concerns and lower resource usage during navigation.

## Launch File Structure

```python
# launch/ugv_bringup.launch.py — top-level launch
from launch import LaunchDescription
from launch_ros.actions import Node, LifecycleNode
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource

def generate_launch_description():
    return LaunchDescription([
        # === Always-On Base Layer ===
        # robot_state_publisher (always active)
        # sensor drivers (always active)
        # ros2_control hardware interface + controllers (always active)
        # twist_mux with priority config (always active)
        Node(
            package='twist_mux',
            executable='twist_mux',
            name='twist_mux',
            parameters=[twist_mux_config],
            remappings=[('/cmd_vel_out', '/cmd_vel')],
        ),

        # === Mode-Managed Layer (start unconfigured, mode_manager controls lifecycle) ===

        # slam_toolbox — MAPPING mode only
        LifecycleNode(
            package='slam_toolbox',
            executable='async_slam_toolbox_node',
            name='slam_toolbox',
            parameters=[slam_toolbox_config],
            # Starts unconfigured — mode_manager will configure+activate when entering MAPPING
        ),

        # map_server — NAVIGATION mode only
        LifecycleNode(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            parameters=[{'yaml_filename': ''}],  # Set by mode_manager before configure
        ),

        # AMCL — NAVIGATION mode only
        LifecycleNode(
            package='nav2_amcl',
            executable='amcl',
            name='amcl',
            parameters=[amcl_config],
        ),

        # Nav2 stack with lifecycle_manager (autostart: false)
        # NOTE: Ensure map_server and amcl are NOT in nav2 lifecycle_manager's node_names
        #       since mode_manager handles them directly
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(nav2_launch),
            launch_arguments={
                'autostart': 'false',
                'use_lifecycle_manager': 'true',
            }.items(),
        ),

        # === Orchestrator ===
        Node(
            package='mode_manager',
            executable='mode_manager_node',
            name='mode_manager',
            parameters=[mode_manager_config],
            output='screen',
        ),
    ])
```

## Testing Plan

### Unit Tests
- Transition validation logic (allowed/disallowed transitions)
- Mode definition parsing from config
- Map existence check logic

### Integration Tests (launch_testing)
1. **Start system in IDLE** — verify all managed nodes are unconfigured/inactive
2. **IDLE -> MAPPING** — verify slam_toolbox activates
3. **MAPPING -> NAVIGATION** — verify: map saved, slam deactivated, map_server activated with saved map, AMCL activated with initial pose, Nav2 started
4. **NAVIGATION -> TELEOP** — verify: Nav2 shut down, AMCL deactivated, map_server deactivated
5. **TELEOP -> IDLE** — verify clean state
6. **IDLE -> NAVIGATION (no map)** — verify rejection with error message
7. **Invalid transition** — verify rejection and state unchanged
8. **Timeout handling** — simulate slow lifecycle transition, verify fallback to IDLE

### Manual Testing
- Drive robot in MAPPING mode, build map
- Switch to NAVIGATION, verify robot localizes on built map (AMCL particles converge)
- Send nav goal, verify autonomous driving
- Override with joystick (twist_mux), verify teleop takes priority
- Switch to TELEOP, verify Nav2 + AMCL + map_server stop
- Switch back to NAVIGATION from TELEOP, verify re-localization on saved map

## Dependencies

```xml
<!-- package.xml -->
<depend>rclcpp</depend>          <!-- or rclpy -->
<depend>lifecycle_msgs</depend>
<depend>std_srvs</depend>
<depend>geometry_msgs</depend>
<depend>nav2_msgs</depend>
<depend>rosidl_default_generators</depend>
<depend>slam_toolbox</depend>     <!-- for serialize_map service type -->
<depend>twist_mux</depend>
<depend>tf2_ros</depend>          <!-- for looking up last SLAM pose -->
```

## Implementation Order

1. Create package skeleton with `ros2 pkg create mode_manager`
2. Define custom interfaces (SetMode.srv, ModeStatus.msg)
3. Implement lifecycle client helper (reusable async service caller with timeout)
4. Implement mode_manager_node with IDLE <-> TELEOP transitions first (simplest, no lifecycle calls)
5. Add slam_toolbox lifecycle management (IDLE <-> MAPPING)
6. Add map saving logic (serialize_map + save_map services)
7. Add map_server + AMCL lifecycle management (IDLE <-> NAVIGATION, requires pre-saved map)
8. Add Nav2 lifecycle management via nav2_lifecycle_manager (complete NAVIGATION mode)
9. Implement MAPPING -> NAVIGATION compound transition (save map, capture pose, transition all nodes, set initial pose)
10. Add parameter-driven configuration and allowed_transitions validation
11. Write launch files
12. Add integration tests with launch_testing
