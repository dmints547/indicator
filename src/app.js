// src/App.js
import React, { useEffect, useMemo, useState } from 'react';
import io from 'socket.io-client';
import axios from 'axios';

const WS_URL = process.env.REACT_APP_WS_URL || 'http://localhost:5000';
const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:5000';

const TIMEFRAMES = ['4hour','2hour','1hour','30min','15min','5min','3min','1min'];

function App() {
  const [signal, setSignal] = useState(null);
  const [error, setError] = useState(null);
  const [symbol, setSymbol] = useState('AAPL');
  const [tf, setTf] = useState('1min');

  useEffect(() => {
    const socket = io(`${WS_URL}/ws`, { transports: ['websocket'] });
    socket.on('signal', (payload) => {
      // Only accept updates for current symbol+tf
      if (payload.symbol?.toUpperCase() === symbol.toUpperCase() && payload.timeframe === tf) {
        setSignal(payload);
      }
    });
    socket.on('disconnect', () => console.log('WebSocket disconnected'));
    // initial fetch
    axios.get(`${API_URL}/api/signal`, { params: { symbol, tf } })
      .then(res => setSignal(res.data))
      .catch(err => setError(err.response?.data?.error || err.message));
    return () => socket.disconnect();
  }, [symbol, tf]);

  const summary = useMemo(() => {
    if (!signal) return null;
    const s = signal;
    return [
      { label: 'Symbol', value: s.symbol || symbol },
      { label: 'Timeframe', value: s.timeframe || tf },
      { label: 'Trend', value: s.trend },
      { label: 'Strength', value: s.strength },
      { label: 'Confidence', value: s.confidence?.toFixed(2) },
      { label: 'Entry', value: Number(s.entry).toFixed(2) },
      { label: 'Stop Loss', value: Number(s.stop_loss).toFixed(2) },
      { label: 'Take Profit', value: Number(s.take_profit).toFixed(2) },
      { label: 'Last Close', value: Number(s.last_close).toFixed(2) },
    ];
  }, [signal, symbol, tf]);

  return (
    <div style={{ padding: 24, maxWidth: 720, margin: '0 auto', fontFamily: 'Inter, system-ui, Arial' }}>
      <h1>Live Trading Signals</h1>

      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          placeholder="Symbol (e.g. AAPL)"
          style={{ padding: 8 }}
        />
        <select value={tf} onChange={(e) => setTf(e.target.value)} style={{ padding: 8 }}>
          {TIMEFRAMES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {error && <div style={{ color: 'crimson', marginBottom: 12 }}>Error: {error}</div>}
      {!signal ? (
        <div>Waiting for signal…</div>
      ) : (
        <>
          <ul>
            {summary.map(row => (
              <li key={row.label}><strong>{row.label}:</strong> {row.value}</li>
            ))}
          </ul>
          <details style={{ marginTop: 16 }}>
            <summary>Why this signal?</summary>
            <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 6 }}>
{JSON.stringify(signal.explain, null, 2)}
            </pre>
          </details>
          <div style={{ marginTop: 16, color: '#666' }}>
            Updated: {new Date(signal.timestamp || signal.time).toLocaleString()}
          </div>
        </>
      )}
    </div>
  );
}

export default App;
