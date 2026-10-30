import type { ReactNode } from 'react';
import { motion, type HTMLMotionProps } from 'motion/react';
import { useReducedMotion } from './useReducedMotion';
import './demo-motion.css';

export function ScoreFill({ fraction }: { fraction: number }) {
  const reduced = useReducedMotion();
  return <motion.i initial={reduced ? false : { scaleX: 0 }}
    animate={{ scaleX: Math.max(0, Math.min(1, fraction)) }}
    transition={reduced ? { duration: 0 } : { type: 'spring', stiffness: 95, damping: 20 }}
    style={{ width: '100%', transformOrigin: 'left center', transition: 'none' }} />;
}

export function SignedStamp({ children }: { children: ReactNode }) {
  const reduced = useReducedMotion();
  return <motion.div className="agreement-status" initial={reduced ? false : { scale: 1.16, rotate: -5, opacity: 0 }}
    animate={{ scale: 1, rotate: 0, opacity: 1 }}
    transition={{ duration: reduced ? 0 : 0.36, ease: [0.22, 1, 0.36, 1] }}>
    {children}
  </motion.div>;
}

export function ThreatRow({ index, ...props }: HTMLMotionProps<'button'> & { index: number }) {
  const reduced = useReducedMotion();
  return <motion.button {...props} initial={reduced ? false : { opacity: 0, y: 9 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: reduced ? 0 : 0.35, delay: reduced ? 0 : Math.min(index, 6) * 0.055, ease: 'easeOut' }} />;
}
