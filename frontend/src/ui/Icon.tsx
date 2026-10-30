import type { CSSProperties } from 'react';
const paths: Record<string, string> = {
  search: 'm21 21-5-5 M19 10.5a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0',
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  play: 'm8 5 11 7-11 7Z',
  pause: 'M9 5v14M15 5v14',
  chevron: 'm9 5 7 7-7 7',
  close: 'm6 6 12 12M6 18 18 6',
  layers: 'm12 3 10 6-10 6L2 9Zm-9 10 9 5 9-5M3 17l9 5 9-5',
  target: 'M12 2v4M12 18v4M2 12h4M18 12h4M19 12a7 7 0 1 1-14 0 7 7 0 0 1 14 0',
  globe: 'M22 12A10 10 0 1 1 2 12a10 10 0 0 1 20 0M2 12h20M12 2c6 6 6 14 0 20-6-6-6-14 0-20',
  shield: 'm12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Zm-5 10 3 3 7-7',
  settings: 'M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6',
  external: 'M14 3h7v7M21 3l-9 9M10 3H3v18h18v-7',
  clock: 'M22 12A10 10 0 1 1 2 12a10 10 0 0 1 20 0M12 6v6l4 2',
  alert: 'm12 3 10 18H2Zm0 6v5m0 3v.1',
  bell: 'M18 8a6 6 0 0 0-12 0c0 8-3 8-3 10h18c0-2-3-2-3-10M10 22h4',
  refresh: 'M20 7V2l-4 4M4 17v5l4-4M21 12a9 9 0 0 0-15-7M3 12a9 9 0 0 0 15 7',
  check: 'm5 12 5 5L20 7',
  satellite: 'm8 8 8 8m-1-13 6 6-4 4-6-6Zm-8 8 6 6-4 4-6-6Zm3-2 4-4 4 4-4 4Z',
};
export function Icon({
  name,
  size = 18,
  style,
}: {
  name: string;
  size?: number;
  style?: CSSProperties;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={style}
    >
      <path d={paths[name] ?? paths.target} />
    </svg>
  );
}
