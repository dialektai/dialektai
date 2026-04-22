const paths = {
  chat: 'M3 4h14v9H8l-4 3V4z',
  folder: 'M2 5h6l2 2h8v9H2V5z',
  terminal: 'M3 4h14v12H3V4zM6 8l2 2-2 2M10 12h4',
  cog: 'M10 13a3 3 0 100-6 3 3 0 000 6zm0-9v2M10 16v2M4 10H2M18 10h-2M5.6 5.6L4.2 4.2M15.8 15.8l-1.4-1.4M5.6 14.4l-1.4 1.4M15.8 4.2l-1.4 1.4',
  plus: 'M10 4v12M4 10h12',
  send: 'M3 10l14-6-6 14-2-6-6-2z',
  attach: 'M14 8l-5 5a2.5 2.5 0 01-3.5-3.5l6-6a4 4 0 015.5 5.5L9.5 16',
  mic: 'M10 3a2.5 2.5 0 00-2.5 2.5v5a2.5 2.5 0 005 0v-5A2.5 2.5 0 0010 3zM5 10a5 5 0 0010 0M10 15v3',
  cpu: 'M5 5h10v10H5V5zM2 7h1M2 10h1M2 13h1M17 7h1M17 10h1M17 13h1M7 2v1M10 2v1M13 2v1M7 17v1M10 17v1M13 17v1',
  file: 'M5 2h7l4 4v12H5V2zM12 2v4h4',
  globe: 'M10 2a8 8 0 100 16 8 8 0 000-16zM2 10h16M10 2c2.5 2.8 2.5 13.2 0 16M10 2c-2.5 2.8-2.5 13.2 0 16',
  chev: 'M6 8l4 4 4-4',
  chevR: 'M8 6l4 4-4 4',
  check: 'M4 10l4 4 8-8',
  screen: 'M2 4h16v10H2V4zM7 18h6M10 14v4',
  search: 'M8.5 3a5.5 5.5 0 104.1 9.3l4 4 1-1-4-4A5.5 5.5 0 008.5 3z',
  shield: 'M10 2l7 3v5c0 5-3.5 7.5-7 8-3.5-.5-7-3-7-8V5l7-3z',
  sparkle: 'M10 2v5M10 13v5M2 10h5M13 10h5M5 5l3 3M12 12l3 3M5 15l3-3M12 8l3-3',
  copy: 'M6 6h10v10H6V6zM4 4h10v2M4 4v10h2',
  stop: 'M5 5h10v10H5z',
  refresh: 'M3 10a7 7 0 0112-5l2 2M17 10a7 7 0 01-12 5l-2-2M15 3v4h4M5 17v-4H1',
  diamond: 'M10 2l8 8-8 8-8-8 8-8z',
  x: 'M4 4l12 12M16 4L4 16',
  ham: 'M3 6h14M3 10h14M3 14h14',
  edit: 'M3 14l1.5-1.5L13 4l2.5 2.5-8.5 8.5L3 16zM11 6l3 3',
  download: 'M10 3v10M6 9l4 4 4-4M3 15h14v2H3z',
};

export default function Icon({ name, size = 14, color = 'currentColor' }) {
  return (
    <svg
      width={size} height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="square"
      strokeLinejoin="miter"
      style={{ flexShrink: 0 }}
    >
      <path d={paths[name] || paths.diamond} />
    </svg>
  );
}
