export const fmtCurrency = (value = 0, digits = 2) =>
  `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;

export const fmtPct = (value = 0, digits = 2) => `${Number(value || 0).toFixed(digits)}%`;

export const sentimentToVariant = (sentiment) => {
  const s = `${sentiment || ''}`.toLowerCase();
  if (s.includes('bull')) return 'bullish';
  if (s.includes('bear')) return 'bearish';
  return 'neutral';
};
