import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';

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
          <div>🔄 Phase 1: Cloudflare Calls Integration - Ready to start</div>
          <div>⏸️ Phase 2: Rosbridge Proxy - Pending</div>
          <div>⏸️ Phase 3: Fleet Agent - Pending</div>
          <div>⏸️ Phase 4: Full UI Implementation - Pending</div>
        </div>
      </div>
    </div>
  `
})
export class AppComponent implements OnInit {
  apiStatus: any = null;
  robots: RobotInfo[] = [];

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
}
