export default function DisplacementEvent({ event }) {
  return (
    <div className="border border-zinc-700 rounded-lg p-3">
      <p className="text-sm font-medium">{event.direction?.toUpperCase()} displacement</p>
      <p className="text-xs text-zinc-400">{event.start} → {event.end} · {event.atr_multiple}x ATR · {event.candles} candles</p>
    </div>
  );
}
