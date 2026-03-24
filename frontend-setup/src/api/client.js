/**
 * ICT Trade Mission Control — API Client
 * Base fetch wrapper for all backend calls.
 * Backend: https://v5-algo.onrender.com/api
 */

const API_URL = import.meta.env.VITE_API_URL || 'https://v5-algo.onrender.com/api';

export async function get(path) {
  try {
    const res = await fetch(`${API_URL}${path}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const data = await res.json();
    return data.items || data;
  } catch (err) {
    console.error(`[API] GET ${path}:`, err.message);
    return null;
  }
}

export async function post(path, body = {}) {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return await res.json();
  } catch (err) {
    console.error(`[API] POST ${path}:`, err.message);
    return null;
  }
}

// ── Convenience exports ──────────────────────────────────────

// Prices
export const getAllPrices = () => get('/prices');
export const getSymbolDetail = (sym) => get(`/prices/${sym}`);
export const getMarketOverview = () => get('/market-overview');
export const getBtcChart = (days = 7) => get(`/chart/btc?days=${days}`);

// TradeLocker
export const getCandles = (sym, res = '1h', lb = '5D') =>
  get(`/tl/candles/${sym}?resolution=${res}&lookback=${lb}`);
export const getPositions = () => get('/tl/positions');
export const getInstruments = () => get('/tl/instruments');
export const getTLPrice = (sym) => get(`/tl/price/${sym}`);

// DRM — Your $23K Edge
export const getDRM = (sym, res = '1h', lb = '5D') =>
  get(`/drm/${sym}?resolution=${res}&lookback=${lb}`);
export const scanDRM = () => post('/drm/scan');
export const getProbability = (current, target, atr, days = 3) =>
  get(`/probability?current=${current}&target=${target}&atr=${atr}&days=${days}`);

// Analysis
export const runAnalysis = () => post('/analyze');

// Signals
export const getSignals = (limit = 50) => get(`/signals?limit=${limit}`);
export const approveSignal = (id) => post('/approve-signal', { signal_id: id, approved_by: 'operator' });
export const rejectSignal = (id, reason = 'pass') =>
  post('/reject-signal', { signal_id: id, rejected_by: 'operator', reason });

// News
export const getSentiment = () => get('/news/sentiment');
export const getLatestNews = (limit = 20) => get(`/news/latest?limit=${limit}`);
export const getBitcoinNews = () => get('/news/bitcoin');

// Review
export const getDailyReview = (date) => get(`/review/daily${date ? `?date=${date}` : ''}`);
export const getWeeklyReview = () => get('/review/weekly');
export const getStreak = () => get('/review/streak');
export const getTradeJournal = () => get('/review/trade-journal');

// Safety
export const getSafetyStatus = () => get('/safety/status');
export const resetBreaker = () => post('/safety/reset-breaker');

// System
export const getHealth = () => get('/health');
export const getAccountState = () => get('/account-state');
export const brokerTest = () => post('/broker-test');
export const getConfig = () => get('/config');
export const setMode = (mode) => post('/set-mode', { mode });
export const killSwitch = () => post('/kill-switch');

// Scratchpad
export const getScratchpadSessions = (count = 20) => get(`/scratchpad/sessions?count=${count}`);
export const getScratchpadDetail = (id) => get(`/scratchpad/${id}`);
