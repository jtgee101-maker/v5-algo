const API_URL = (process.env.VITE_API_URL || 'https://v5-algo.onrender.com/api').replace(/\/$/, '');

async function get(path) {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  const report = [];

  const health = await get('/health');
  assert(health.status === 'ok' || typeof health.status === 'string', 'health.status missing');
  report.push('health');

  const prices = await get('/prices');
  const priceKeys = Array.isArray(prices) ? prices.map((p) => p.symbol) : Object.keys(prices || {});
  assert(priceKeys.length >= 6, 'expected at least 6 price symbols');
  report.push('prices');

  const overview = await get('/market-overview');
  assert(overview?.prices, 'market-overview.prices missing');
  report.push('market-overview');

  const positions = await get('/tl/positions');
  assert(Array.isArray(positions?.positions) || Array.isArray(positions), 'positions list missing');
  report.push('positions');

  const drm = await get('/drm/USOIL');
  assert(drm?.symbol || drm?.signals, 'drm payload missing');
  report.push('drm');

  const signals = await get('/signals');
  assert(Array.isArray(signals) || Array.isArray(signals?.signals), 'signals list missing');
  report.push('signals');

  console.log('Backend verification passed:', report.join(', '));
}

main().catch((err) => {
  console.error('Backend verification failed:', err.message);
  process.exit(1);
});
