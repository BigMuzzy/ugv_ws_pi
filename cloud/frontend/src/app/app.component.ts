import { Component, OnInit, ElementRef, ViewChild, AfterViewInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import nipplejs from 'nipplejs';

interface RobotInfo {
  robotId: string;
  name: string;
  status: 'online' | 'offline';
  batteryLevel?: number;
  lastSeen?: string;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="header">
      <h1>Fleet Management Console</h1>
    </div>

    <div class="container">
      <div class="card">
        <h2>Fleet Dashboard</h2>
        <p style="color: #666; margin-top: 0.5rem;">
          Minimal Angular implementation for testing
        </p>
      </div>

      <div class="card">
        <h3>Workers API Status</h3>
        <div *ngIf="apiStatus; else loading">
          <div class="robot-info">
            <div><strong>Status:</strong> <span [class]="'status ' + (apiStatus.status === 'ok' ? 'online' : 'offline')">{{apiStatus.status}}</span></div>
            <div><strong>Environment:</strong> {{apiStatus.environment}}</div>
            <div><strong>Timestamp:</strong> {{apiStatus.timestamp}}</div>
          </div>
        </div>
        <ng-template #loading>
          <p style="color: #666;">Loading API status...</p>
        </ng-template>
      </div>

      <div class="card">
        <h3>Connected Robots</h3>
        <div class="robot-grid">
          <div class="robot-card" *ngFor="let robot of robots">
            <h3>{{robot.name}}</h3>
            <div class="robot-info">
              <div><strong>ID:</strong> {{robot.robotId}}</div>
              <div><strong>Status:</strong> <span [class]="'status ' + robot.status">{{robot.status}}</span></div>
              <div *ngIf="robot.batteryLevel"><strong>Battery:</strong> {{robot.batteryLevel}}%</div>
              <div *ngIf="robot.lastSeen"><strong>Last Seen:</strong> {{formatDate(robot.lastSeen)}}</div>
            </div>
            <button class="btn btn-primary" (click)="viewRobot(robot.robotId)">View Details</button>
          </div>
        </div>
        <div class="placeholder" *ngIf="robots.length === 0">
          <p>No robots connected</p>
          <p style="font-size: 0.875rem; color: #999; margin-top: 0.5rem;">
            Robots will appear here when they connect to the fleet
          </p>
        </div>
      </div>

      <div class="card">
        <h3>Phase Progress</h3>
        <div class="robot-info">
          <div>✅ Phase 0: Foundation & Setup - Complete</div>
          <div>✅ Phase 1: Cloudflare Calls Integration - Robot Connected!</div>
          <div>⏸️ Phase 2: Rosbridge Proxy - Pending</div>
          <div>⏸️ Phase 3: Fleet Agent - Pending</div>
          <div>⏸️ Phase 4: Full UI Implementation - Pending</div>
        </div>
      </div>

      <div class="card" *ngIf="!viewingRobot">
        <h3>Quick Test</h3>
        <button class="btn btn-primary" (click)="connectToRobot('robot_01')">
          Connect to robot_01
        </button>
      </div>

      <div class="card" *ngIf="viewingRobot">
        <h3>Robot Video Stream: {{viewingRobot}}</h3>
        <video #videoElement autoplay playsinline style="width: 100%; max-width: 640px; background: #000;"></video>
        <div style="margin-top: 1rem;">
          <button class="btn btn-primary" (click)="disconnect()" style="margin-right: 0.5rem;">Disconnect</button>
          <span *ngIf="connectionState">Connection: {{connectionState}}</span>
        </div>
                <div class="joystick-container" style="margin-top: 1rem; display: flex; justify-content: center;">
           <div #joystickContainer style="width: 150px; height: 150px; position: relative;"></div>
        </div>
      </div>
    </div>
  `
})
export class AppComponent implements OnInit {
  @ViewChild('videoElement') videoElement?: ElementRef<HTMLVideoElement>;
  @ViewChild('joystickContainer') joystickContainer?: ElementRef<HTMLDivElement>;
  
  apiStatus: any = null;
  robots: RobotInfo[] = [];
  viewingRobot: string | null = null;
  
  connectionState: string = '';
  
  private pc: RTCPeerConnection | null = null;
  private dataChannel: RTCDataChannel | null = null;
  private joystickManager: any = null;

  constructor(private http: HttpClient) {}

  ngOnInit() {
    this.loadApiStatus();
    this.loadRobots();
  }

  loadApiStatus() {
    this.http.get('/api/health').subscribe({
      next: (data) => {
        this.apiStatus = data;
      },
      error: (err) => {
        console.error('Failed to load API status:', err);
        // Try direct Workers endpoint
        this.http.get('http://localhost:8787/health').subscribe({
          next: (data) => this.apiStatus = data,
          error: (err2) => console.error('Also failed direct connection:', err2)
        });
      }
    });
  }

  loadRobots() {
    // Mock data for now - will be replaced with real API in Phase 1
    this.robots = [];
  }

  viewRobot(robotId: string) {
    console.log('View robot:', robotId);
    alert(`Robot detail view will be implemented in Phase 4.\nRobot ID: ${robotId}`);
  }

  formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleString();
  }

  async connectToRobot(robotId: string) {
    this.viewingRobot = robotId;
    this.connectionState = 'Connecting...';
    
    // Initialize joystick after view update
    this.initJoystick();

    try {
      // Get session info
      const response = await fetch(`https://fleet-workers.mssemyonov.workers.dev/api/sessions/${robotId}`);
      const data = await response.json();
      
      if (!data.success) {
        alert('Robot session not found. Make sure the robot is running.');
        this.viewingRobot = null;
        return;
      }

      const session = data.session;

      // Create peer connection
      this.pc = new RTCPeerConnection({
        iceServers: session.iceServers
      });

      // Handle connection state
      this.pc.onconnectionstatechange = () => {
        console.log('Connection state:', this.pc!.connectionState);
        this.connectionState = this.pc!.connectionState;
      };

      // Handle ICE connection state
      this.pc.oniceconnectionstatechange = () => {
        console.log('ICE connection state:', this.pc!.iceConnectionState);
      };

      // Handle incoming video track
      this.pc.ontrack = (event) => {
        console.log('Received track:', event.track.kind);
        if (event.track.kind === 'video' && this.videoElement) {
          const stream = new MediaStream([event.track]);
          this.videoElement.nativeElement.srcObject = stream;
          console.log('Video stream attached to element');
        }
      };

      // Create DataChannel explicitly (negotiated: true, id: 1) to match Robot
      console.log("Creating 'commands' DataChannel (negotiated: true, id: 1)");
      this.dataChannel = this.pc.createDataChannel('commands', { negotiated: true, id: 1 });
      this.dataChannel.onopen = () => console.log('Data channel opened');
      this.dataChannel.onmessage = (msg) => console.log('Received message:', msg.data);
      this.dataChannel.onerror = (err) => console.error('Data channel error:', err);

      // Add transceiver to receive video from robot
      this.pc.addTransceiver('video', { direction: 'recvonly' });

      // Use Server-Side Offer flow (more robust for Cloudflare Calls)
      console.log('Requesting offer from SFU to pull tracks');
      
      const pullResponse = await fetch(
        `https://fleet-workers.mssemyonov.workers.dev/api/sessions/${robotId}/pull`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}) // Empty body = request server offer
        }
      );

      const pullData = await pullResponse.json();
      if (!pullData.success) {
        alert('Failed to connect: ' + pullData.error);
        this.disconnect();
        return;
      }

      // Set SFU's offer as remote description
      console.log('Setting remote description (SFU offer)');
      await this.pc.setRemoteDescription(new RTCSessionDescription(pullData.offer));
      
      // Create answer
      console.log('Creating answer');
      const answer = await this.pc.createAnswer();
      await this.pc.setLocalDescription(answer);

      // Wait for ICE gathering
      await new Promise<void>((resolve) => {
        if (this.pc!.iceGatheringState === 'complete') {
          resolve();
        } else {
          const checkState = () => {
            if (this.pc!.iceGatheringState === 'complete') {
              this.pc!.removeEventListener('icegatheringstatechange', checkState);
              resolve();
            }
          };
          this.pc!.addEventListener('icegatheringstatechange', checkState);
          setTimeout(() => resolve(), 3000); // Timeout after 3s
        }
      });

      // Send answer to SFU
      console.log('Sending answer to SFU');
      const answerResponse = await fetch(
        `https://fleet-workers.mssemyonov.workers.dev/api/sessions/${robotId}/answer`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            answer: {
              type: this.pc.localDescription!.type,
              sdp: this.pc.localDescription!.sdp
            },
            sessionId: pullData.sessionId // Required for renegotiation
          })
        }
      );

      const answerData = await answerResponse.json();
      if (!answerData.success) {
        console.error('Failed to send answer:', answerData.error);
        // Note: Connection might still work if ICE completes
      }
      
      console.log('WebRTC negotiation complete');

    } catch (error) {
      console.error('Error connecting:', error);
      alert('Connection error: ' + error);
      this.disconnect();
    }
  }

  disconnect() {
    if (this.joystickManager) {
      this.joystickManager.destroy();
      this.joystickManager = null;
    }
    if (this.dataChannel) {
      this.dataChannel.close();
      this.dataChannel = null;
    }
    if (this.pc) {
      this.pc.close();
      this.pc = null;
    }
    if (this.videoElement) {
      this.videoElement.nativeElement.srcObject = null;
    }
    this.viewingRobot = null;
    this.connectionState = '';
  }

  initJoystick() {
    // Wait a tick for the container to be rendered
    setTimeout(() => {
      if (!this.joystickContainer) return;
      
      this.joystickManager = nipplejs.create({
        zone: this.joystickContainer.nativeElement,
        mode: 'static',
        position: { left: '50%', top: '50%' },
        color: 'blue',
        size: 150
      });

      this.joystickManager.on('move', (evt: any, data: any) => {
        this.onJoystickMove(data);
      });

      this.joystickManager.on('end', () => {
        this.onJoystickEnd();
      });
    }, 100);
  }

  onJoystickMove(data: any) {
    if (!this.dataChannel || this.dataChannel.readyState !== 'open') {
      console.warn('Joystick moved but DataChannel not open', this.dataChannel?.readyState);
      return;
    }

    // Convert joystick data to linear/angular velocity
    // nipplejs returns vector { x, y } where x, y are between -1 and 1 (roughly)
    // We need to map this to linear (forward/back) and angular (left/right)
    
    // Forward/Back is Y axis (inverted in nipplejs usually, up is positive)
    // Left/Right is X axis
    
    const linear = data.vector.y; 
    const angular = -data.vector.x; // Invert X for correct rotation direction

    const command = {
      type: 'command',
      linear: linear,
      angular: angular
    };

    console.log('Sending joystick command:', command);
    this.dataChannel.send(JSON.stringify(command));
  }

  onJoystickEnd() {
    if (!this.dataChannel || this.dataChannel.readyState !== 'open') return;

    // Stop the robot when joystick is released
    const command = {
      type: 'command',
      linear: 0,
      angular: 0
    };

    this.dataChannel.send(JSON.stringify(command));
  }
}
