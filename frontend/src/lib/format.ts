const numberFormat = new Intl.NumberFormat('en-US');
const compactFormat = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });
export const formatNumber = (value: number) => numberFormat.format(value);
export const formatCompact = (value: number) => compactFormat.format(value);
export function formatDistance(metres: number): string {
  if (!Number.isFinite(metres)) return '—';
  return Math.abs(metres) >= 1000 ? `${(metres / 1000).toFixed(2)} km` : `${Math.round(metres)} m`;
}
const superscripts: Record<string, string> = { '-': '⁻', '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹' };
export function formatProbability(pc: number): string {
  if (!Number.isFinite(pc) || pc < 0 || pc > 1) return '—';
  if (pc === 0) return '0';
  const [coefficient, exponent] = pc.toExponential(1).split('e');
  return `${coefficient} × 10${String(Number(exponent)).split('').map((char) => superscripts[char] ?? char).join('')}`;
}
export function probabilityOdds(pc: number): string {
  return pc > 0 && pc <= 1 ? `1 in ${formatNumber(Math.round(1 / pc))}` : pc === 0 ? 'No modeled collision' : 'Unavailable';
}
export function formatCountdown(tca: string | number, timeMs = Date.now()): string {
  const delta = (typeof tca === 'number' ? tca : Date.parse(tca)) - timeMs;
  if (!Number.isFinite(delta)) return '—';
  const totalSec = Math.floor(Math.abs(delta) / 1000);
  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  const seconds = totalSec % 60;
  return `${delta < 0 ? 'T+' : 'T−'}${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}
export function formatUtc(value: string | number | Date): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return '—';
  return `${date.toISOString().slice(11, 19)} UTC`;
}
export function formatUtcDate(value: string | number | Date): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '—' : `${date.toISOString().slice(0, 10)} · ${formatUtc(date)}`;
}
