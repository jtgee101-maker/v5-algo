import { animate, useMotionValue, useTransform } from 'framer-motion';
import { useEffect } from 'react';

export default function AnimatedNumber({ value = 0, prefix = '', suffix = '', decimals = 2, duration = 0.4 }) {
  const mv = useMotionValue(value);
  const rounded = useTransform(mv, (latest) => Number(latest).toFixed(decimals));

  useEffect(() => {
    const controls = animate(mv, value, { duration });
    return () => controls.stop();
  }, [mv, value, duration]);

  return (
    <span>
      {prefix}
      {rounded}
      {suffix}
    </span>
  );
}
