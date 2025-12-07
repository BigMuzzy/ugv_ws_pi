const WebSocket = require('ws');
const https = require('https');

const WORKER_HOST = 'fleet-worker.mssemyonov.workers.dev';
const ROBOT_ID = 'test-robot-01';
const SFU_SESSION_ID = 'session-123';
const OPERATOR_SESSION_ID = 'op-session-456';

function makeRequest(method, path, body = null) {
    return new Promise((resolve, reject) => {
        const options = {
            hostname: WORKER_HOST,
            port: 443,
            path: path,
            method: method,
            headers: {
                'Content-Type': 'application/json'
            }
        };

        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                try {
                    resolve({ status: res.statusCode, body: data ? JSON.parse(data) : null });
                } catch (e) {
                    resolve({ status: res.statusCode, body: data });
                }
            });
        });

        req.on('error', (e) => reject(e));
        if (body) req.write(JSON.stringify(body));
        req.end();
    });
}

async function runTest() {
    console.log('Starting Phase 1 Verification...');

    // 1. Connect WebSocket
    console.log('1. Connecting WebSocket...');
    const ws = new WebSocket(`wss://${WORKER_HOST}/ws/robot`);

    await new Promise((resolve, reject) => {
        ws.on('open', resolve);
        ws.on('error', reject);
    });
    console.log('   WebSocket Connected.');

    // 2. Send Status
    console.log('2. Sending Status...');
    ws.send(JSON.stringify({
        type: 'status',
        robotId: ROBOT_ID,
        sfuSessionId: SFU_SESSION_ID
    }));
    
    // Wait a bit for KV update (eventual consistency)
    await new Promise(r => setTimeout(r, 2000));

    // 3. Verify Robot in List
    console.log('3. Verifying Robot List...');
    const listRes = await makeRequest('GET', '/robots');
    console.log('   GET /robots response:', listRes.status, JSON.stringify(listRes.body));
    
    const robotFound = listRes.body.find(r => r.id === ROBOT_ID);
    if (robotFound && robotFound.sfuSessionId === SFU_SESSION_ID) {
        console.log('   SUCCESS: Robot found in registry.');
    } else {
        console.error('   FAILURE: Robot not found or incorrect data.');
        process.exit(1);
    }

    // 4. Trigger Connect Signal
    console.log('4. Triggering Connect Signal...');
    
    // Listen for signal
    const signalPromise = new Promise((resolve) => {
        ws.on('message', (data) => {
            const msg = JSON.parse(data);
            console.log('   WS Received:', msg);
            if (msg.action === 'subscribe_cmd' && msg.sessionId === OPERATOR_SESSION_ID) {
                resolve(true);
            }
        });
    });

    const connectRes = await makeRequest('POST', '/connect', {
        robotId: ROBOT_ID,
        operatorSessionId: OPERATOR_SESSION_ID
    });
    console.log('   POST /connect response:', connectRes.status, JSON.stringify(connectRes.body));

    if (connectRes.status === 200 && connectRes.body.success) {
        console.log('   SUCCESS: Connect request accepted.');
    } else {
        console.error('   FAILURE: Connect request failed.');
        process.exit(1);
    }

    // Wait for signal
    console.log('   Waiting for signal on WebSocket...');
    const signalReceived = await Promise.race([
        signalPromise,
        new Promise(r => setTimeout(() => r(false), 5000))
    ]);

    if (signalReceived) {
        console.log('   SUCCESS: Signal received on WebSocket.');
    } else {
        console.error('   FAILURE: Signal NOT received.');
        process.exit(1);
    }

    ws.close();
    console.log('Phase 1 Verification COMPLETE.');
}

runTest().catch(console.error);
