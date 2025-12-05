/**
 * Cloudflare SFU Client for Frontend
 * 
 * Handles WebRTC connection to Cloudflare Calls SFU to:
 * - Receive video stream from robot
 * - Send teleop commands via DataChannel
 * - Monitor connection quality and latency
 */

import type { SFUSessionInfo, RTCIceServer } from '../../../shared/types';

export interface SFUClientConfig {
  workersEndpoint: string;
  robotId: string;
  onVideoTrack?: (track: MediaStreamTrack) => void;
  onConnectionStateChange?: (state: RTCPeerConnectionState) => void;
  onDataChannelMessage?: (data: any) => void;
  logger?: {
    info: (msg: string) => void;
    error: (msg: string) => void;
    warn: (msg: string) => void;
  };
}

export class SFUClient {
  private pc: RTCPeerConnection | null = null;
  private dataChannel: RTCDataChannel | null = null;
  private config: SFUClientConfig;
  private sessionInfo: SFUSessionInfo | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectTimeout: number | null = null;

  // Latency tracking
  private lastPingTime = 0;
  private latencyMs = 0;
  private pingInterval: number | null = null;

  constructor(config: SFUClientConfig) {
    this.config = config;
  }

  /**
   * Connect to SFU session for the robot
   */
  async connect(): Promise<boolean> {
    try {
      // Step 1: Get session info from Workers API
      this.sessionInfo = await this.fetchSessionInfo();
      if (!this.sessionInfo) {
        this.log('error', 'Failed to fetch session info');
        return false;
      }

      this.log('info', `Joining SFU session: ${this.sessionInfo.sessionId}`);

      // Step 2: Create peer connection with ICE servers
      this.createPeerConnection(this.sessionInfo.iceServers);

      // Step 3: Create offer
      const offer = await this.pc!.createOffer();
      await this.pc!.setLocalDescription(offer);

      this.log('info', 'Created offer, waiting for ICE gathering...');

      // Wait for ICE gathering to complete
      await this.waitForIceGathering();

      // Step 5: Send offer to SFU (via Workers) and get answer
      const answer = await this.sendOfferAndGetAnswer();
      if (!answer) {
        this.log('error', 'Failed to get answer from SFU');
        return false;
      }

      // Step 6: Set remote description with answer
      await this.pc!.setRemoteDescription(new RTCSessionDescription(answer));
      this.log('info', 'Set remote description, connection establishing...');

      // Step 6: Start latency monitoring
      this.startLatencyMonitoring();

      this.reconnectAttempts = 0;
      return true;

    } catch (error) {
      this.log('error', `Error connecting to SFU: ${error}`);
      return false;
    }
  }

  /**
   * Fetch session info from Workers API
   */
  private async fetchSessionInfo(): Promise<SFUSessionInfo | null> {
    try {
      const url = `${this.config.workersEndpoint}/api/sessions/${this.config.robotId}`;
      const response = await fetch(url);

      if (!response.ok) {
        if (response.status === 404) {
          this.log('error', 'Session not found for robot');
        } else {
          this.log('error', `Failed to fetch session: ${response.status}`);
        }
        return null;
      }

      const data = await response.json();
      return data.session;

    } catch (error) {
      this.log('error', `Error fetching session info: ${error}`);
      return null;
    }
  }

  /**
   * Create RTCPeerConnection with ICE servers
   */
  private createPeerConnection(iceServers: RTCIceServer[]): void {
    const config: RTCConfiguration = {
      iceServers: iceServers.map(server => ({
        urls: Array.isArray(server.urls) ? server.urls : [server.urls],
        username: server.username,
        credential: server.credential
      }))
    };

    this.pc = new RTCPeerConnection(config);

    // Handle connection state changes
    this.pc.onconnectionstatechange = () => {
      const state = this.pc!.connectionState;
      this.log('info', `Connection state: ${state}`);

      if (this.config.onConnectionStateChange) {
        this.config.onConnectionStateChange(state);
      }

      if (state === 'failed' || state === 'disconnected') {
        this.handleConnectionFailure();
      }
    };

    // Handle ICE connection state
    this.pc.oniceconnectionstatechange = () => {
      this.log('info', `ICE connection state: ${this.pc!.iceConnectionState}`);
    };

    // Handle incoming tracks (video from robot)
    this.pc.ontrack = (event) => {
      this.log('info', `Received ${event.track.kind} track`);
      
      if (event.track.kind === 'video' && this.config.onVideoTrack) {
        this.config.onVideoTrack(event.track);
      }
    };

    // Handle ICE candidates
    this.pc.onicecandidate = (event) => {
      if (event.candidate) {
        this.log('info', 'ICE candidate generated');
        // TODO: Send ICE candidate to SFU via Workers
      }
    };

    // Handle incoming data channel
    this.pc.ondatachannel = (event) => {
      this.log('info', `Received data channel: ${event.channel.label}`);
      this.dataChannel = event.channel;
      this.setupDataChannelHandlers();
    };
  }

  /**
   * Setup handlers for data channel
   */
  private setupDataChannelHandlers(): void {
    if (!this.dataChannel) return;

    this.dataChannel.onopen = () => {
      this.log('info', 'Data channel opened');
    };

    this.dataChannel.onclose = () => {
      this.log('info', 'Data channel closed');
    };

    this.dataChannel.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // Handle pong for latency measurement
        if (data.type === 'pong') {
          this.latencyMs = Date.now() - this.lastPingTime;
        }

        if (this.config.onDataChannelMessage) {
          this.config.onDataChannelMessage(data);
        }
      } catch (error) {
        this.log('error', `Error parsing data channel message: ${error}`);
      }
    };
  }

  /**
   * Send offer to Workers and get answer from SFU
   */
  private async sendOfferAndGetAnswer(): Promise<RTCSessionDescriptionInit | null> {
    if (!this.pc || !this.pc.localDescription) {
      this.log('error', 'No local description available');
      return null;
    }

    try {
      const url = `${this.config.workersEndpoint}/api/sessions/${this.config.robotId}/pull`;
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          offer: {
            type: this.pc.localDescription.type,
            sdp: this.pc.localDescription.sdp
          }
        })
      });

      if (!response.ok) {
        const errorText = await response.text();
        this.log('error', `Failed to send offer: ${response.status} - ${errorText}`);
        return null;
      }

      const data = await response.json();
      return data.answer;

    } catch (error) {
      this.log('error', `Error sending offer: ${error}`);
      return null;
    }
  }

  /**
   * Wait for ICE gathering to complete
   */
  private async waitForIceGathering(): Promise<void> {
    if (!this.pc) return;

    if (this.pc.iceGatheringState === 'complete') {
      return;
    }

    return new Promise((resolve) => {
      const checkState = () => {
        if (this.pc!.iceGatheringState === 'complete') {
          this.pc!.removeEventListener('icegatheringstatechange', checkState);
          resolve();
        }
      };

      this.pc!.addEventListener('icegatheringstatechange', checkState);

      // Timeout after 5 seconds
      setTimeout(() => {
        if (this.pc) {
          this.pc.removeEventListener('icegatheringstatechange', checkState);
        }
        resolve();
      }, 5000);
    });
  }

  /**
   * Handle connection failure and attempt reconnection
   */
  private handleConnectionFailure(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.log('error', 'Max reconnection attempts reached');
      return;
    }

    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    this.reconnectAttempts++;

    this.log('info', `Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);

    this.reconnectTimeout = window.setTimeout(async () => {
      await this.disconnect();
      await this.connect();
    }, delay);
  }

  /**
   * Start latency monitoring via ping/pong
   */
  private startLatencyMonitoring(): void {
    this.pingInterval = window.setInterval(() => {
      if (this.dataChannel && this.dataChannel.readyState === 'open') {
        this.lastPingTime = Date.now();
        this.sendMessage({ type: 'ping', timestamp: this.lastPingTime });
      }
    }, 1000); // Ping every second
  }

  /**
   * Send velocity command to robot
   */
  sendCommand(linear: number, angular: number): void {
    this.sendMessage({
      type: 'command',
      linear,
      angular
    });
  }

  /**
   * Send emergency stop command
   */
  emergencyStop(): void {
    this.sendMessage({
      type: 'emergency_stop'
    });
  }

  /**
   * Send message through data channel
   */
  private sendMessage(data: any): void {
    if (!this.dataChannel || this.dataChannel.readyState !== 'open') {
      this.log('warn', 'Data channel not open, cannot send message');
      return;
    }

    try {
      this.dataChannel.send(JSON.stringify(data));
    } catch (error) {
      this.log('error', `Error sending message: ${error}`);
    }
  }

  /**
   * Get current latency in milliseconds
   */
  getLatency(): number {
    return this.latencyMs;
  }

  /**
   * Get connection state
   */
  getConnectionState(): RTCPeerConnectionState | null {
    return this.pc ? this.pc.connectionState : null;
  }

  /**
   * Disconnect from SFU
   */
  async disconnect(): Promise<void> {
    // Clear timers
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.pingInterval) {
      clearInterval(this.pingInterval);
      this.pingInterval = null;
    }

    // Close data channel
    if (this.dataChannel) {
      this.dataChannel.close();
      this.dataChannel = null;
    }

    // Close peer connection
    if (this.pc) {
      this.pc.close();
      this.pc = null;
    }

    this.log('info', 'Disconnected from SFU');
  }

  /**
   * Log message
   */
  private log(level: 'info' | 'error' | 'warn', message: string): void {
    if (this.config.logger && this.config.logger[level]) {
      this.config.logger[level](message);
    } else {
      console[level](`[SFUClient] ${message}`);
    }
  }
}

/**
 * React hook for SFU connection
 */
export function useSFUClient(
  workersEndpoint: string,
  robotId: string,
  options?: {
    autoConnect?: boolean;
    onVideoTrack?: (track: MediaStreamTrack) => void;
    onConnectionStateChange?: (state: RTCPeerConnectionState) => void;
  }
) {
  // This is a placeholder for the React hook implementation
  // Will be properly implemented when integrating with the Angular frontend
  
  return {
    connect: async () => false,
    disconnect: async () => {},
    sendCommand: (linear: number, angular: number) => {},
    emergencyStop: () => {},
    getLatency: () => 0,
    isConnected: () => false
  };
}
