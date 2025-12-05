/**
 * Cloudflare Calls Session Management API
 *
 * Handles:
 * - Creating SFU sessions for robots
 * - Retrieving session info for viewers to join
 * - Managing session lifecycle
 * - Storing session data in Workers KV
 */

import type { SFUSessionInfo, RTCIceServer } from '../../shared/types';

export interface Env {
  ROBOT_REGISTRY?: KVNamespace;
  CLOUDFLARE_CALLS_APP_ID?: string;
  CLOUDFLARE_CALLS_API_TOKEN?: string;
  CLOUDFLARE_TURN_SERVICE_ID?: string;
  CLOUDFLARE_TURN_API_TOKEN?: string;
  ENVIRONMENT: string;
}

// Cloudflare Calls API base URL
const CALLS_API_BASE = 'https://rtc.live.cloudflare.com/v1';

// Types for signaling
interface RTCSessionDescriptionInit {
  type: 'offer' | 'answer' | 'pranswer' | 'rollback';
  sdp?: string;
}

interface RTCIceCandidateInit {
  candidate?: string;
  sdpMLineIndex?: number | null;
  sdpMid?: string | null;
  usernameFragment?: string | null;
}

/**
 * Create a new SFU session for a robot
 * POST /api/sessions/create
 */
export async function createSession(
  request: Request,
  env: Env
): Promise<Response> {
  try {
    const body = await request.json() as { robotId: string };
    const { robotId } = body;

    if (!robotId) {
      return jsonError('Missing robotId', 400);
    }

    // Validate Cloudflare Calls credentials
    if (!env.CLOUDFLARE_CALLS_APP_ID || !env.CLOUDFLARE_CALLS_API_TOKEN) {
      console.error('Missing Cloudflare Calls credentials');
      return jsonError('Cloudflare Calls not configured', 500);
    }

    // Create new session with Cloudflare Calls API
    // Try without a body first, or with empty object
    const callsResponse = await fetch(
      `${CALLS_API_BASE}/apps/${env.CLOUDFLARE_CALLS_APP_ID}/sessions/new`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.CLOUDFLARE_CALLS_API_TOKEN}`,
        },
      }
    );

    if (!callsResponse.ok) {
      const errorText = await callsResponse.text();
      console.error('Cloudflare Calls API error:', errorText);
      return jsonError(`Failed to create session: ${errorText}`, callsResponse.status);
    }

    const callsData = await callsResponse.json() as {
      sessionId: string;
      sessionDescription?: unknown;
    };

    // Get ICE servers (TURN credentials)
    const iceServers = await getIceServers(env);

    // Build session info
    const now = new Date();
    const expires = new Date(now.getTime() + 3600 * 1000); // 1 hour TTL

    const sessionInfo: SFUSessionInfo = {
      sessionId: callsData.sessionId,
      robotId,
      created: now.toISOString(),
      expires: expires.toISOString(),
      iceServers,
    };

    // Store session info in KV with 1 hour TTL
    if (env.ROBOT_REGISTRY) {
      await env.ROBOT_REGISTRY.put(
        `session:${robotId}`,
        JSON.stringify(sessionInfo),
        { expirationTtl: 3600 }
      );
    }

    return jsonResponse({
      success: true,
      session: sessionInfo,
    });
  } catch (error) {
    console.error('Error creating session:', error);
    return jsonError(
      error instanceof Error ? error.message : 'Unknown error',
      500
    );
  }
}

/**
 * Get session info for a robot (for viewers to join)
 * GET /api/sessions/:robotId
 */
export async function getSession(
  robotId: string,
  env: Env
): Promise<Response> {
  try {
    if (!robotId) {
      return jsonError('Missing robotId', 400);
    }

    // Retrieve session from KV
    if (!env.ROBOT_REGISTRY) {
      return jsonError('Robot registry not configured', 500);
    }

    const sessionData = await env.ROBOT_REGISTRY.get(`session:${robotId}`);

    if (!sessionData) {
      return jsonError('Session not found for robot', 404);
    }

    const sessionInfo = JSON.parse(sessionData) as SFUSessionInfo;

    // Check if session has expired
    const expires = new Date(sessionInfo.expires);
    if (expires < new Date()) {
      // Clean up expired session
      await env.ROBOT_REGISTRY.delete(`session:${robotId}`);
      return jsonError('Session expired', 410);
    }

    return jsonResponse({
      success: true,
      session: sessionInfo,
    });
  } catch (error) {
    console.error('Error getting session:', error);
    return jsonError(
      error instanceof Error ? error.message : 'Unknown error',
      500
    );
  }
}

/**
 * Delete/close a session
 * DELETE /api/sessions/:robotId
 */
export async function deleteSession(
  robotId: string,
  env: Env
): Promise<Response> {
  try {
    if (!robotId) {
      return jsonError('Missing robotId', 400);
    }

    if (!env.ROBOT_REGISTRY) {
      return jsonError('Robot registry not configured', 500);
    }

    // Get session info to get sessionId
    const sessionData = await env.ROBOT_REGISTRY.get(`session:${robotId}`);

    if (sessionData) {
      const sessionInfo = JSON.parse(sessionData) as SFUSessionInfo;

      // Optionally: Call Cloudflare Calls API to close the session
      // (Not strictly necessary as sessions expire automatically)
      if (env.CLOUDFLARE_CALLS_APP_ID && env.CLOUDFLARE_CALLS_API_TOKEN) {
        try {
          await fetch(
            `${CALLS_API_BASE}/apps/${env.CLOUDFLARE_CALLS_APP_ID}/sessions/${sessionInfo.sessionId}`,
            {
              method: 'DELETE',
              headers: {
                'Authorization': `Bearer ${env.CLOUDFLARE_CALLS_API_TOKEN}`,
              },
            }
          );
        } catch (error) {
          console.error('Error closing Cloudflare session:', error);
          // Continue anyway to clean up KV
        }
      }

      // Remove from KV
      await env.ROBOT_REGISTRY.delete(`session:${robotId}`);
    }

    return jsonResponse({
      success: true,
      message: 'Session deleted',
    });
  } catch (error) {
    console.error('Error deleting session:', error);
    return jsonError(
      error instanceof Error ? error.message : 'Unknown error',
      500
    );
  }
}

/**
 * Get ICE servers (TURN credentials) from Cloudflare
 */
async function getIceServers(env: Env): Promise<RTCIceServer[]> {
  // Default STUN server
  const iceServers: RTCIceServer[] = [
    { urls: 'stun:stun.cloudflare.com:3478' },
  ];

  // If Cloudflare TURN is configured, fetch credentials
  if (env.CLOUDFLARE_TURN_SERVICE_ID && env.CLOUDFLARE_TURN_API_TOKEN) {
    try {
      const turnResponse = await fetch(
        `https://rtc.live.cloudflare.com/v1/turn/keys/${env.CLOUDFLARE_TURN_SERVICE_ID}/credentials/generate`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${env.CLOUDFLARE_TURN_API_TOKEN}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            ttl: 86400, // 24 hours
          }),
        }
      );

      if (turnResponse.ok) {
        const turnData = await turnResponse.json() as {
          iceServers: {
            urls: string | string[];
            username?: string;
            credential?: string;
          };
        };

        iceServers.push(turnData.iceServers);
      } else {
        console.warn('Failed to get TURN credentials, using STUN only');
      }
    } catch (error) {
      console.error('Error fetching TURN credentials:', error);
      // Continue with STUN only
    }
  }

  return iceServers;
}

/**
 * Get ICE servers endpoint
 * GET /api/ice-servers
 */
export async function getIceServersEndpoint(env: Env): Promise<Response> {
  try {
    const iceServers = await getIceServers(env);

    return jsonResponse({
      success: true,
      iceServers,
    });
  } catch (error) {
    console.error('Error getting ICE servers:', error);
    return jsonError(
      error instanceof Error ? error.message : 'Unknown error',
      500
    );
  }
}

/**
 * Handle WebRTC offer from robot or viewer
 * POST /api/sessions/:robotId/offer
 * 
 * This endpoint receives an SDP offer and forwards it to the Cloudflare Calls SFU.
 * The SFU responds with an SDP answer.
 */
export async function handleOffer(
  robotId: string,
  request: Request,
  env: Env
): Promise<Response> {
  try {
    const body = await request.json() as { offer: RTCSessionDescriptionInit };
    const { offer } = body;

    if (!offer || !offer.sdp) {
      return jsonError('Missing or invalid offer', 400);
    }

    // Get session info
    if (!env.ROBOT_REGISTRY) {
      return jsonError('Robot registry not configured', 500);
    }

    const sessionData = await env.ROBOT_REGISTRY.get(`session:${robotId}`);
    if (!sessionData) {
      return jsonError('Session not found', 404);
    }

    const sessionInfo = JSON.parse(sessionData) as SFUSessionInfo;

    // Validate Cloudflare Calls credentials
    if (!env.CLOUDFLARE_CALLS_APP_ID || !env.CLOUDFLARE_CALLS_API_TOKEN) {
      return jsonError('Cloudflare Calls not configured', 500);
    }

    // Parse SDP to extract mid values
    // Handle both \r\n and \n
    const sdpLines = offer.sdp!.split(/\r?\n/);
    const mids: string[] = [];
    for (const line of sdpLines) {
      if (line.startsWith('a=mid:')) {
        const mid = line.substring(6).trim();
        mids.push(mid);
      }
    }

    console.log('Extracted mids from SDP:', mids);

    // Build tracks array with mids from SDP
    // Use a unique track name to avoid any potential conflicts or stale state
    const timestamp = Date.now();
    const tracks = mids.map((mid, index) => ({
      location: 'local',
      trackName: `${robotId}_track_${index}_${timestamp}`,
      mid: mid,
    }));

    // Build request body - only include tracks if we have them
    const requestBody: {
      sessionDescription: { type: string; sdp: string };
      tracks?: Array<{ location: string; trackName: string; mid: string }>;
    } = {
      sessionDescription: {
        type: offer.type,
        sdp: offer.sdp,
      },
    };

    if (tracks.length > 0) {
      requestBody.tracks = tracks;
    }

    console.log('Request body:', JSON.stringify(requestBody, null, 2));

    // Send offer to Cloudflare Calls SFU and get answer
    // For Cloudflare Calls, we use the tracks endpoint to add tracks with SDP
    const tracksResponse = await fetch(
      `${CALLS_API_BASE}/apps/${env.CLOUDFLARE_CALLS_APP_ID}/sessions/${sessionInfo.sessionId}/tracks/new`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.CLOUDFLARE_CALLS_API_TOKEN}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      }
    );

    if (!tracksResponse.ok) {
      const errorText = await tracksResponse.text();
      console.error('Cloudflare Calls tracks API error:', errorText);
      return jsonError(`Failed to process offer: ${errorText}`, tracksResponse.status);
    }

    const tracksData = await tracksResponse.json() as {
      sessionDescription?: RTCSessionDescriptionInit;
      tracks?: unknown[];
      errorCode?: string;
      errorDescription?: string;
    };

    if (!tracksData.sessionDescription) {
      return jsonError('No answer received from SFU', 500);
    }

    // Store the tracks info in session
    sessionInfo.tracks = tracksData.tracks;
    sessionInfo.offer = offer; // Store the robot's offer
    await env.ROBOT_REGISTRY.put(
      `session:${robotId}`,
      JSON.stringify(sessionInfo),
      { expirationTtl: 3600 }
    );

    return jsonResponse({
      success: true,
      answer: tracksData.sessionDescription,
    });
  } catch (error) {
    console.error('Error handling offer:', error);
    return jsonError(
      error instanceof Error ? error.message : 'Unknown error',
      500
    );
  }
}

/**
 * Handle viewer's offer to pull tracks from robot
 * POST /api/sessions/:robotId/pull
 */
export async function handlePull(
  robotId: string,
  request: Request,
  env: Env
): Promise<Response> {
  try {
    const body = await request.json() as { offer?: RTCSessionDescriptionInit };
    const { offer } = body;

    // Get session info
    if (!env.ROBOT_REGISTRY) {
      return jsonError('Robot registry not configured', 500);
    }

    const sessionData = await env.ROBOT_REGISTRY.get(`session:${robotId}`);
    if (!sessionData) {
      return jsonError('Session not found', 404);
    }

    const sessionInfo = JSON.parse(sessionData) as SFUSessionInfo;

    // Validate Cloudflare Calls credentials
    if (!env.CLOUDFLARE_CALLS_APP_ID || !env.CLOUDFLARE_CALLS_API_TOKEN) {
      return jsonError('Cloudflare Calls not configured', 500);
    }

    console.log('Processing viewer pull request for session:', sessionInfo.sessionId);

    // Create a new session for the viewer
    const viewerSessionResponse = await fetch(
      `${CALLS_API_BASE}/apps/${env.CLOUDFLARE_CALLS_APP_ID}/sessions/new`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.CLOUDFLARE_CALLS_API_TOKEN}`,
        },
      }
    );

    if (!viewerSessionResponse.ok) {
      const errorText = await viewerSessionResponse.text();
      console.error('Failed to create viewer session:', errorText);
      return jsonError(`Failed to create viewer session: ${errorText}`, viewerSessionResponse.status);
    }

    const viewerSessionData = await viewerSessionResponse.json() as {
      sessionId: string;
    };

    console.log('Created viewer session:', viewerSessionData.sessionId);

    // Fetch authoritative session details from Cloudflare to get active tracks
    let activeTracks: Array<{ trackName: string; mid: string; status: string; sessionId?: string }> = [];
    try {
      const sessionDetailsResponse = await fetch(
        `${CALLS_API_BASE}/apps/${env.CLOUDFLARE_CALLS_APP_ID}/sessions/${sessionInfo.sessionId}`,
        {
          headers: {
            'Authorization': `Bearer ${env.CLOUDFLARE_CALLS_API_TOKEN}`,
          },
        }
      );
      
      if (sessionDetailsResponse.ok) {
        const sessionDetails = await sessionDetailsResponse.json() as { tracks?: Array<any> };
        // Filter for active local tracks in the robot session
        activeTracks = (sessionDetails.tracks || []).filter((t: any) => 
          t.status === 'active' && t.location === 'local'
        );
        console.log('Active tracks in robot session:', JSON.stringify(activeTracks));
      } else {
        console.warn('Failed to fetch robot session details');
      }
    } catch (e) {
      console.error('Error fetching session details:', e);
    }

    // If we have an offer (Client-Side Offer)
    if (offer && offer.sdp) {
      // Parse SDP to extract mid values from viewer's offer
      const sdpLines = offer.sdp.split(/\r?\n/);
      const mids: string[] = [];
      for (const line of sdpLines) {
        if (line.startsWith('a=mid:')) {
          const mid = line.substring(6).trim();
          mids.push(mid);
        }
      }

      console.log('Extracted mids from viewer offer:', mids);

      // Build tracks array - viewer wants to receive (pull) remote tracks from robot's session
      const tracks = mids.slice(0, activeTracks.length).map((mid, index) => ({
        location: 'remote',
        sessionId: activeTracks[index].sessionId || sessionInfo.sessionId,
        trackName: activeTracks[index].trackName,
        mid: mid,
      }));

      console.log('Pulling tracks from robot session (Client Offer):', JSON.stringify(tracks));

      const requestBody = {
        sessionDescription: {
          type: offer.type,
          sdp: offer.sdp,
        },
        tracks: tracks.length > 0 ? tracks : undefined
      };

      // Send offer to Cloudflare Calls SFU
      const pullResponse = await fetch(
        `${CALLS_API_BASE}/apps/${env.CLOUDFLARE_CALLS_APP_ID}/sessions/${viewerSessionData.sessionId}/tracks/new`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${env.CLOUDFLARE_CALLS_API_TOKEN}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        }
      );

      if (!pullResponse.ok) {
        const errorText = await pullResponse.text();
        console.error('Cloudflare Calls pull tracks API error:', errorText);
        return jsonError(`Failed to pull tracks: ${errorText}`, pullResponse.status);
      }

      const pullData = await pullResponse.json() as {
        sessionDescription?: RTCSessionDescriptionInit;
        tracks?: unknown[];
      };

      return jsonResponse({
        success: true,
        answer: pullData.sessionDescription,
        tracks: pullData.tracks,
        sessionId: viewerSessionData.sessionId // Return viewer session ID
      });

    } else {
      // No offer provided (Server-Side Offer)
      // We ask Cloudflare to generate an offer for the tracks we want
      
      const tracks = activeTracks.map((track) => ({
        location: 'remote',
        sessionId: track.sessionId || sessionInfo.sessionId,
        trackName: track.trackName,
        // No 'mid' needed here, Cloudflare will assign one
      }));

      console.log('Pulling tracks from robot session (Server Offer):', JSON.stringify(tracks));

      const requestBody = {
        tracks: tracks
      };

      // Send request to Cloudflare Calls SFU
      const pullResponse = await fetch(
        `${CALLS_API_BASE}/apps/${env.CLOUDFLARE_CALLS_APP_ID}/sessions/${viewerSessionData.sessionId}/tracks/new`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${env.CLOUDFLARE_CALLS_API_TOKEN}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        }
      );

      if (!pullResponse.ok) {
        const errorText = await pullResponse.text();
        console.error('Cloudflare Calls pull tracks API error:', errorText);
        return jsonError(`Failed to pull tracks: ${errorText}`, pullResponse.status);
      }

      const pullData = await pullResponse.json() as {
        sessionDescription?: RTCSessionDescriptionInit;
        tracks?: unknown[];
      };

      // This is an OFFER from Cloudflare
      return jsonResponse({
        success: true,
        offer: pullData.sessionDescription,
        tracks: pullData.tracks,
        sessionId: viewerSessionData.sessionId // Return viewer session ID
      });
    }
  } catch (error) {
    console.error('Error handling pull:', error);
    return jsonError(
      error instanceof Error ? error.message : 'Unknown error',
      500
    );
  }
}

/**
 * Handle viewer's answer to robot's offer (or server offer)
 * POST /api/sessions/:robotId/answer
 */
export async function handleAnswer(
  robotId: string,
  request: Request,
  env: Env
): Promise<Response> {
  try {
    const body = await request.json() as { answer: RTCSessionDescriptionInit; sessionId?: string };
    const { answer, sessionId } = body;

    if (!answer || !answer.sdp) {
      return jsonError('Missing or invalid answer', 400);
    }

    // If sessionId is provided, it's the viewer's session ID (Server-Side Offer flow)
    if (sessionId) {
      // Validate Cloudflare Calls credentials
      if (!env.CLOUDFLARE_CALLS_APP_ID || !env.CLOUDFLARE_CALLS_API_TOKEN) {
        return jsonError('Cloudflare Calls not configured', 500);
      }

      console.log('Processing viewer answer for viewer session:', sessionId);

      const requestBody = {
        sessionDescription: {
          type: answer.type,
          sdp: answer.sdp,
        }
      };

      // Send answer to Cloudflare Calls SFU (renegotiate)
      const renegResponse = await fetch(
        `${CALLS_API_BASE}/apps/${env.CLOUDFLARE_CALLS_APP_ID}/sessions/${sessionId}/renegotiate`,
        {
          method: 'PUT',
          headers: {
            'Authorization': `Bearer ${env.CLOUDFLARE_CALLS_API_TOKEN}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(requestBody),
        }
      );

      if (!renegResponse.ok) {
        const errorText = await renegResponse.text();
        console.error('Cloudflare Calls renegotiate API error:', errorText);
        return jsonError(`Failed to process answer: ${errorText}`, renegResponse.status);
      }

      const renegData = await renegResponse.json() as {
        sessionDescription?: RTCSessionDescriptionInit;
        tracks?: unknown[];
      };

      return jsonResponse({
        success: true,
        message: 'Viewer connected to session',
        tracks: renegData.tracks,
      });

    } else {
      // Legacy flow (Client-Side Offer, but answer endpoint used differently?)
      // This block was previously assuming we are adding tracks to an existing session via answer?
      // But handlePull handles the initial connection.
      // Let's keep the old logic just in case, but it seems unused by the new flow.
      
      // Get session info
      if (!env.ROBOT_REGISTRY) {
        return jsonError('Robot registry not configured', 500);
      }

      const sessionData = await env.ROBOT_REGISTRY.get(`session:${robotId}`);
      if (!sessionData) {
        return jsonError('Session not found', 404);
      }
      const sessionInfo = JSON.parse(sessionData) as SFUSessionInfo;
      
      // ... (rest of old logic if needed, but likely we just need the above block)
      return jsonError('Session ID required for answer', 400);
    }
  } catch (error) {
    console.error('Error handling answer:', error);
    return jsonError(
      error instanceof Error ? error.message : 'Unknown error',
      500
    );
  }
}

/**
 * Get answer for a session (for viewers) - DEPRECATED
 * Use handleAnswer instead (POST /api/sessions/:robotId/answer)
 * GET /api/sessions/:robotId/answer
 */
export async function getAnswer(
  robotId: string,
  env: Env
): Promise<Response> {
  try {
    if (!env.ROBOT_REGISTRY) {
      return jsonError('Robot registry not configured', 500);
    }

    const sessionData = await env.ROBOT_REGISTRY.get(`session:${robotId}`);
    if (!sessionData) {
      return jsonError('Session not found', 404);
    }

    const sessionInfo = JSON.parse(sessionData) as SFUSessionInfo & { tracks?: unknown[] };

    // Validate Cloudflare Calls credentials
    if (!env.CLOUDFLARE_CALLS_APP_ID || !env.CLOUDFLARE_CALLS_API_TOKEN) {
      return jsonError('Cloudflare Calls not configured', 500);
    }

    // For viewers, we need to create a new peer connection to the same session
    // This will allow them to receive the tracks
    const pullResponse = await fetch(
      `${CALLS_API_BASE}/apps/${env.CLOUDFLARE_CALLS_APP_ID}/sessions/${sessionInfo.sessionId}/tracks/new`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.CLOUDFLARE_CALLS_API_TOKEN}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          tracks: [
            {
              location: 'remote',
              trackName: `${robotId}_video`,
            }
          ]
        }),
      }
    );

    if (!pullResponse.ok) {
      const errorText = await pullResponse.text();
      console.error('Cloudflare Calls pull tracks error:', errorText);
      return jsonError(`Failed to get tracks: ${errorText}`, pullResponse.status);
    }

    const pullData = await pullResponse.json() as {
      sessionDescription?: RTCSessionDescriptionInit;
      tracks?: unknown[];
    };

    if (!pullData.sessionDescription) {
      return jsonError('No session description available', 500);
    }

    return jsonResponse({
      success: true,
      answer: pullData.sessionDescription,
      tracks: pullData.tracks,
    });
  } catch (error) {
    console.error('Error getting answer:', error);
    return jsonError(
      error instanceof Error ? error.message : 'Unknown error',
      500
    );
  }
}

/**
 * Add ICE candidate
 * POST /api/sessions/:robotId/ice-candidate
 */
export async function addIceCandidate(
  robotId: string,
  request: Request,
  env: Env
): Promise<Response> {
  try {
    const body = await request.json() as { candidate: RTCIceCandidateInit };
    const { candidate } = body;

    if (!candidate) {
      return jsonError('Missing candidate', 400);
    }

    // Get session info
    if (!env.ROBOT_REGISTRY) {
      return jsonError('Robot registry not configured', 500);
    }

    const sessionData = await env.ROBOT_REGISTRY.get(`session:${robotId}`);
    if (!sessionData) {
      return jsonError('Session not found', 404);
    }

    const sessionInfo = JSON.parse(sessionData) as SFUSessionInfo;

    // Store ICE candidate in KV (with a separate key)
    const candidateKey = `ice_candidate:${robotId}:${Date.now()}`;
    await env.ROBOT_REGISTRY.put(
      candidateKey,
      JSON.stringify(candidate),
      { expirationTtl: 300 } // 5 minutes TTL
    );

    // Note: Cloudflare Calls handles ICE candidates automatically via STUN/TURN
    // This endpoint is mainly for compatibility and debugging

    return jsonResponse({
      success: true,
      message: 'ICE candidate stored',
    });
  } catch (error) {
    console.error('Error adding ICE candidate:', error);
    return jsonError(
      error instanceof Error ? error.message : 'Unknown error',
      500
    );
  }
}

// ============================================================================
// Utility Functions
// ============================================================================

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
    },
  });
}

function jsonError(message: string, status = 500): Response {
  return jsonResponse({ success: false, error: message }, status);
}
