/**
 * ROSBridge Client for Fleet Operator Console
 * 
 * This module provides a roslibjs-like interface that works through
 * the Fleet DO operator WebSocket instead of connecting directly to rosbridge.
 * 
 * Architecture:
 *   Operator Browser <-> Fleet DO (Cloudflare) <-> Robot <-> rosbridge_server
 */

class FleetROSBridge {
    constructor(options = {}) {
        this.workerUrl = options.workerUrl || 'wss://fleet-worker.mssemyonov.workers.dev';
        this.robotId = options.robotId || null;
        this.ws = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = options.maxReconnectAttempts || 5;
        this.reconnectDelay = options.reconnectDelay || 2000;
        
        // Callbacks
        this.onConnection = options.onConnection || (() => {});
        this.onClose = options.onClose || (() => {});
        this.onError = options.onError || (() => {});
        
        // Message handlers by operation ID
        this._messageHandlers = new Map();
        this._topicSubscribers = new Map();  // topic -> Set of callbacks
        this._topicSubscriptionIds = new Map();  // topic -> subscription id
        this._serviceCallbacks = new Map();  // service call id -> callback
        this._actionGoals = new Map();       // goal id -> { feedback, result }
        
        // Auto-increment ID for operations
        this._nextId = 1;
    }
    
    /**
     * Connect to Fleet DO operator WebSocket
     */
    connect(robotId = null) {
        if (robotId) this.robotId = robotId;
        
        if (!this.robotId) {
            console.error('[ROSBridge] No robotId specified');
            this.onError(new Error('No robotId specified'));
            return;
        }
        
        const wsUrl = `${this.workerUrl.replace('https://', 'wss://').replace('http://', 'ws://')}/ws/operator?robotId=${this.robotId}`;
        console.log(`[ROSBridge] Connecting to ${wsUrl}`);
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('[ROSBridge] WebSocket connected');
                this.connected = true;
                this.reconnectAttempts = 0;
                this.onConnection();
            };
            
            this.ws.onclose = (event) => {
                console.log(`[ROSBridge] WebSocket closed: ${event.code} ${event.reason}`);
                this.connected = false;
                this.onClose(event);
                
                // Attempt reconnect if not a clean close
                if (event.code !== 1000 && this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.reconnectAttempts++;
                    console.log(`[ROSBridge] Reconnecting (attempt ${this.reconnectAttempts})...`);
                    setTimeout(() => this.connect(), this.reconnectDelay);
                }
            };
            
            this.ws.onerror = (error) => {
                console.error('[ROSBridge] WebSocket error:', error);
                this.onError(error);
            };
            
            this.ws.onmessage = (event) => {
                this._handleMessage(event.data);
            };
            
        } catch (e) {
            console.error('[ROSBridge] Failed to connect:', e);
            this.onError(e);
        }
    }
    
    /**
     * Disconnect from Fleet DO
     */
    disconnect() {
        if (this.ws) {
            this.ws.close(1000, 'Client disconnect');
            this.ws = null;
        }
        this.connected = false;
        this._topicSubscribers.clear();
        this._topicSubscriptionIds.clear();
        this._serviceCallbacks.clear();
        this._actionGoals.clear();
    }
    
    /**
     * Handle incoming message from Fleet DO
     */
    _handleMessage(data) {
        try {
            const msg = JSON.parse(data);

            // Check if this is a wrapped Fleet DO message or direct rosbridge message
            if (msg.type === 'rosbridge') {
                // Wrapped format: {type: 'rosbridge', payload: {...}}
                const rosbridgeMsg = msg.payload;
                this._handleRosbridgeMessage(rosbridgeMsg);
            } else if (msg.type === 'connected') {
                console.log('[ROSBridge] Connection established:', msg.robotId);
            } else if (msg.type === 'robot_status') {
                console.log('[ROSBridge] Robot status:', msg.payload);
            } else if (msg.type === 'error') {
                console.error('[ROSBridge] Error from Fleet DO:', msg.payload);
            } else if (msg.op) {
                // Direct rosbridge protocol message (not wrapped)
                this._handleRosbridgeMessage(msg);
            } else {
                console.warn('[ROSBridge] Unknown message format:', msg);
            }
        } catch (e) {
            console.error('[ROSBridge] Failed to parse message:', e, data);
        }
    }
    
    /**
     * Handle rosbridge protocol message
     */
    _handleRosbridgeMessage(msg) {
        // Validate required 'op' field per ROSBridge protocol
        if (!msg.op || typeof msg.op !== 'string') {
            console.error('[ROSBridge] Invalid message - missing or invalid "op" field:', msg);
            return;
        }

        const op = msg.op;
        console.log('[ROSBridge] Received:', op, msg.topic || msg.service || msg.id);

        switch (op) {
            case 'publish':
                // Topic message received
                const topic = msg.topic;
                const subscribers = this._topicSubscribers.get(topic);
                if (subscribers) {
                    subscribers.forEach(callback => {
                        try {
                            callback(msg.msg);
                        } catch (e) {
                            console.error(`[ROSBridge] Subscriber callback error for ${topic}:`, e);
                        }
                    });
                }
                break;
                
            case 'service_response':
                // Service call response
                const serviceId = msg.id;
                const serviceCallback = this._serviceCallbacks.get(serviceId);
                if (serviceCallback) {
                    this._serviceCallbacks.delete(serviceId);
                    // Protocol: result is boolean success, values contains response data
                    const success = msg.result === true;
                    const response = msg.values || {};
                    serviceCallback(success, response);
                } else {
                    console.warn('[ROSBridge] Received service_response for unknown ID:', serviceId);
                }
                break;
                
            case 'action_feedback':
                // Action feedback
                const feedbackGoalId = msg.id;
                const feedbackGoal = this._actionGoals.get(feedbackGoalId);
                if (feedbackGoal && feedbackGoal.feedback) {
                    feedbackGoal.feedback(msg.values);
                }
                break;
                
            case 'action_result':
                // Action result
                const resultGoalId = msg.id;
                const resultGoal = this._actionGoals.get(resultGoalId);
                if (resultGoal && resultGoal.result) {
                    this._actionGoals.delete(resultGoalId);
                    resultGoal.result(msg.result, msg.values);
                }
                break;
                
            case 'status':
                // rosbridge status (connected topics, etc.)
                console.log('[ROSBridge] Status:', msg);
                break;
                
            default:
                console.log('[ROSBridge] Unknown op:', op, msg);
        }
    }
    
    /**
     * Send rosbridge message through Fleet DO
     */
    _send(rosbridgeMsg) {
        if (!this.connected || !this.ws) {
            console.error('[ROSBridge] Not connected');
            return false;
        }

        const fleetMsg = {
            type: 'rosbridge',
            payload: rosbridgeMsg
        };

        this.ws.send(JSON.stringify(fleetMsg));
        return true;
    }
    
    /**
     * Generate unique ID for operations
     */
    _generateId(prefix = 'op') {
        return `${prefix}_${this._nextId++}_${Date.now()}`;
    }
    
    // ========== Topic Operations ==========
    
    /**
     * Subscribe to a topic
     * @param {string} topic - Topic name (e.g., '/rosout', '/odom')
     * @param {string} messageType - Message type (e.g., 'std_msgs/String')
     * @param {function} callback - Called with message data
     * @param {object} options - Optional: throttle_rate, queue_length, fragment_size
     * @returns {object} Subscription handle with unsubscribe() method
     */
    subscribe(topic, messageType, callback, options = {}) {
        // Add to local subscribers
        if (!this._topicSubscribers.has(topic)) {
            this._topicSubscribers.set(topic, new Set());

            // Generate and store subscription ID for this topic
            const subscribeId = this._generateId('subscribe');
            this._topicSubscriptionIds.set(topic, subscribeId);

            // Send subscribe command to rosbridge
            const subscribeMsg = {
                op: 'subscribe',
                id: subscribeId,
                topic: topic,
                type: messageType,
                ...options
            };

            this._send(subscribeMsg);
            console.log(`[ROSBridge] Subscribed to ${topic} (${messageType})`);
        }

        this._topicSubscribers.get(topic).add(callback);

        // Return subscription handle
        return {
            topic,
            unsubscribe: () => {
                this.unsubscribe(topic, callback);
            }
        };
    }
    
    /**
     * Unsubscribe from a topic
     */
    unsubscribe(topic, callback = null) {
        const subscribers = this._topicSubscribers.get(topic);
        if (!subscribers) {
            console.warn(`[ROSBridge] Unsubscribe called for unknown topic: ${topic}`);
            return;
        }

        if (callback) {
            subscribers.delete(callback);
            // If no more subscribers, unsubscribe from rosbridge
            if (subscribers.size === 0) {
                this._topicSubscribers.delete(topic);

                // Use the stored subscription ID for unsubscribe
                const subscribeId = this._topicSubscriptionIds.get(topic);
                if (subscribeId) {
                    console.log(`[ROSBridge] Sending unsubscribe for ${topic} (id: ${subscribeId})`);
                    this._send({
                        op: 'unsubscribe',
                        id: subscribeId,
                        topic: topic
                    });
                    this._topicSubscriptionIds.delete(topic);
                } else {
                    console.warn(`[ROSBridge] No subscription ID found for ${topic}`);
                }
            }
        } else {
            // Unsubscribe all callbacks for this topic
            this._topicSubscribers.delete(topic);

            // Use the stored subscription ID for unsubscribe
            const subscribeId = this._topicSubscriptionIds.get(topic);
            if (subscribeId) {
                console.log(`[ROSBridge] Sending unsubscribe (all) for ${topic} (id: ${subscribeId})`);
                this._send({
                    op: 'unsubscribe',
                    id: subscribeId,
                    topic: topic
                });
                this._topicSubscriptionIds.delete(topic);
            } else {
                console.warn(`[ROSBridge] No subscription ID found for ${topic}`);
            }
        }
    }
    
    /**
     * Publish to a topic
     * @param {string} topic - Topic name
     * @param {string} messageType - Message type
     * @param {object} message - Message data
     */
    publish(topic, messageType, message) {
        // First, advertise the topic if not already done
        // rosbridge handles this automatically, but explicit is better
        this._send({
            op: 'advertise',
            id: this._generateId('advertise'),
            topic: topic,
            type: messageType
        });
        
        // Then publish
        this._send({
            op: 'publish',
            id: this._generateId('publish'),
            topic: topic,
            msg: message
        });
        
        console.log(`[ROSBridge] Published to ${topic}:`, message);
    }
    
    // ========== Service Operations ==========
    
    /**
     * Call a ROS service
     * @param {string} service - Service name (e.g., '/get_map')
     * @param {string} serviceType - Service type (e.g., 'nav_msgs/GetMap')
     * @param {object} request - Request data
     * @param {function} callback - Called with (success, response)
     */
    callService(service, serviceType, request, callback) {
        const callId = this._generateId('service');
        this._serviceCallbacks.set(callId, callback);
        
        this._send({
            op: 'call_service',
            id: callId,
            service: service,
            type: serviceType,
            args: request
        });
        
        console.log(`[ROSBridge] Calling service ${service}:`, request);
        
        // Timeout for service call
        setTimeout(() => {
            if (this._serviceCallbacks.has(callId)) {
                this._serviceCallbacks.delete(callId);
                callback(false, { error: 'Service call timeout' });
            }
        }, 10000);  // 10 second timeout
    }
    
    // ========== Action Operations ==========
    
    /**
     * Send action goal
     * @param {string} actionName - Action name (e.g., '/navigate_to_pose')
     * @param {string} actionType - Action type (e.g., 'nav2_msgs/NavigateToPose')
     * @param {object} goal - Goal data
     * @param {object} callbacks - { feedback: fn, result: fn }
     * @returns {object} Goal handle with cancel() method
     */
    sendActionGoal(actionName, actionType, goal, callbacks = {}) {
        const goalId = this._generateId('action');

        this._actionGoals.set(goalId, {
            feedback: callbacks.feedback,
            result: callbacks.result
        });

        const actionMsg = {
            op: 'send_action_goal',
            id: goalId,
            action: actionName,
            action_type: actionType,
            args: goal,
            feedback: true  // Enable feedback messages
        };

        console.log(`[ROSBridge] Sending action goal (id: ${goalId}):`, actionMsg);
        this._send(actionMsg);
        
        return {
            goalId,
            cancel: () => {
                this.cancelActionGoal(goalId, actionName);
            }
        };
    }
    
    /**
     * Cancel action goal
     */
    cancelActionGoal(goalId, actionName) {
        this._send({
            op: 'cancel_action_goal',
            id: goalId,
            action: actionName
        });
        
        this._actionGoals.delete(goalId);
        console.log(`[ROSBridge] Cancelled action goal ${goalId}`);
    }
    
    // ========== Utility Methods ==========
    
    /**
     * Get list of published topics
     */
    getTopics(callback) {
        // This requires rosbridge to support the 'get_topics' op
        // Some rosbridge implementations don't support this
        const callId = this._generateId('get_topics');
        this._serviceCallbacks.set(callId, (success, response) => {
            callback(response);
        });
        
        this._send({
            op: 'call_service',
            id: callId,
            service: '/rosapi/topics',
            type: 'rosapi/Topics'
        });
    }
    
    /**
     * Get list of services
     */
    getServices(callback) {
        const callId = this._generateId('get_services');
        this._serviceCallbacks.set(callId, (success, response) => {
            callback(response);
        });
        
        this._send({
            op: 'call_service',
            id: callId,
            service: '/rosapi/services',
            type: 'rosapi/Services'
        });
    }
    
    /**
     * Get list of nodes
     */
    getNodes(callback) {
        const callId = this._generateId('get_nodes');
        this._serviceCallbacks.set(callId, (success, response) => {
            callback(response);
        });
        
        this._send({
            op: 'call_service',
            id: callId,
            service: '/rosapi/nodes',
            type: 'rosapi/Nodes'
        });
    }
}

// ========== Convenience Classes ==========

/**
 * Topic class for easier subscription management
 */
class Topic {
    constructor(ros, options) {
        this.ros = ros;
        this.name = options.name;
        this.messageType = options.messageType;
        this.throttleRate = options.throttleRate || 0;
        this.queueLength = options.queueLength || 0;
        this._subscription = null;
    }
    
    subscribe(callback) {
        const options = {};
        if (this.throttleRate > 0) options.throttle_rate = this.throttleRate;
        if (this.queueLength > 0) options.queue_length = this.queueLength;
        
        this._subscription = this.ros.subscribe(
            this.name, 
            this.messageType, 
            callback,
            options
        );
    }
    
    unsubscribe() {
        if (this._subscription) {
            this._subscription.unsubscribe();
            this._subscription = null;
        }
    }
    
    publish(message) {
        this.ros.publish(this.name, this.messageType, message);
    }
}

/**
 * Service class for service calls
 */
class Service {
    constructor(ros, options) {
        this.ros = ros;
        this.name = options.name;
        this.serviceType = options.serviceType;
    }
    
    call(request, callback) {
        this.ros.callService(this.name, this.serviceType, request, callback);
    }
}

/**
 * ActionClient class for action management
 */
class ActionClient {
    constructor(ros, options) {
        this.ros = ros;
        this.actionName = options.actionName;
        this.actionType = options.actionType;
        this._goals = new Map();
    }
    
    sendGoal(goal, callbacks = {}) {
        const handle = this.ros.sendActionGoal(
            this.actionName,
            this.actionType,
            goal,
            callbacks
        );
        this._goals.set(handle.goalId, handle);
        return handle;
    }
    
    cancelAllGoals() {
        this._goals.forEach((handle, goalId) => {
            handle.cancel();
        });
        this._goals.clear();
    }
}

// Export for module usage (if using ES modules)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { FleetROSBridge, Topic, Service, ActionClient };
}
