const API_URL = (import.meta.env.VITE_API_URL || 'https://v5-algo.onrender.com/api').replace(/\/$/, '');
const REQUEST_TIMEOUT_MS = 20_000;

async function request(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}${path}`, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
      signal: controller.signal,
    });

    if (!response.ok) {
      const text = await response.text().catch(() => 'Unknown error');
      throw new Error(`${response.status} ${response.statusText}: ${text}`);
    }

    const text = await response.text();
    return text ? JSON.parse(text) : null;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`Request timed out for ${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

const get = (path) => request(path);
const post = (path, body = {}) => request(path, { method: 'POST', body: JSON.stringify(body) });

export const getAllPrices = () => get('/prices');
export const getSymbolDetail = (symbol) => get(`/prices/${symbol}`);
export const getMarketOverview = () => get('/market-overview');
export const getBtcChart = (days = 7) => get(`/chart/btc?days=${days}`);
export const getCandles = (symbol, resolution = '1h', lookback = '5D') =>
  get(`/tl/candles/${symbol}?resolution=${resolution}&lookback=${lookback}`);
export const getPositions = () => get('/tl/positions');
export const getInstruments = () => get('/tl/instruments');
export const getDRM = (symbol, resolution = '1h', lookback = '5D') =>
  get(`/drm/${symbol}?resolution=${resolution}&lookback=${lookback}`);
export const scanDRM = () => post('/drm/scan');
export const getProbability = (current, target, atr, days = 5) =>
  get(`/probability?current=${current}&target=${target}&atr=${atr}&days=${days}`);
export const runAnalysis = () => post('/analyze');
export const getSignals = () => get('/signals');
export const approveSignal = (signalId, approvedBy = 'operator') =>
  post('/approve-signal', { signal_id: signalId, approved_by: approvedBy });
export const rejectSignal = (signalId, reason = 'pass', rejectedBy = 'operator') =>
  post('/reject-signal', { signal_id: signalId, reason, rejected_by: rejectedBy });
export const getSentiment = () => get('/news/sentiment');
export const getLatestNews = (limit = 20) => get(`/news/latest?limit=${limit}`);
export const getBitcoinNews = () => get('/news/bitcoin');
export const getDailyReview = () => get('/review/daily');
export const getWeeklyReview = () => get('/review/weekly');
export const getStreak = () => get('/review/streak');
export const getTradeJournal = () => get('/review/trade-journal');
export const getSafetyStatus = () => get('/safety/status');
export const resetBreaker = () => post('/safety/reset-breaker');
export const getHealth = () => get('/health');
export const getAccountState = () => get('/account-state');
export const brokerTest = () => post('/broker-test');
export const getConfig = () => get('/config');
export const setMode = (mode) => post('/set-mode', { mode });
export const killSwitch = () => post('/kill-switch');
export const getScratchpadSessions = (count = 20) => get(`/scratchpad/sessions?count=${count}`);
export const getScratchpadDetail = (sessionId) => get(`/scratchpad/${sessionId}`);

export { API_URL };
