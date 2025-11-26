# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed - 2025-11-04

#### GMapping SLAM Map Not Updating Issue

**Problem:** Only the first laser scan was being added to the map. The robot could move around, but no new map pieces were added regardless of where it went.

**Root Cause:** Default GMapping parameters had very high update thresholds:
- `linearUpdate` was 1.0 meter (too large)
- `angularUpdate` was 0.5 radians (~28.6 degrees, too large)

**Solution:** Modified GMapping configuration parameters in `src/ugv_else/gmapping/slam_gmapping/launch/mapping.launch.py`

**Changes Made:**
- File: `src/ugv_else/gmapping/slam_gmapping/launch/mapping.launch.py`
- Added parameters to slam_gmapping node:
  - `linearUpdate: 0.1` - Process scan after robot moves 10cm (was 1.0m)
  - `angularUpdate: 0.1` - Process scan after robot rotates ~5.7 degrees (was ~28.6 degrees)
  - `temporalUpdate: 0.5` - Process scan after 0.5 seconds even without movement

**Impact:** Robot now updates the map much more frequently with smaller movements, enabling proper SLAM mapping functionality.

**Rebuild Required:** Yes - `colcon build --packages-select slam_gmapping`

---

## How to Use This Changelog

### When Making Changes

Add entries under `[Unreleased]` section using these categories:

- **Added** - New features or files
- **Changed** - Changes to existing functionality
- **Deprecated** - Soon-to-be removed features
- **Removed** - Removed features
- **Fixed** - Bug fixes
- **Security** - Security-related changes

### Entry Format

```markdown
### [Category] - YYYY-MM-DD

#### Brief Title of Change

**Problem:** (if fixing a bug)
**Solution:**
**Changes Made:**
- File: path/to/file.ext
  - Description of change

**Impact:**
**Rebuild Required:** Yes/No - commands if needed
```

### Example Entry

```markdown
### Added - 2025-11-04

#### New Autonomous Navigation Feature

**Solution:** Implemented waypoint-based navigation using Nav2
**Changes Made:**
- File: src/ugv_main/ugv_nav/launch/navigation.launch.py
  - Created new launch file for Nav2 stack
- File: src/ugv_main/ugv_nav/config/nav2_params.yaml
  - Added navigation parameters configuration

**Impact:** Robot can now navigate autonomously to GPS waypoints
**Rebuild Required:** Yes - `colcon build --packages-select ugv_nav`
```

---

## Version History

When you reach significant milestones, you can create version tags:

### Template for Versioned Releases

```markdown
## [1.0.0] - YYYY-MM-DD

### Added
- Initial release with SLAM mapping
- LiDAR integration with LD06

### Fixed
- GMapping map update frequency

[1.0.0]: Description or link to this version
```
