import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import { useBackendChecks } from '../hooks/useBackendChecks';

const PHASES = [
  { id: 0, title: 'Pre-flight backend checks', status: 'active', detail: 'Validate Render endpoints and API contracts before building UI pages.' },
  { id: 1, title: 'Foundation layer', status: 'done', detail: 'API client, hooks, shared state, reusable UI components.' },
  { id: 2, title: 'Layout shell', status: 'done', detail: 'Sidebar, header, responsive app shell, page routing.' },
  { id: 3, title: 'Dashboard hero', status: 'done', detail: 'Market overview, key stats, trading context at a glance.' },
  { id: 4, title: 'DRM analysis page', status: 'done', detail: 'Displacement + reaction model panels and calculators.' },
  { id: 5, title: 'Charts page', status: 'done', detail: 'Candles, symbols, and quick technical context.' },
  { id: 6, title: 'Scanner + Signals', status: 'done', detail: 'Signal discovery and approval flow.' },
  { id: 7, title: 'News + Research + Positions', status: 'done', detail: 'Context + execution + exposure in one workflow.' },
  { id: 8, title: 'Remaining pages', status: 'active', detail: 'Performance, risk, settings, and usability hardening.' },
  { id: 9, title: 'Polish + deploy', status: 'next', detail: 'QA, API reliability checks, deploy automation and monitoring.' },
];

function StatusBadge({ status }) {
  if (status === 'done') return <Badge variant="live">Done</Badge>;
  if (status === 'active') return <Badge variant="high">In Progress</Badge>;
  return <Badge variant="neutral">Next</Badge>;
}

export default function BuildProgress() {
  const checks = useBackendChecks();

  return (
    <div className="space-y-4">
      <Card>
        <h2 className="text-xl font-semibold">Frontend Delivery Plan</h2>
        <p className="text-sm text-zinc-400 mt-1">
          This page tracks the PRD/PDP build sequence so we can ship the product step by step with live backend validation.
        </p>
      </Card>

      <Card>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">Render API Verification</h3>
            <p className="text-sm text-zinc-400">Checks run every 45 seconds from the frontend.</p>
          </div>
          <Button variant="ghost" onClick={() => checks.refetch()} loading={checks.isFetching}>Re-check now</Button>
        </div>

        {checks.data ? (
          <div className="mt-3 space-y-2">
            <p className="text-sm">
              Passed {checks.data.passed}/{checks.data.total} checks
              {checks.data.failed ? <span className="text-rose-300"> • {checks.data.failed} failing</span> : <span className="text-emerald-300"> • all healthy</span>}
            </p>
            <div className="grid md:grid-cols-2 gap-2">
              {checks.data.checks.map((item) => (
                <div key={item.key} className="rounded-lg border border-zinc-800 p-3 bg-zinc-900/50">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium">{item.label}</p>
                    <Badge variant={item.status === 'pass' ? 'bullish' : 'bearish'}>{item.status}</Badge>
                  </div>
                  <p className="text-xs text-zinc-400 mt-1">{item.detail}</p>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-sm text-zinc-400 mt-3">Running backend checks...</p>
        )}
      </Card>

      <div className="grid gap-3">
        {PHASES.map((phase) => (
          <Card key={phase.id}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-xs uppercase tracking-wide text-zinc-500">Phase {phase.id}</p>
                <h3 className="font-semibold">{phase.title}</h3>
                <p className="text-sm text-zinc-400 mt-1">{phase.detail}</p>
              </div>
              <StatusBadge status={phase.status} />
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
