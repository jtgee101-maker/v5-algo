import Button from '../ui/Button';
import ConfidenceBar from './ConfidenceBar';
import ReasoningChain from './ReasoningChain';

export default function SignalDetail({ signal, onApprove, onReject }) {
  if (!signal) return <div className="card text-zinc-500">Select a signal.</div>;
  return (
    <div className="card space-y-3">
      <h3 className="text-lg font-semibold">{signal.symbol} {signal.side || signal.bias}</h3>
      <ConfidenceBar score={signal.conf_score || 0} />
      <ReasoningChain reasoning={signal.reasoning || signal.confluence_tags || []} />
      <div className="flex gap-2">
        <Button onClick={() => onApprove(signal)}>Take Trade</Button>
        <Button variant="ghost" onClick={() => onReject(signal)}>Pass</Button>
      </div>
    </div>
  );
}
