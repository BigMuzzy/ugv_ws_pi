import { KVNamespace, DurableObjectNamespace, DurableObjectState, WebSocket } from '@cloudflare/workers-types';

export interface Env {
	ROBOT_REGISTRY: KVNamespace;
    FLEET_DO: DurableObjectNamespace;
}

export default {
	async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
		const url = new URL(request.url);

        // CORS for OPTIONS
        if (request.method === 'OPTIONS') {
             return new Response(null, {
                headers: {
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                    'Access-Control-Allow-Headers': 'Content-Type'
                }
            });
        }

        // Route requests to the Durable Object
        const id = env.FLEET_DO.idFromName('default-fleet');
        const stub = env.FLEET_DO.get(id);

        return stub.fetch(request);
	},
};

export class FleetDO {
    state: DurableObjectState;
    env: Env;
    connectedRobots: Map<string, WebSocket>;

    constructor(state: DurableObjectState, env: Env) {
        this.state = state;
        this.env = env;
        this.connectedRobots = new Map();
    }

    async fetch(request: Request): Promise<Response> {
        const url = new URL(request.url);

        // 1. WebSocket Handler (/ws/robot)
		if (url.pathname === '/ws/robot') {
			const upgradeHeader = request.headers.get('Upgrade');
			if (!upgradeHeader || upgradeHeader !== 'websocket') {
				return new Response('Expected Upgrade: websocket', { status: 426 });
			}

			const [client, server] = Object.values(new WebSocketPair());
			
            this.handleSession(server);

			return new Response(null, {
				status: 101,
				webSocket: client,
			});
		}

        // 2. REST API: GET /robots
		if (request.method === 'GET' && url.pathname === '/robots') {
			const list = await this.env.ROBOT_REGISTRY.list({ prefix: 'robot:' });
			const robots = [];
			for (const key of list.keys) {
				const value = await this.env.ROBOT_REGISTRY.get(key.name, 'json');
				if (value) {
					robots.push({ id: key.name.replace('robot:', ''), ...value });
				}
			}
			return new Response(JSON.stringify(robots), {
				headers: { 
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*' 
                }
			});
		}

        // 3. REST API: POST /connect
		if (request.method === 'POST' && url.pathname === '/connect') {
			try {
				const body = await request.json() as any;
				const { robotId, operatorSessionId } = body;

				if (!robotId || !operatorSessionId) {
					return new Response('Missing robotId or operatorSessionId', { 
                        status: 400,
                        headers: { 'Access-Control-Allow-Origin': '*' }
                    });
				}

				const robotWs = this.connectedRobots.get(robotId);
				if (!robotWs) {
					return new Response('Robot not connected to this Fleet DO', { 
                        status: 404,
                        headers: { 'Access-Control-Allow-Origin': '*' }
                    });
				}

				// Send signal to robot
				const signal = {
					action: 'subscribe_cmd',
					sessionId: operatorSessionId,
					channel: 'cmd_vel'
				};
				robotWs.send(JSON.stringify(signal));

				return new Response(JSON.stringify({ success: true }), {
					headers: { 
                        'Content-Type': 'application/json',
                        'Access-Control-Allow-Origin': '*'
                    }
				});
			} catch (e) {
				return new Response('Error processing request', { 
                    status: 500,
                    headers: { 'Access-Control-Allow-Origin': '*' }
                });
			}
		}

        return new Response('Not Found', { status: 404 });
    }

    handleSession(webSocket: WebSocket) {
        webSocket.accept();

        let robotId: string | null = null;

        webSocket.addEventListener('message', async (event) => {
            try {
                const data = JSON.parse(event.data as string);
                
                if (data.type === 'status') {
                    if (data.robotId) {
                        robotId = data.robotId;
                        if (robotId) {
                            this.connectedRobots.set(robotId, webSocket);
                        
                            await this.env.ROBOT_REGISTRY.put(`robot:${robotId}`, JSON.stringify({
                                status: 'online',
                                sfuSessionId: data.sfuSessionId,
                                videoTrackName: data.videoTrackName,
                                lastSeen: Date.now()
                            }), { expirationTtl: 60 });
                        }
                    }
                }
            } catch (err) {
                console.error('Error parsing message', err);
            }
        });

        webSocket.addEventListener('close', async () => {
            if (robotId) {
                this.connectedRobots.delete(robotId);
                await this.env.ROBOT_REGISTRY.delete(`robot:${robotId}`);
            }
        });
        
        webSocket.addEventListener('error', async () => {
            if (robotId) {
                this.connectedRobots.delete(robotId);
            }
        });
    }
}
