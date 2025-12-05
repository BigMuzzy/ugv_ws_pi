/**
 * Shared TypeScript types for Fleet Management System
 * Used by both Workers backend and React frontend
 */

// ============================================================================
// Robot Types
// ============================================================================

export interface RobotInfo {
  robotId: string;
  name: string;
  status: RobotStatus;
  lastSeen: string; // ISO timestamp
  batteryLevel?: number; // 0-100
  location?: {
    x: number;
    y: number;
    z: number;
  };
  capabilities?: string[];
}

export type RobotStatus = 'online' | 'offline' | 'error' | 'maintenance';

// ============================================================================
// WebRTC / Cloudflare Calls Types
// ============================================================================

export interface SFUSessionInfo {
  sessionId: string;
  robotId: string;
  created: string;
  expires: string;
  iceServers: RTCIceServer[];
  tracks?: unknown[]; // Cloudflare Calls track info
}

export interface RTCIceServer {
  urls: string | string[];
  username?: string;
  credential?: string;
}

export interface WebRTCOffer {
  type: 'offer';
  sdp: string;
}

export interface WebRTCAnswer {
  type: 'answer';
  sdp: string;
}

export interface ICECandidate {
  candidate: string;
  sdpMid: string | null;
  sdpMLineIndex: number | null;
}

// ============================================================================
// Rosbridge Protocol Types
// ============================================================================

export interface RosbridgeMessage {
  op: string;
  [key: string]: unknown;
}

export interface RosbridgeSubscribe extends RosbridgeMessage {
  op: 'subscribe';
  topic: string;
  type?: string;
  throttle_rate?: number;
  queue_length?: number;
}

export interface RosbridgePublish extends RosbridgeMessage {
  op: 'publish';
  topic: string;
  msg: unknown;
}

export interface RosbridgeAdvertise extends RosbridgeMessage {
  op: 'advertise';
  topic: string;
  type: string;
}

export interface RosbridgeUnadvertise extends RosbridgeMessage {
  op: 'unadvertise';
  topic: string;
}

export interface RosbridgeCallService extends RosbridgeMessage {
  op: 'call_service';
  service: string;
  args?: unknown;
}

// ============================================================================
// ROS2 Message Types (common ones)
// ============================================================================

export interface Twist {
  linear: {
    x: number;
    y: number;
    z: number;
  };
  angular: {
    x: number;
    y: number;
    z: number;
  };
}

export interface Odometry {
  header: Header;
  child_frame_id: string;
  pose: {
    pose: Pose;
    covariance: number[];
  };
  twist: {
    twist: Twist;
    covariance: number[];
  };
}

export interface Pose {
  position: {
    x: number;
    y: number;
    z: number;
  };
  orientation: {
    x: number;
    y: number;
    z: number;
    w: number;
  };
}

export interface Header {
  stamp: {
    sec: number;
    nanosec: number;
  };
  frame_id: string;
}

export interface BatteryState {
  header: Header;
  voltage: number;
  current: number;
  charge: number;
  capacity: number;
  design_capacity: number;
  percentage: number;
  power_supply_status: number;
  power_supply_health: number;
  power_supply_technology: number;
  present: boolean;
}

// ============================================================================
// API Request/Response Types
// ============================================================================

export interface CreateSessionRequest {
  robotId: string;
}

export interface CreateSessionResponse {
  success: boolean;
  session?: SFUSessionInfo;
  error?: string;
}

export interface GetSessionRequest {
  robotId: string;
}

export interface GetSessionResponse {
  success: boolean;
  session?: SFUSessionInfo;
  error?: string;
}

export interface AuthRequest {
  robotId: string;
  secret: string;
}

export interface AuthResponse {
  success: boolean;
  token?: string;
  expiresIn?: number;
  error?: string;
}

export interface HeartbeatRequest {
  robotId: string;
  timestamp: number;
  status: {
    ros_ok: boolean;
    battery?: number;
    location?: {
      x: number;
      y: number;
      z: number;
    };
  };
}

export interface HeartbeatResponse {
  success: boolean;
  acknowledged: boolean;
}

// ============================================================================
// WebSocket Message Types
// ============================================================================

export interface WSMessage {
  type: string;
  [key: string]: unknown;
}

export interface WSConnectMessage extends WSMessage {
  type: 'connect';
  robotId: string;
  token: string;
}

export interface WSDisconnectMessage extends WSMessage {
  type: 'disconnect';
  reason?: string;
}

export interface WSErrorMessage extends WSMessage {
  type: 'error';
  error: string;
  code?: string;
}

export interface WSDataMessage extends WSMessage {
  type: 'data';
  payload: unknown;
}

// ============================================================================
// Configuration Types
// ============================================================================

export interface FleetConfig {
  cloudEndpoint: string;
  environment: 'development' | 'staging' | 'production';
  heartbeatInterval: number;
  reconnectAttempts: number;
  reconnectDelay: number;
}

export interface VideoConfig {
  device: string;
  width: number;
  height: number;
  fps: number;
  codec: 'VP8' | 'VP9' | 'H264';
  bitrate: number;
}

export interface RobotConfig {
  robotId: string;
  name: string;
  cmdVelTopic: string;
  maxLinearSpeed: number;
  maxAngularSpeed: number;
  commandTimeoutMs: number;
  publishRateHz: number;
}

// ============================================================================
// Utility Types
// ============================================================================

export type Result<T, E = Error> =
  | { success: true; data: T }
  | { success: false; error: E };

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  hasMore: boolean;
}
