/**
 * Fleet Management Workers - Main Entry Point
 *
 * Handles:
 * - API endpoints for Cloudflare Calls session management
 * - WebSocket proxy for rosbridge connections
 * - Authentication and authorization
 */

import {
  createSession,
  getSession,
  deleteSession,
  getIceServersEndpoint,
  handleOffer,
  getAnswer,
  addIceCandidate,
  type Env as CallsEnv
} from '../api/calls-session';

export interface Env {
  // KV Namespaces
  ROBOT_REGISTRY?: KVNamespace;

  // Durable Objects
  ROBOT_CONNECTION?: DurableObjectNamespace;

  // Secrets (set via wrangler secret put)
  CLOUDFLARE_CALLS_APP_ID?: string;
  CLOUDFLARE_CALLS_API_TOKEN?: string;
  CLOUDFLARE_TURN_SERVICE_ID?: string;
  CLOUDFLARE_TURN_API_TOKEN?: string;
  JWT_SECRET?: string;

  // Environment variables
  ENVIRONMENT: string;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    // CORS headers for development
    const corsHeaders = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    };

    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    try {
      // Health check endpoint
      if (url.pathname === '/health') {
        return new Response(JSON.stringify({
          status: 'ok',
          environment: env.ENVIRONMENT,
          timestamp: new Date().toISOString()
        }), {
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }

      // API routes - Phase 1: Cloudflare Calls Integration
      if (url.pathname.startsWith('/api/')) {
        // POST /api/sessions/create
        if (url.pathname === '/api/sessions/create' && request.method === 'POST') {
          return await createSession(request, env);
        }

        // GET /api/sessions/:robotId
        const sessionMatch = url.pathname.match(/^\/api\/sessions\/([^/]+)$/);
        if (sessionMatch && request.method === 'GET') {
          const robotId = sessionMatch[1];
          return await getSession(robotId, env);
        }

        // DELETE /api/sessions/:robotId
        if (sessionMatch && request.method === 'DELETE') {
          const robotId = sessionMatch[1];
          return await deleteSession(robotId, env);
        }

        // POST /api/sessions/:robotId/offer
        const offerMatch = url.pathname.match(/^\/api\/sessions\/([^/]+)\/offer$/);
        if (offerMatch && request.method === 'POST') {
          const robotId = offerMatch[1];
          return await handleOffer(robotId, request, env);
        }

        // GET /api/sessions/:robotId/answer
        const answerMatch = url.pathname.match(/^\/api\/sessions\/([^/]+)\/answer$/);
        if (answerMatch && request.method === 'GET') {
          const robotId = answerMatch[1];
          return await getAnswer(robotId, env);
        }

        // POST /api/sessions/:robotId/ice-candidate
        const iceMatch = url.pathname.match(/^\/api\/sessions\/([^/]+)\/ice-candidate$/);
        if (iceMatch && request.method === 'POST') {
          const robotId = iceMatch[1];
          return await addIceCandidate(robotId, request, env);
        }

        // GET /api/ice-servers
        if (url.pathname === '/api/ice-servers' && request.method === 'GET') {
          return await getIceServersEndpoint(env);
        }

        // Unknown API endpoint
        return new Response(JSON.stringify({
          error: 'Not Found',
          message: 'Unknown API endpoint'
        }), {
          status: 404,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }

      // WebSocket routes will be added in Phase 2
      if (url.pathname.startsWith('/ws/')) {
        return new Response(JSON.stringify({
          error: 'WebSocket endpoints not yet implemented',
          message: 'Phase 2 in progress'
        }), {
          status: 501,
          headers: { ...corsHeaders, 'Content-Type': 'application/json' }
        });
      }

      // Default response
      return new Response(JSON.stringify({
        name: 'Fleet Management Workers',
        version: '1.0.0',
        status: 'Phase 1 Active - Signaling Complete',
        endpoints: {
          health: '/health',
          api: {
            createSession: 'POST /api/sessions/create',
            getSession: 'GET /api/sessions/:robotId',
            deleteSession: 'DELETE /api/sessions/:robotId',
            sendOffer: 'POST /api/sessions/:robotId/offer',
            getAnswer: 'GET /api/sessions/:robotId/answer',
            addIceCandidate: 'POST /api/sessions/:robotId/ice-candidate',
            iceServers: 'GET /api/ice-servers'
          },
          websocket: '/ws/* (Phase 2)'
        }
      }), {
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });

    } catch (error) {
      return new Response(JSON.stringify({
        error: 'Internal Server Error',
        message: error instanceof Error ? error.message : 'Unknown error'
      }), {
        status: 500,
        headers: { ...corsHeaders, 'Content-Type': 'application/json' }
      });
    }
  }
};
