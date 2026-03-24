import ProgressRing from '../ui/ProgressRing';

export default function ProbabilityRing({ value, label }) {
  return <ProgressRing value={value} max={100} size={80} color="#a855f7" label={label} />;
}
