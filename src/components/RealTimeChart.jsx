import React, { useEffect, useRef } from 'react';
import Plotly from 'plotly.js-dist-min';
import { io } from 'socket.io-client';

const WS_BASE = process.env.REACT_APP_WS_URL || 'http://localhost:5000';

function movingAverage(arr, window) {
  const out = new Array(arr.length).fill(null);
  let sum = 0;
  for (let i = 0; i < arr.length; i++) {
    sum += arr[i];
    if (i >= window) sum -= arr[i - window];
    if (i >= window - 1) out[i] = sum / window;
  }
  return out;
}

export default function RealTimeChart() {
  const divRef = useRef(null);
  const dataRef = useRef({ x: [], open: [], high: [], low: [], close: [] });

  useEffect(() => {
    Plotly.newPlot(
      divRef.current,
      [
        {
          type: 'candlestick',
          x: [],
          open: [],
          high: [],
          low: [],
          close: [],
          name: 'Price',
        },
        {
          type: 'scatter',
          mode: 'lines',
          x: [],
          y: [],
          name: 'MA10',
          line: { color: 'orange', width: 2 },
        },
      ],
      {
        title: 'Live Candlestick (MA10)',
        xaxis: { rangeslider: { visible: false } },
        yaxis: { fixedrange: false },
        template: 'plotly_dark',
      }
    );

    const socket = io(`${WS_BASE}/prices`, { transports: ['websocket'] });

    socket.on('init_candles', (candles) => {
      const x = candles.map(c => c.time);
      const open = candles.map(c => c.open);
      const high = candles.map(c => c.high);
      const low = candles.map(c => c.low);
      const close = candles.map(c => c.close);
      dataRef.current = { x, open, high, low, close };
      const ma10 = movingAverage(close, 10);
      Plotly.react(divRef.current, [
        { type: 'candlestick', x, open, high, low, close, name: 'Price' },
        { type: 'scatter', mode: 'lines', x, y: ma10, name: 'MA10', line: { color: 'orange', width: 2 } },
      ]);
    });

    socket.on('new_candle', (c) => {
      const d = dataRef.current;
      const lastIdx = d.x.length - 1;
      if (lastIdx >= 0 && c.time === d.x[lastIdx]) {
        // Update last candle (still forming)
        d.open[lastIdx] = c.open;
        d.high[lastIdx] = c.high;
        d.low[lastIdx] = c.low;
        d.close[lastIdx] = c.close;
        const ma10 = movingAverage(d.close, 10);
        Plotly.update(
          divRef.current,
          { open: [d.open], high: [d.high], low: [d.low], close: [d.close] },
          {},
          [0]
        );
        Plotly.update(divRef.current, { x: [d.x], y: [ma10] }, {}, [1]);
      } else {
        // Append new candle
        d.x.push(c.time);
        d.open.push(c.open);
        d.high.push(c.high);
        d.low.push(c.low);
        d.close.push(c.close);
        const ma10 = movingAverage(d.close, 10);
        Plotly.extendTraces(
          divRef.current,
          { x: [[c.time]], open: [[c.open]], high: [[c.high]], low: [[c.low]], close: [[c.close]] },
          [0]
        );
        Plotly.update(divRef.current, { x: [d.x], y: [ma10] }, {}, [1]);
      }
    });

    return () => socket.close();
  }, []);

  return <div ref={divRef} style={{ width: '100%', height: 500 }} />;
}
