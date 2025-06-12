import Client, { CommitmentLevel, SubscribeRequest } from "@triton-one/yellowstone-grpc";
import * as bs58 from 'bs58';
import * as fs from 'fs';
import * as path from 'path';

// Owner activity tracking
const ownerActivity = new Map<string, number[]>(); // owner -> array of timestamps
const blacklistedOwners = new Set<string>();
const BLACKLIST_FILE = path.join(__dirname, 'blacklisted_owners.json');
const MAX_TRANSACTIONS_PER_PERIOD = 20;
const TIME_WINDOW = 3600000; // 1 hour

// Load blacklist from file
function loadBlacklist(): void {
    try {
        if (fs.existsSync(BLACKLIST_FILE)) {
            const data = fs.readFileSync(BLACKLIST_FILE, 'utf8');
            const blacklist = JSON.parse(data);
            blacklist.forEach((owner: string) => blacklistedOwners.add(owner));
            console.log(`Loaded ${blacklistedOwners.size} blacklisted owners`);
        }
    } catch (error) {
        console.error('Error loading blacklist:', error);
    }
}

// Save blacklist to file
function saveBlacklist(): void {
    try {
        const blacklistArray = Array.from(blacklistedOwners);
        fs.writeFileSync(BLACKLIST_FILE, JSON.stringify(blacklistArray, null, 2));
        console.log(`Saved ${blacklistArray.length} blacklisted owners`);
    } catch (error) {
        console.error('Error saving blacklist:', error);
    }
}

// Check if owner should be blacklisted
function checkAndUpdateOwnerActivity(owner: string): boolean {
    const now = Date.now();
    
    // Get or create activity array for this owner
    if (!ownerActivity.has(owner)) {
        ownerActivity.set(owner, []);
    }
    
    const timestamps = ownerActivity.get(owner)!;
    
    // Remove timestamps older than the time window
    const recentTimestamps = timestamps.filter(timestamp => now - timestamp < TIME_WINDOW);
    
    // Add current timestamp
    recentTimestamps.push(now);
    
    // Update the activity record
    ownerActivity.set(owner, recentTimestamps);
    
    // Check if owner should be blacklisted
    if (recentTimestamps.length > MAX_TRANSACTIONS_PER_PERIOD && !blacklistedOwners.has(owner)) {
        blacklistedOwners.add(owner);
        saveBlacklist();
        console.log(`Owner ${owner} blacklisted for excessive activity (${recentTimestamps.length} transactions in ${TIME_WINDOW/1000}s)`);
        return true;
    }
    
    return blacklistedOwners.has(owner);
}

class GrpcStreamManager {
    private client: Client;
    private stream: any;
    private isConnected: boolean = false;
    private reconnectAttempts: number = 0;
    private readonly maxReconnectAttempts: number = 10;
    private readonly reconnectInterval: number = 5000; // 5 seconds
    private readonly dataHandler: (data: any) => void;

    constructor(
        endpoint: string,
        authToken: string,
        dataHandler: (data: any) => void
    ) {
        this.client = new Client(
            endpoint,
            authToken,
            { "grpc.max_receive_message_length": 64 * 1024 * 1024 }
        );
        this.dataHandler = dataHandler;
    }

    async connect(subscribeRequest: SubscribeRequest): Promise<void> {
        try {
            this.stream = await this.client.subscribe();
            this.isConnected = true;
            this.reconnectAttempts = 0;

            this.stream.on("data", this.handleData.bind(this));
            this.stream.on("error", this.handleError.bind(this));
            this.stream.on("end", () => this.handleDisconnect(subscribeRequest));
            this.stream.on("close", () => this.handleDisconnect(subscribeRequest));

            await this.write(subscribeRequest);
            this.startPing();
        } catch (error) {
            console.error("Connection error:", error);
            await this.reconnect(subscribeRequest);
        }
    }

    private async write(req: SubscribeRequest): Promise<void> {
        return new Promise((resolve, reject) => {
            this.stream.write(req, (err: any) => err ? reject(err) : resolve());
        });
    }

    private async reconnect(subscribeRequest: SubscribeRequest): Promise<void> {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error("Max reconnection attempts reached");
            return;
        }

        this.reconnectAttempts++;
        console.log(`Reconnecting... Attempt ${this.reconnectAttempts}`);

        setTimeout(async () => {
            try {
                await this.connect(subscribeRequest);
            } catch (error) {
                console.error("Reconnection failed:", error);
                await this.reconnect(subscribeRequest);
            }
        }, this.reconnectInterval * Math.min(this.reconnectAttempts, 5));
    }

    private startPing(): void {
        setInterval(() => {
            if (this.isConnected) {
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
                }).catch(console.error);
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

    private handleError(error: any): void {
        console.error("Stream error:", error);
        this.isConnected = false;
    }

    private handleDisconnect(subscribeRequest: SubscribeRequest): void {
        console.log("Stream disconnected");
        this.isConnected = false;
        this.reconnect(subscribeRequest);
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
}

// Transaction monitoring implementation
async function monitorTransactions() {
    // Load existing blacklist on startup
    loadBlacklist();
    
    const manager = new GrpcStreamManager(
        "http://new-york.grpc.pinnaclenode.com",
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
}

function handleTransactionUpdate(data: any): void {
    // Check if we have transaction data in the correct structure
    if (data?.transaction?.transaction) {
        const txInfo = data.transaction.transaction;
        // Filter: Only process transactions which are a simple transfer of USDC. We can check if the transaction is a simple transfer of USDC by checking if the number of pre and post token balances are both less than or equal to 2 and all of the token mints are usdc. There must be at least one pre and one post token balance.
        const USDCMint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";
        
        // Filter out complex transactions with more than 11 account keys
        if (txInfo.transaction.message.accountKeys.length > 11) {
            return; // Not a simple transfer
        }
        
        if(txInfo.meta.preTokenBalances.length <= 2 && txInfo.meta.postTokenBalances.length == 2 && txInfo.meta.preTokenBalances.length >= 1) {
            if(txInfo.meta.preTokenBalances.every((balance: any) => balance.mint == USDCMint) && txInfo.meta.postTokenBalances.every((balance: any) => balance.mint == USDCMint)) {
                
                // Calculate balance changes for each owner
                const balanceChanges = new Map<string, number>();
                
                // Process pre-token balances (subtract from owner's balance)
                txInfo.meta.preTokenBalances.forEach((balance: any) => {
                    const owner = balance.owner;
                    const amount = parseFloat(balance.uiTokenAmount.uiAmountString);
                    balanceChanges.set(owner, (balanceChanges.get(owner) || 0) - amount);
                });
                
                // Process post-token balances (add to owner's balance)
                txInfo.meta.postTokenBalances.forEach((balance: any) => {
                    const owner = balance.owner;
                    const amount = parseFloat(balance.uiTokenAmount.uiAmountString);
                    balanceChanges.set(owner, (balanceChanges.get(owner) || 0) + amount);
                });
                
                // Find sender (negative change) and receiver (positive change)
                let sender = '';
                let receiver = '';
                let amountSent = 0;
                let amountReceived = 0;
                
                for (const [owner, change] of balanceChanges.entries()) {
                    if (change < 0) {
                        sender = owner;
                        amountSent = Math.abs(change);
                    } else if (change > 0) {
                        receiver = owner;
                        amountReceived = change;
                    }
                }
                
                // Check if sender or receiver are blacklisted (and update activity)
                const senderBlacklisted = checkAndUpdateOwnerActivity(sender);
                const receiverBlacklisted = checkAndUpdateOwnerActivity(receiver);
                
                if (senderBlacklisted || receiverBlacklisted) {
                    return;
                }
                
                // Check if amounts are within 4% tolerance
                if (sender && receiver && amountSent > 0 && amountReceived > 0) {
                    const discrepancy = Math.abs(amountSent - amountReceived) / amountSent;
                    
                    // Find sender's post-transaction balance
                    const senderPostBalance = txInfo.meta.postTokenBalances.find((balance: any) => balance.owner === sender);
                    const senderRemainingBalance = senderPostBalance ? parseFloat(senderPostBalance.uiTokenAmount.uiAmountString) : 0;
                    
                    // Filter out transactions where sender's remaining balance is under 100 USDC
                    
                    if (discrepancy <= 0.04 && amountSent >= 1 && senderRemainingBalance >= 100) { // 4% tolerance
                        console.log("Transaction is a simple transfer of USDC");
                        console.log(txInfo.transaction.signatures[0]);
                        console.log(`USDC Transfer Details:`);
                        console.log(`  From: ${sender}`);
                        console.log(`  To: ${receiver}`);
                        console.log(`  Amount Sent: ${amountSent.toFixed(6)} USDC`);
                        console.log(`  Amount Received: ${amountReceived.toFixed(6)} USDC`);
                        console.log(`  Sender's Remaining Balance: ${senderRemainingBalance.toFixed(6)} USDC`);
                        console.log(`  Discrepancy: ${(discrepancy * 100).toFixed(2)}%`);
                    }
                } else {
                    console.log("Could not identify proper sender/receiver pair");
                }
                
                //print all accountkeys in the transaction
                console.log(txInfo.transaction.message.accountKeys);
            }
        }
            // Log messages
            //if (txInfo.meta.logMessages?.length > 0) {
              //  console.log('\n=== Program Logs ===');
             //   txInfo.meta.logMessages.forEach((log: string) => {
            //        console.log(`  ${log}`);
            //    });
           // }
    }
}

// Start monitoring
monitorTransactions().catch(console.error);