export default function ScanProgress({ isScanning, symbolCount = 6 }) {
  if (!isScanning) return null;
  return (
    <div className="flex items-center gap-2 text-sm text-purple-300">
      <span className="inline-flex h-2 w-2 rounded-full bg-purple-500 animate-pulse" />
      Analyzing {symbolCount} symbols...
    </div>
  );
}
