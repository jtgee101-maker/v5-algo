import { useState } from 'react';
import { getProbability } from '../../api/client';
import Button from '../ui/Button';

export default function ProbabilityCalculator() {
  const [form, setForm] = useState({ current: 90.4, target: 105, atr: 8.99, days: 5 });
  const [result, setResult] = useState(null);

  const onSubmit = async (e) => {
    e.preventDefault();
    const data = await getProbability(form.current, form.target, form.atr, form.days);
    setResult(data);
  };

  return (
    <form onSubmit={onSubmit} className="card space-y-3">
      <h3 className="font-semibold">Probability Calculator</h3>
      <div className="grid grid-cols-2 gap-3 text-sm">
        {Object.keys(form).map((k) => (
          <label key={k} className="flex flex-col gap-1">
            <span className="text-zinc-400 capitalize">{k}</span>
            <input className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2" type="number" step="any" value={form[k]} onChange={(e)=>setForm((s)=>({ ...s, [k]: Number(e.target.value) }))} />
          </label>
        ))}
      </div>
      <Button type="submit">Calculate</Button>
      {result ? <p className="text-sm text-zinc-300">{result.interpretation || `${result.touch_probability}% probability`}</p> : null}
    </form>
  );
}
