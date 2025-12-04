/**
 * WebRTC Configuration
 * 
 * This file contains ICE server configurations for WebRTC connections.
 * Configurations are fetched dynamically from the backend to ensure
 * secure credential management.
 */

/**
 * Get the WebRTC configuration for peer connection
 * @param {string} backendUrl - The backend URL to fetch credentials from
 * @returns {Promise<RTCConfiguration>} WebRTC peer connection configuration
 */
async function getWebRTCConfig(backendUrl) {
    const iceServers = await fetchICEServersFromBackend(backendUrl);
    
    return {
        iceServers: iceServers,
        iceCandidatePoolSize: 10,  // Gather candidates more aggressively
        iceTransportPolicy: 'all'  // Try all candidates including relay
    };
}

/**
 * Fetch ICE servers from backend
 * @param {string} backendUrl - The backend URL
 * @returns {Promise<RTCIceServer[]>} Array of ICE server configurations
 */
async function fetchICEServersFromBackend(backendUrl) {
    try {
        const response = await fetch(`${backendUrl}/ice-servers`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            console.warn('Failed to fetch ICE servers from backend, using fallback');
            return getFallbackConfig();
        }

        const data = await response.json();
        
        // Backend should return: { iceServers: [...] }
        if (data.iceServers && Array.isArray(data.iceServers)) {
            console.log('Using ICE servers from backend');
            return data.iceServers;
        } else {
            console.warn('Invalid ICE server response format, using fallback');
            return getFallbackConfig();
        }
    } catch (error) {
        console.error('Error fetching ICE servers:', error);
        console.log('Using fallback configuration');
        return getFallbackConfig();
    }
}

/**
 * Fallback configuration if backend is unavailable
 * Uses public STUN servers (no TURN support)
 */
function getFallbackConfig() {
    return [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' }
    ];
}

