/**
 * Fleet Worker - Robot Registry and Signaling Service
 * 
 * This Cloudflare Worker manages:
 * - Robot registration and heartbeat tracking
 * - WebSocket connections for real-time signaling
 * - Operator-to-robot connection orchestration
 */

import { KVNamespace, DurableObjectNamespace, DurableObjectState, WebSocket } from '@cloudflare/workers-types';

// =============================================================================
// Types & Interfaces
// =============================================================================

export interface Env {
    /** KV namespace for persistent robot registry */
    ROBOT_REGISTRY: KVNamespace;
    /** Durable Object binding for WebSocket state management */
    FLEET_DO: DurableObjectNamespace;
}

/** Robot status message sent via WebSocket */
interface RobotStatusMessage {
    type: 'status';
    robotId: string;
    sfuSessionId: string;
    videoTrackName: string;
}

/** Signal sent to robot to subscribe to operator's DataChannel */
interface SubscribeSignal {
    action: 'subscribe_cmd';
    sessionId: string;
    channel: string;
}

/** Robot entry stored in KV */
interface RobotEntry {
    status: 'online' | 'offline';
    sfuSessionId: string;
    videoTrackName: string;
    lastSeen: number;
}

/** Connect request body */
interface ConnectRequest {
    robotId: string;
    operatorSessionId: string;
}

// =============================================================================
// Constants
// =============================================================================

/** TTL for robot entries in KV (seconds) - robots must heartbeat within this window */
const ROBOT_TTL_SECONDS = 60;

/** CORS headers for browser access */
const CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
} as const;

/** JSON response headers with CORS */
const JSON_HEADERS = {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
} as const;

// =============================================================================
// Worker Entry Point
// =============================================================================

export default {
    /**
     * Main request handler - routes all requests to the FleetDO singleton.
     * 
     * The Worker itself is stateless; all state is managed by the Durable Object
     * which can maintain WebSocket connections and in-memory data structures.
     */
    async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
        // Handle CORS preflight requests at the edge (before routing to DO)
        if (request.method === 'OPTIONS') {
            return new Response(null, { headers: CORS_HEADERS });
        }

        // Route all requests to a single FleetDO instance.
        // Using a fixed name ('default-fleet') ensures all robots and operators
        // connect to the same DO instance for coordinated signaling.
        const id = env.FLEET_DO.idFromName('default-fleet');
        const stub = env.FLEET_DO.get(id);

        return stub.fetch(request);
    },
};

// =============================================================================
// Durable Object - Fleet State Manager
// =============================================================================

/**
 * FleetDO - Durable Object for managing fleet state and WebSocket connections.
 * 
 * Responsibilities:
 * - Maintain persistent WebSocket connections to robots
 * - Store robot metadata in KV with TTL for auto-cleanup
 * - Forward signaling messages between operators and robots
 * 
 * Why Durable Object?
 * - Regular Workers cannot hold WebSocket connections open
 * - DO provides in-memory state (connectedRobots map) that persists across requests
 * - Single instance ensures all signaling goes through one coordinator
 */
export class FleetDO {
    private readonly state: DurableObjectState;
    private readonly env: Env;
    
    /** 
     * In-memory map of connected robots.
     * Key: robotId, Value: WebSocket connection
     * This enables instant message delivery without KV lookups.
     */
    private readonly connectedRobots: Map<string, WebSocket>;

    constructor(state: DurableObjectState, env: Env) {
        this.state = state;
        this.env = env;
        this.connectedRobots = new Map();
    }

    /**
     * HTTP request handler for the Durable Object.
     * Routes to WebSocket upgrade or REST API handlers.
     */
    async fetch(request: Request): Promise<Response> {
        const url = new URL(request.url);

        // -----------------------------------------------------------------
        // WebSocket Endpoint: /ws/robot
        // Robots connect here to register and receive signaling messages
        // -----------------------------------------------------------------
        if (url.pathname === '/ws/robot') {
            return this.handleWebSocketUpgrade(request);
        }

        // -----------------------------------------------------------------
        // REST API: GET /robots
        // Returns list of all registered robots with their SFU details
        // -----------------------------------------------------------------
        if (request.method === 'GET' && url.pathname === '/robots') {
            return this.handleGetRobots();
        }

        // -----------------------------------------------------------------
        // REST API: POST /connect
        // Signals a robot to subscribe to an operator's DataChannel
        // -----------------------------------------------------------------
        if (request.method === 'POST' && url.pathname === '/connect') {
            return this.handleConnect(request);
        }

        // 404 for unknown routes
        return new Response('Not Found', { 
            status: 404,
            headers: { 'Access-Control-Allow-Origin': '*' }
        });
    }

    // =========================================================================
    // Request Handlers
    // =========================================================================

    /**
     * Upgrades HTTP request to WebSocket for robot connections.
     */
    private handleWebSocketUpgrade(request: Request): Response {
        const upgradeHeader = request.headers.get('Upgrade');
        if (upgradeHeader !== 'websocket') {
            return new Response('Expected Upgrade: websocket', { status: 426 });
        }

        // Create WebSocket pair - client goes to caller, server stays here
        const [client, server] = Object.values(new WebSocketPair());
        this.handleWebSocketSession(server);

        return new Response(null, {
            status: 101,
            webSocket: client,
        });
    }

    /**
     * Returns list of all registered robots from KV store.
     */
    private async handleGetRobots(): Promise<Response> {
        try {
            const list = await this.env.ROBOT_REGISTRY.list({ prefix: 'robot:' });
            const robots: Array<{ id: string } & RobotEntry> = [];

            // Fetch all robot entries in parallel for better performance
            const entries = await Promise.all(
                list.keys.map(async (key) => {
                    const value = await this.env.ROBOT_REGISTRY.get<RobotEntry>(key.name, 'json');
                    if (value) {
                        return { id: key.name.replace('robot:', ''), ...value };
                    }
                    return null;
                })
            );

            // Filter out null entries (expired or deleted)
            const validRobots = entries.filter((r): r is { id: string } & RobotEntry => r !== null);

            return new Response(JSON.stringify(validRobots), { headers: JSON_HEADERS });
        } catch (error) {
            console.error('Error fetching robots:', error);
            return new Response(JSON.stringify({ error: 'Failed to fetch robots' }), {
                status: 500,
                headers: JSON_HEADERS,
            });
        }
    }

    /**
     * Handles operator connect request - signals robot to subscribe to DataChannel.
     */
    private async handleConnect(request: Request): Promise<Response> {
        try {
            const body = await request.json() as ConnectRequest;
            const { robotId, operatorSessionId } = body;

            // Validate required fields
            if (!robotId || !operatorSessionId) {
                return new Response(
                    JSON.stringify({ error: 'Missing robotId or operatorSessionId' }),
                    { status: 400, headers: JSON_HEADERS }
                );
            }

            // Check if robot is connected
            const robotWs = this.connectedRobots.get(robotId);
            if (!robotWs) {
                return new Response(
                    JSON.stringify({ error: 'Robot not connected', robotId }),
                    { status: 404, headers: JSON_HEADERS }
                );
            }

            // Send subscription signal to robot
            const signal: SubscribeSignal = {
                action: 'subscribe_cmd',
                sessionId: operatorSessionId,
                channel: 'cmd_vel',
            };
            robotWs.send(JSON.stringify(signal));

            console.log(`Signaled robot ${robotId} to subscribe to operator ${operatorSessionId}`);

            return new Response(
                JSON.stringify({ success: true, robotId, operatorSessionId }),
                { headers: JSON_HEADERS }
            );
        } catch (error) {
            console.error('Error processing connect request:', error);
            return new Response(
                JSON.stringify({ error: 'Failed to process connect request' }),
                { status: 500, headers: JSON_HEADERS }
            );
        }
    }

    // =========================================================================
    // WebSocket Session Management
    // =========================================================================

    /**
     * Manages a robot's WebSocket session lifecycle.
     * 
     * Session Flow:
     * 1. Robot connects and sends status message with robotId
     * 2. We store the WebSocket in connectedRobots map
     * 3. We update KV with robot metadata (TTL for auto-cleanup)
     * 4. Robot sends periodic heartbeats to refresh TTL
     * 5. On disconnect, we clean up map and KV entries
     * 
     * @param webSocket - The server-side WebSocket to manage
     */
    private handleWebSocketSession(webSocket: WebSocket): void {
        webSocket.accept();

        // Track robotId for this session (set on first status message)
        let robotId: string | null = null;

        // ---------------------------------------------------------------------
        // Message Handler
        // ---------------------------------------------------------------------
        webSocket.addEventListener('message', async (event) => {
            try {
                const data = JSON.parse(event.data as string);

                // Handle robot status/heartbeat messages
                if (data.type === 'status' && this.isValidStatusMessage(data)) {
                    robotId = data.robotId;

                    // Store WebSocket reference for instant message delivery
                    this.connectedRobots.set(robotId, webSocket);

                    // Persist to KV with TTL (acts as heartbeat mechanism)
                    const entry: RobotEntry = {
                        status: 'online',
                        sfuSessionId: data.sfuSessionId,
                        videoTrackName: data.videoTrackName,
                        lastSeen: Date.now(),
                    };

                    await this.env.ROBOT_REGISTRY.put(
                        `robot:${robotId}`,
                        JSON.stringify(entry),
                        { expirationTtl: ROBOT_TTL_SECONDS }
                    );

                    console.log(`Robot ${robotId} registered/heartbeat - session: ${data.sfuSessionId}`);
                }
            } catch (err) {
                console.error('Error processing WebSocket message:', err);
            }
        });

        // ---------------------------------------------------------------------
        // Close Handler
        // ---------------------------------------------------------------------
        webSocket.addEventListener('close', async () => {
            if (robotId) {
                console.log(`Robot ${robotId} disconnected`);
                this.connectedRobots.delete(robotId);

                // Remove from KV immediately (don't wait for TTL)
                try {
                    await this.env.ROBOT_REGISTRY.delete(`robot:${robotId}`);
                } catch (err) {
                    console.error(`Error deleting robot ${robotId} from KV:`, err);
                }
            }
        });

        // ---------------------------------------------------------------------
        // Error Handler
        // ---------------------------------------------------------------------
        webSocket.addEventListener('error', (event) => {
            console.error(`WebSocket error for robot ${robotId}:`, event);
            if (robotId) {
                this.connectedRobots.delete(robotId);
                // Note: Don't delete from KV here - let TTL handle it
                // The close event will fire after error and handle cleanup
            }
        });
    }

    // =========================================================================
    // Utility Methods
    // =========================================================================

    /**
     * Type guard to validate robot status message structure.
     */
    private isValidStatusMessage(data: unknown): data is RobotStatusMessage {
        return (
            typeof data === 'object' &&
            data !== null &&
            'type' in data &&
            (data as RobotStatusMessage).type === 'status' &&
            'robotId' in data &&
            typeof (data as RobotStatusMessage).robotId === 'string' &&
            'sfuSessionId' in data &&
            'videoTrackName' in data
        );
    }
}
