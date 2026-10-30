import { useLayoutEffect } from 'react';
import { animate, motion, useMotionValue, useTransform } from 'motion/react';
import { useReducedMotion } from './useReducedMotion';
import './demo-motion.css';

const integer = (value: number) => Math.round(value).toLocaleString('en-US');

/** Retargets from the displayed value, so rapid updates never queue stale numbers. */
export default function Ticker({ value, format = integer }: {
  value: number | null | undefined; format?: (value: number) => string;
}) {
  const reduced = useReducedMotion();
  const current = useMotionValue(value ?? 0);
  const display = useTransform(current, format);
  useLayoutEffect(() => {
    if (value == null || !Number.isFinite(value)) return;
    if (reduced) { current.set(value); return; }
    const animation = animate(current, value, { duration: 0.65, ease: [0.22, 1, 0.36, 1] });
    return () => animation.stop();
  }, [value, reduced, current]);
  if (value == null || !Number.isFinite(value)) return <span>—</span>;
  return <span className="number-ticker">
    <motion.span aria-hidden="true">{display}</motion.span>
    <span className="ticker-accessible">{format(value)}</span>
  </span>;
}
