/**
 * WebRTC Configuration
 * 
 * This file contains ICE server configurations for WebRTC connections.
 * You can easily switch between different STUN/TURN providers by
 * uncommenting the desired configuration.
 */

/**
 * Get the WebRTC configuration for peer connection
 * @returns {RTCConfiguration} WebRTC peer connection configuration
 */
function getWebRTCConfig() {
    return {
        iceServers: getICEServers(),
        iceCandidatePoolSize: 10,  // Gather candidates more aggressively
        iceTransportPolicy: 'all'  // Try all candidates including relay
    };
}

/**
 * Get ICE servers configuration
 * @returns {RTCIceServer[]} Array of ICE server configurations
 */
function getICEServers() {
    // Choose your preferred configuration by uncommenting one of the options below
    
    // Option 1: Metered.ca (Free tier with TURN support) - ACTIVE
    return getMeteredConfig();
    
    // Option 2: Google STUN only (No TURN support)
    // return getGoogleSTUNConfig();
    
    // Option 3: Custom TURN server
    // return getCustomTURNConfig();
    
    // Option 4: Multiple providers (Redundancy)
    // return getMultiProviderConfig();
}

/**
 * Metered.ca configuration (Free tier)
 * Provides both STUN and TURN servers with multiple transports
 * https://www.metered.ca/tools/openrelay/
 */
function getMeteredConfig() {
    return [
        // Google STUN servers (fallback)
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        
        // Metered.ca STUN server
        { urls: 'stun:stun.relay.metered.ca:80' },
        
        // Metered.ca TURN servers with multiple transports
        {
            urls: [
                'turn:global.relay.metered.ca:80',
                'turn:global.relay.metered.ca:80?transport=tcp',
                'turn:global.relay.metered.ca:443',
                'turns:global.relay.metered.ca:443?transport=tcp'
            ],
            username: 'bbded4f052d4c3c9e8e6342f',
            credential: 'UWI3yEJTIVm+nT0J'
        }
    ];
}

/**
 * Google STUN only configuration
 * Simple, reliable STUN servers but no TURN (relay) support
 * Works well for direct connections but may fail behind strict NATs
 */
function getGoogleSTUNConfig() {
    return [
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        { urls: 'stun:stun2.l.google.com:19302' },
        { urls: 'stun:stun3.l.google.com:19302' },
        { urls: 'stun:stun4.l.google.com:19302' }
    ];
}

/**
 * Custom TURN server configuration
 * Use this if you're hosting your own TURN server (coturn, etc.)
 */
function getCustomTURNConfig() {
    return [
        // Public STUN servers
        { urls: 'stun:stun.l.google.com:19302' },
        
        // Your custom TURN server
        {
            urls: [
                'turn:YOUR_SERVER_IP:3478',
                'turn:YOUR_SERVER_IP:3478?transport=tcp'
            ],
            username: 'your_username',
            credential: 'your_password'
        }
    ];
}

/**
 * Multi-provider configuration
 * Uses multiple providers for redundancy
 * Browser will try servers in order until connection succeeds
 */
function getMultiProviderConfig() {
    return [
        // Google STUN (always available)
        { urls: 'stun:stun.l.google.com:19302' },
        { urls: 'stun:stun1.l.google.com:19302' },
        
        // Metered.ca TURN
        { urls: 'stun:stun.relay.metered.ca:80' },
        {
            urls: [
                'turn:global.relay.metered.ca:80',
                'turn:global.relay.metered.ca:80?transport=tcp',
                'turn:global.relay.metered.ca:443',
                'turns:global.relay.metered.ca:443?transport=tcp'
            ],
            username: 'bbded4f052d4c3c9e8e6342f',
            credential: 'UWI3yEJTIVm+nT0J'
        },
        
        // Add more providers here as needed
    ];
}

