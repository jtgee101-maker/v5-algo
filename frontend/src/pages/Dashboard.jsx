import { useQuery } from '@tanstack/react-query';
import { getAccountState, getScratchpadSessions } from '../api/client';
import DRMPanel from '../components/drm/DRMPanel';
import MarketGrid from '../components/markets/MarketGrid';
import SentimentOrb from '../components/news/SentimentOrb';
import PositionCard from '../components/positions/PositionCard';
import PnLSummary from '../components/positions/PnLSummary';
import AnimatedNumber from '../components/ui/AnimatedNumber';
import Card from '../components/ui/Card';
import { ErrorState, LoadingState } from '../components/ui/PageState';
import { useMarketData } from '../hooks/useMarketData';
import { usePositions } from '../hooks/usePositions';
import { fmtCurrency } from '../lib/format';

export default function Dashboard() {
  const market = useMarketData();
  const positions = usePositions();
  const account = useQuery({ queryKey: ['account'], queryFn: getAccountState, refetchInterval: 30_000 });
  const sessions = useQuery({ queryKey: ['scratch-sessions-dashboard'], queryFn: () => getScratchpadSessions(5), refetchInterval: 60_000 });

  if (market.isLoading) return <LoadingState message="Loading market overview..." />;
  if (market.error) return <ErrorState message="Unable to load market overview." onRetry={market.refetch} />;

  const posRows = positions.data?.positions || [];
  const sentiment = market.data?.news_sentiment || {};

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <p className="text-xs uppercase tracking-wide text-zinc-500">Portfolio Equity</p>
          <p className="font-mono text-5xl mt-2">
            <AnimatedNumber value={account.data?.equity || 0} prefix="$" decimals={2} duration={0.5} />
          </p>
          <div className="mt-4"><PnLSummary positions={posRows} /></div>
          <div className="mt-4 space-y-2 max-h-64 overflow-auto pr-1">
            {posRows.length ? posRows.map((p) => <PositionCard key={`${p.instrument}-${p.side}`} position={p} />) : <p className="text-sm text-zinc-500">No open positions.</p>}
          </div>
        </Card>
        <DRMPanel />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <h3 className="font-semibold mb-3">Market Pulse</h3>
          <SentimentOrb sentiment={sentiment.btc_sentiment} score={sentiment.sentiment_score} />
          <div className="mt-3 text-sm text-zinc-400 space-y-1">
            {(sentiment.top_headlines || []).slice(0, 3).map((h) => (
              <p key={h.title}>• {h.title} <span className="text-zinc-500">({h.source})</span></p>
            ))}
          </div>
        </Card>
        <Card>
          <h3 className="font-semibold mb-3">Crypto Global</h3>
          <p className="text-zinc-400 text-sm">Market Cap: <span className="font-mono text-zinc-100">{fmtCurrency(market.data?.crypto_global?.total_market_cap_usd, 0)}</span></p>
          <p className="text-zinc-400 text-sm mt-2">BTC Dominance: <span className="font-mono text-zinc-100">{market.data?.crypto_global?.btc_dominance ?? '-'}%</span></p>
          <p className="text-zinc-400 text-sm mt-2">24h Change: <span className="font-mono text-zinc-100">{market.data?.crypto_global?.market_cap_change_24h ?? '-'}%</span></p>
          <h4 className="font-semibold mt-5 mb-2">Activity Feed</h4>
          {(sessions.data?.sessions || []).map((s) => (
            <p className="text-xs text-zinc-400 border-b border-zinc-800 py-1" key={s.session_id}>Session {s.session_id} · {s.entries} entries</p>
          ))}
        </Card>
      </div>

      <div>
        <h3 className="font-semibold mb-3">Market Grid</h3>
        <MarketGrid prices={market.data?.prices} sessions={market.data?.sessions} />
      </div>
    </div>
  );
}
