# Shared Types

This directory contains TypeScript types shared between the Workers backend and React frontend.

## Usage

### In Workers

```typescript
import type { RobotInfo, SFUSessionInfo } from '@shared/types';
```

### In Frontend

```typescript
import type { RobotInfo, SFUSessionInfo } from '@shared/types';
```

## Type Categories

- **Robot Types**: Robot information, status, capabilities
- **WebRTC Types**: SFU sessions, ICE servers, SDP offers/answers
- **Rosbridge Types**: ROS2 message protocol types
- **ROS2 Message Types**: Common ROS2 messages (Twist, Odometry, etc.)
- **API Types**: Request/response types for REST endpoints
- **WebSocket Types**: WebSocket message types
- **Configuration Types**: Config structures for robot and fleet
- **Utility Types**: Generic utility types (Result, PaginatedResponse, etc.)

## Adding New Types

When adding new types:
1. Group related types together
2. Add JSDoc comments for complex types
3. Export all public types
4. Update this README with the new category
