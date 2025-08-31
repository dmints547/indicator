// test_sockets.js
const { io } = require('socket.io-client');

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:5000';

// --- /ws: signal stream ---
const ws = io(`${BACKEND_URL}/ws`, { transports: ['websocket'] });

ws.on('connect', () => {
  console.log('[WS] connected');
});
ws.on('welcome', (msg) => {
  console.log('[WS] welcome:', msg);
});
ws.on('disconnect', (reason) => {
  console.log('[WS] disconnected:', reason);
});
ws.on('connect_error', (err) => {
  console.error('[WS] connect_error:', err.message);
});

// --- /prices: OHLC stream ---
const prices = io(`${BACKEND_URL}/prices`, { transports: ['websocket'] });

prices.on('connect', () => {
  console.log('[PRICES] connected');
});
prices.on('init_candles', (candles) => {
  console.log(`[PRICES] init_candles: ${Array.isArray(candles) ? candles.length : 'N/A'} bars`);
  // Show last candle summary for sanity
  if (Array.isArray(candles) && candles.length) {
    const c = candles[candles.length - 1];
    console.log('[PRICES] last candle:', { time: c.time, o: c.open, h: c.high, l: c.low, c: c.close });
  }
});
prices.on('new_candle', (c) => {
  console.log('[PRICES] new_candle:', { time: c.time, o: c.open, h: c.high, l: c.low, c: c.close });
});
prices.on('disconnect', (reason) => {
  console.log('[PRICES] disconnected:', reason);
});
prices.on('connect_error', (err) => {
  console.error('[PRICES] connect_error:', err.message);
});

// Keep process alive for streaming demo
setInterval(() => {}, 1 << 30);
