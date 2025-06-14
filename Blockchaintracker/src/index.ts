import Client, { CommitmentLevel, SubscribeRequest } from "@triton-one/yellowstone-grpc";
import * as bs58 from 'bs58';
import * as fs from 'fs';
import * as path from 'path';
import axios from 'axios';

// Account key activity tracking
const accountKeyActivity = new Map<string, number[]>(); // accountKey -> array of timestamps
const blacklistedAccountKeys = new Set<string>();
const BLACKLIST_FILE = path.join(__dirname, 'blacklisted_account_keys.json');

const MAX_TRANSACTIONS_PER_PERIOD = 40;
const TIME_WINDOW = 3600000; // 1 hour
const startupTime = Date.now();

// Concurrent processing configuration
const MAX_CONCURRENT_PROCESSING = 10;
const processingQueue: Array<() => Promise<void>> = [];
let activeProcessing = 0;

// Excluded account keys (system programs)
const EXCLUDED_ACCOUNT_KEYS = new Set([
    '11111111111111111111111111111111',
    'ComputeBudget111111111111111111111111111111',
    'SysvarRent111111111111111111111111111111111',
    'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL',
    'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
    "SysvarRecentB1ockHashes11111111111111111111",
    "So11111111111111111111111111111111111111112",
    "Sysvar1nstructions1111111111111111111111111",
    "SysvarC1ock11111111111111111111111111111111"
]);

// Load blacklist from file
function loadBlacklist(): void {
    try {
        if (fs.existsSync(BLACKLIST_FILE)) {
            const data = fs.readFileSync(BLACKLIST_FILE, 'utf8');
            const blacklist = JSON.parse(data);
            blacklist.forEach((accountKey: string) => blacklistedAccountKeys.add(accountKey));
            console.log(`Loaded ${blacklistedAccountKeys.size} blacklisted account keys`);
        }
    } catch (error) {
        console.error('Error loading blacklist:', error);
    }
}

// Save blacklist to file (async)
async function saveBlacklist(): Promise<void> {
    try {
        const blacklistArray = Array.from(blacklistedAccountKeys);
        await fs.promises.writeFile(BLACKLIST_FILE, JSON.stringify(blacklistArray, null, 2));
    } catch (error) {
        console.error('Error saving blacklist:', error);
    }
}

// Periodic sweep to unblacklist eligible account keys
async function sweepUnblacklist(): Promise<void> {
    const now = Date.now();
    const toUnblacklist: string[] = [];
    for (const accountKey of blacklistedAccountKeys) {
        const timestamps = accountKeyActivity.get(accountKey) || [];
        const recentTimestamps = timestamps.filter(timestamp => now - timestamp < TIME_WINDOW);
        // If activity is below threshold and time window has elapsed since startup, unblacklist
        if (recentTimestamps.length <= MAX_TRANSACTIONS_PER_PERIOD && (now - startupTime) >= TIME_WINDOW) {
            toUnblacklist.push(accountKey);
            console.log(`Account key ${accountKey} unblacklisted by sweep - recent activity below threshold (${recentTimestamps.length} transactions in ${TIME_WINDOW/1000}s)`);
        }
        // Update the activity record in case timestamps were trimmed
        accountKeyActivity.set(accountKey, recentTimestamps);
    }
    if (toUnblacklist.length > 0) {
        toUnblacklist.forEach(key => blacklistedAccountKeys.delete(key));
        await saveBlacklist();
    }
}

// Check if account key should be blacklisted or unblacklisted
async function checkAndUpdateAccountKeyActivity(accountKey: string): Promise<boolean> {
    // Early return for excluded account keys
    if (EXCLUDED_ACCOUNT_KEYS.has(accountKey)) {
        return false;
    }
    
    // Early return if already blacklisted and no activity update needed
    const isCurrentlyBlacklisted = blacklistedAccountKeys.has(accountKey);
    const now = Date.now();
    
    // Get or create activity array
    let timestamps = accountKeyActivity.get(accountKey);
    if (!timestamps) {
        timestamps = [];
        accountKeyActivity.set(accountKey, timestamps);
    }
    
    // Filter recent timestamps and add current one
    const recentTimestamps = timestamps.filter(timestamp => now - timestamp < TIME_WINDOW);
    recentTimestamps.push(now);
    accountKeyActivity.set(accountKey, recentTimestamps);
    
    const timeElapsedSinceStartup = now - startupTime;
    
    // Check for unblacklisting first (early return if unblacklisted)
    if (isCurrentlyBlacklisted && 
        recentTimestamps.length <= MAX_TRANSACTIONS_PER_PERIOD && 
        timeElapsedSinceStartup >= TIME_WINDOW) {
        blacklistedAccountKeys.delete(accountKey);
        await saveBlacklist();
        console.log(`Account key ${accountKey} unblacklisted - recent activity below threshold (${recentTimestamps.length} transactions in ${TIME_WINDOW/1000}s)`);
        return false;
    }
    
    // Check for blacklisting (early return if should be blacklisted)
    if (recentTimestamps.length > MAX_TRANSACTIONS_PER_PERIOD && !isCurrentlyBlacklisted) {
        blacklistedAccountKeys.add(accountKey);
        await saveBlacklist();
        return true;
    }
    
    return isCurrentlyBlacklisted;
}

// Process queue worker
async function processQueue(): Promise<void> {
    while (processingQueue.length > 0 && activeProcessing < MAX_CONCURRENT_PROCESSING) {
        const task = processingQueue.shift();
        if (task) {
            activeProcessing++;
            task().finally(() => {
                activeProcessing--;
                // Continue processing queue if there are more tasks
                if (processingQueue.length > 0) {
                    setImmediate(() => processQueue());
                }
            });
        }
    }
}

// Add task to queue
function enqueueTransaction(data: any): void {
    // Early return for invalid data
    if (!data?.transaction?.transaction) {
        return;
    }
    
    const task = async () => {
        try {
            await processTransaction(data);
        } catch (error) {
            console.error('Error processing transaction:', error);
        }
    };
    
    processingQueue.push(task);
    
    // Start processing if not at capacity
    if (activeProcessing < MAX_CONCURRENT_PROCESSING) {
        setImmediate(() => processQueue());
    }
}

class GrpcStreamManager {
    private client!: Client;
    private stream: any;
    private isConnected: boolean = false;
    private reconnectAttempts: number = 0;
    private readonly maxReconnectAttempts: number = 50; // Increased attempts
    private readonly baseReconnectInterval: number = 5000; // 5 seconds
    private readonly dataHandler: (data: any) => void;
    private readonly endpoint: string;
    private readonly authToken: string;
    private reconnectTimer: NodeJS.Timeout | null = null;
    private pingInterval: NodeJS.Timeout | null = null;
    private isReconnecting: boolean = false;

    constructor(
        endpoint: string,
        authToken: string,
        dataHandler: (data: any) => void
    ) {
        this.endpoint = endpoint;
        this.authToken = authToken;
        this.dataHandler = dataHandler;
        this.createClient();
    }

    private createClient(): void {
        this.client = new Client(
            this.endpoint,
            this.authToken,
            { "grpc.max_receive_message_length": 64 * 1024 * 1024 }
        );
    }

    async connect(subscribeRequest: SubscribeRequest): Promise<void> {
        try {
            // Clear any existing timers
            this.clearTimers();
            
            this.stream = await this.client.subscribe();
            this.isConnected = true;
            this.reconnectAttempts = 0;
            this.isReconnecting = false;

            this.stream.on("data", this.handleData.bind(this));
            this.stream.on("error", this.handleError.bind(this, subscribeRequest));
            this.stream.on("end", () => this.handleDisconnect(subscribeRequest));
            this.stream.on("close", () => this.handleDisconnect(subscribeRequest));

            await this.write(subscribeRequest);
            this.startPing();
            
            console.log("gRPC connection established successfully");
        } catch (error) {
            console.error("Connection error:", error);
            this.isConnected = false;
            await this.scheduleReconnect(subscribeRequest);
        }
    }

    private async write(req: SubscribeRequest): Promise<void> {
        return new Promise((resolve, reject) => {
            if (!this.stream) {
                reject(new Error("Stream not available"));
                return;
            }
            this.stream.write(req, (err: any) => err ? reject(err) : resolve());
        });
    }

    private async scheduleReconnect(subscribeRequest: SubscribeRequest): Promise<void> {
        if (this.isReconnecting) {
            return; // Already reconnecting
        }

        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error(`Max reconnection attempts (${this.maxReconnectAttempts}) reached. Waiting 5 minutes before resetting...`);
            this.reconnectTimer = setTimeout(() => {
                this.reconnectAttempts = 0; // Reset attempts
                this.scheduleReconnect(subscribeRequest);
            }, 5 * 60 * 1000); // Wait 5 minutes
            return;
        }

        this.isReconnecting = true;
        this.reconnectAttempts++;
        
        // Exponential backoff with jitter
        const backoffMs = Math.min(
            this.baseReconnectInterval * Math.pow(2, this.reconnectAttempts - 1),
            60000 // Max 1 minute
        );
        const jitterMs = Math.random() * 1000; // Add up to 1 second jitter
        const delayMs = backoffMs + jitterMs;

        console.log(`Reconnecting... Attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts} (delay: ${Math.round(delayMs/1000)}s)`);

        this.reconnectTimer = setTimeout(async () => {
            try {
                // Recreate client on certain errors (every 5 attempts)
                if (this.reconnectAttempts % 5 === 0) {
                    console.log("Recreating gRPC client...");
                    this.createClient();
                }
                
                await this.connect(subscribeRequest);
            } catch (error) {
                console.error("Reconnection failed:", error);
                this.isReconnecting = false;
                await this.scheduleReconnect(subscribeRequest);
            }
        }, delayMs);
    }

    private clearTimers(): void {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
        if (this.pingInterval) {
            clearInterval(this.pingInterval);
            this.pingInterval = null;
        }
    }

    private startPing(): void {
        this.clearTimers();
        this.pingInterval = setInterval(() => {
            if (this.isConnected && this.stream) {
                this.write({
                    ping: { id: 1 },
                    accounts: {},
                    accountsDataSlice: [],
                    transactions: {},
                    blocks: {},
                    blocksMeta: {},
                    entry: {},
                    slots: {},
                    transactionsStatus: {},
                }).catch(error => {
                    console.error("Ping error:", error);
                    this.isConnected = false;
                });
            }
        }, 30000);
    }

    private handleData(data: any): void {
        try {
            const processed = this.processBuffers(data);
            this.dataHandler(processed);
        } catch (error) {
            console.error("Error processing data:", error);
        }
    }

    private handleError(subscribeRequest: SubscribeRequest, error: any): void {
        console.error("Stream error:", error);
        this.isConnected = false;
        
        // Don't immediately reconnect from error handler to avoid race conditions
        // Let the disconnect handler manage reconnection
        if (!this.isReconnecting) {
            setImmediate(() => this.handleDisconnect(subscribeRequest));
        }
    }

    private handleDisconnect(subscribeRequest: SubscribeRequest): void {
        if (this.isConnected) {
            console.log("Stream disconnected");
            this.isConnected = false;
        }
        
        // Clean up stream
        if (this.stream) {
            try {
                this.stream.removeAllListeners();
                this.stream.end();
            } catch (error) {
                // Ignore errors during cleanup
            }
            this.stream = null;
        }
        
        // Schedule reconnection if not already reconnecting
        if (!this.isReconnecting) {
            this.scheduleReconnect(subscribeRequest);
        }
    }

    private processBuffers(obj: any): any {
        if (!obj) return obj;
        if (Buffer.isBuffer(obj) || obj instanceof Uint8Array) {
            return bs58.default.encode(obj);
        }
        if (Array.isArray(obj)) {
            return obj.map(item => this.processBuffers(item));
        }
        if (typeof obj === 'object') {
            return Object.fromEntries(
                Object.entries(obj).map(([k, v]) => [k, this.processBuffers(v)])
            );
        }
        return obj;
    }

    // Add a method to refresh the gRPC connection
    async refreshConnection(subscribeRequest: SubscribeRequest): Promise<void> {
        try {
            console.log("Refreshing gRPC connection...");
            this.clearTimers();
            
            if (this.stream) {
                this.stream.removeAllListeners();
                this.stream.end();
                this.isConnected = false;
                this.stream = null;
            }
            
            // Reset reconnection state
            this.isReconnecting = false;
            this.reconnectAttempts = 0;
            
            // Recreate client
            this.createClient();
            
            await this.connect(subscribeRequest);
            console.log("gRPC connection refreshed successfully");
        } catch (error) {
            console.error("Error refreshing gRPC connection:", error);
            this.isConnected = false;
            await this.scheduleReconnect(subscribeRequest);
        }
    }

    // Add cleanup method
    public cleanup(): void {
        this.clearTimers();
        this.isConnected = false;
        this.isReconnecting = false;
        
        if (this.stream) {
            try {
                this.stream.removeAllListeners();
                this.stream.end();
            } catch (error) {
                // Ignore cleanup errors
            }
            this.stream = null;
        }
    }
}

// Transaction monitoring implementation
async function monitorTransactions() {
    // Load existing blacklist on startup
    loadBlacklist();
    
    const manager = new GrpcStreamManager(
        "http://frankfurt.grpc.pinnaclenode.com",
        "",
        handleTransactionUpdate
    );

    // Create subscription request for monitoring program transactions
    const subscribeRequest: SubscribeRequest = {
        transactions: {
            client: {
                accountInclude: [],
                accountExclude: [],
                accountRequired: [],
                vote: false,
                failed: false
            }
        },
        commitment: CommitmentLevel.CONFIRMED,
        accounts: {},
        accountsDataSlice: [],
        blocks: {},
        blocksMeta: {},
        entry: {},
        slots: {},
        transactionsStatus: {}
    };

    await manager.connect(subscribeRequest);

    // Refresh the gRPC connection every 15 minutes
    setInterval(() => {
        manager.refreshConnection(subscribeRequest);
    }, 15 * 60 * 1000);

    // Periodic sweep for unblacklisting every 5 minutes
    setInterval(() => {
        sweepUnblacklist().catch(console.error);
    }, 5 * 60 * 1000);
}

// Non-blocking handler that queues transactions for processing
function handleTransactionUpdate(data: any): void {
    enqueueTransaction(data);
}

// Async transaction processor
async function processTransaction(data: any): Promise<void> {
    // Early return for invalid data structure
    if (!data?.transaction?.transaction) {
        return;
    }
    
    const txInfo = data.transaction.transaction;
    const accountKeys = txInfo.transaction?.message?.accountKeys;
    
    // Early return if no account keys or invalid structure
    if (!accountKeys || !Array.isArray(accountKeys)) {
        return;
    }
    
    // CHECK BLACKLIST FIRST - before any other processing
    for (const accountKey of accountKeys) {
        if (await checkAndUpdateAccountKeyActivity(accountKey)) {
            return; // Skip transaction immediately if any account key is blacklisted
        }
    }
    
    // Only after blacklist check, do other validations
    // Early return for complex transactions
    if (accountKeys.length > 11) {
        return; // Not a simple transfer - exit immediately
    }
    
    // Early return if no meta data
    if (!txInfo.meta) {
        return;
    }
    
    const { preTokenBalances, postTokenBalances } = txInfo.meta;
    
    // Early return for invalid token balance structure
    if (!preTokenBalances || !postTokenBalances || 
        preTokenBalances.length > 2 || postTokenBalances.length !== 2 || 
        preTokenBalances.length < 1) {
        return;
    }
    
    // Early return if not all USDC (short-circuit evaluation)
    const USDCMint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";
    const allPreAreUSDC = preTokenBalances.every((balance: any) => balance?.mint === USDCMint);
    const allPostAreUSDC = postTokenBalances.every((balance: any) => balance?.mint === USDCMint);
    
    if (!allPreAreUSDC || !allPostAreUSDC) {
        return;
    }
    
    // Optimized balance calculation with early validation
    let sender = '';
    let receiver = '';
    let amountSent = 0;
    let amountReceived = 0;
    
    // Process balances more efficiently
    const ownerBalances = new Map<string, number>();
    
    // Subtract pre-balances
    for (const balance of preTokenBalances) {
        if (!balance?.owner || !balance?.uiTokenAmount?.uiAmountString) continue;
        const amount = parseFloat(balance.uiTokenAmount.uiAmountString);
        if (isNaN(amount)) continue;
        ownerBalances.set(balance.owner, (ownerBalances.get(balance.owner) || 0) - amount);
    }
    
    // Add post-balances
    for (const balance of postTokenBalances) {
        if (!balance?.owner || !balance?.uiTokenAmount?.uiAmountString) continue;
        const amount = parseFloat(balance.uiTokenAmount.uiAmountString);
        if (isNaN(amount)) continue;
        ownerBalances.set(balance.owner, (ownerBalances.get(balance.owner) || 0) + amount);
    }
    
    // Find sender and receiver in one pass
    for (const [owner, change] of ownerBalances.entries()) {
        if (change < 0 && !sender) {
            sender = owner;
            amountSent = Math.abs(change);
        } else if (change > 0 && !receiver) {
            receiver = owner;
            amountReceived = change;
        }
        // Early exit if both found
        if (sender && receiver) break;
    }
    
    // Early return if can't identify sender/receiver
    if (!sender || !receiver || amountSent <= 0 || amountReceived <= 0) {
        return;
    }
    
    // Early return for amount threshold
    if (amountSent < 1) {
        return;
    }
    
    // Early return for tolerance check
    const discrepancy = Math.abs(amountSent - amountReceived) / amountSent;
    if (discrepancy > 0.04) {
        return;
    }
    
    // Find sender's remaining balance (only if we've passed other checks)
    const senderPostBalance = postTokenBalances.find((balance: any) => balance.owner === sender);
    const senderRemainingBalance = senderPostBalance ? parseFloat(senderPostBalance.uiTokenAmount.uiAmountString) : 0;
    
    // Early return for balance threshold
    if (senderRemainingBalance < 100) {
        return;
    }
    
    // Only log and call API if all conditions are met
    console.log("Transaction is a simple transfer of USDC");
    console.log(txInfo.transaction.signatures[0]);
    console.log(`USDC Transfer Details:`);
    console.log(`  From: ${sender}`);
    console.log(`  To: ${receiver}`);
    console.log(`  Amount Sent: ${amountSent.toFixed(6)} USDC`);
    console.log(`  Amount Received: ${amountReceived.toFixed(6)} USDC`);
    console.log(`  Sender's Remaining Balance: ${senderRemainingBalance.toFixed(6)} USDC`);
    console.log(`  Discrepancy: ${(discrepancy * 100).toFixed(2)}%`);
    console.log("calling poison endpoint on localhost:5001/poison");
    
    // Use async axios call to avoid blocking
    axios.post('http://127.0.0.1:5001/poison', {
        detectedsender: sender,
        detectedreceiver: receiver
    }).catch(error => console.error('API call failed:', error));
}

// Global error handlers to prevent crashes
process.on('uncaughtException', (error) => {
    console.error('Uncaught Exception:', error);
    console.log('Process will continue running...');
});

process.on('unhandledRejection', (reason, promise) => {
    console.error('Unhandled Rejection at:', promise, 'reason:', reason);
    console.log('Process will continue running...');
});

// Graceful shutdown handler
process.on('SIGINT', () => {
    console.log('Received SIGINT, shutting down gracefully...');
    process.exit(0);
});

// Start monitoring with retry logic
async function startMonitoringWithRetry(): Promise<void> {
    let retryCount = 0;
    const maxRetries = 10;
    
    while (retryCount < maxRetries) {
        try {
            console.log(`Starting transaction monitoring... (attempt ${retryCount + 1})`);
            await monitorTransactions();
            break; // If successful, break out of retry loop
        } catch (error) {
            retryCount++;
            console.error(`Transaction monitoring failed (attempt ${retryCount}/${maxRetries}):`, error);
            
            if (retryCount >= maxRetries) {
                console.error('Max retries reached. Exiting...');
                process.exit(1);
            }
            
            // Wait before retrying (exponential backoff)
            const delay = Math.min(5000 * Math.pow(2, retryCount - 1), 60000);
            console.log(`Retrying in ${delay/1000} seconds...`);
            await new Promise(resolve => setTimeout(resolve, delay));
        }
    }
}

// Start monitoring
startMonitoringWithRetry();
