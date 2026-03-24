export default function ReasoningChain({ reasoning = [] }) {
  return (
    <ul className="list-disc list-inside text-sm text-zinc-300 space-y-1">
      {reasoning.map((r, idx) => <li key={`${r}-${idx}`}>✅ {r}</li>)}
    </ul>
  );
}
