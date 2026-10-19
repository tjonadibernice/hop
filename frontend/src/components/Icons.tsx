import type { ReactNode } from "react";

/**
 * Small inline SVG icons. They're decorative (aria-hidden), so every button
 * that uses one also needs a text label or an aria-label.
 */
type IconProps = { size?: number; filled?: boolean };

function Svg({
  size = 20,
  filled = false,
  strokeWidth = 2.2,
  children,
}: IconProps & { strokeWidth?: number; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** The Hop logo mark: an arc that lands on a dot. */
export function HopMark({ size = 20 }: IconProps) {
  return (
    <Svg size={size} strokeWidth={2.6}>
      <path d="M4 18c2-7 6-11 10-11" />
      <path d="M11 4l4 3-3 4" />
      <circle cx="18" cy="18" r="2" />
    </Svg>
  );
}

export function HopArrow({ size = 22 }: IconProps) {
  return (
    <Svg size={size} strokeWidth={2.8}>
      <path d="M4 18c2-7 6-11 10-11" />
      <path d="M11 4l4 3-3 4" />
    </Svg>
  );
}

export function HeartIcon({ size, filled }: IconProps) {
  return (
    <Svg size={size} filled={filled}>
      <path d="M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.8 0-3 .5-4.5 2-1.5-1.5-2.7-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4 3 5.5l7 7Z" />
    </Svg>
  );
}

export function ThumbDownIcon({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M17 14V3" />
      <path d="M9 18.9 10 14H4.2a2 2 0 0 1-2-2.3l1.3-7A2 2 0 0 1 5.5 3H17v11l-4.3 7a2 2 0 0 1-3.7-1.1Z" />
    </Svg>
  );
}

export function ExternalIcon({ size = 16 }: IconProps) {
  return (
    <Svg size={size} strokeWidth={2.4}>
      <path d="M14 4h6v6" />
      <path d="M20 4l-9 9" />
      <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </Svg>
  );
}

export function CheckIcon({ size = 14 }: IconProps) {
  return (
    <Svg size={size} strokeWidth={3.4}>
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </Svg>
  );
}

export function MoonIcon({ size }: IconProps) {
  return (
    <Svg size={size}>
      <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
    </Svg>
  );
}

export function SunIcon({ size }: IconProps) {
  return (
    <Svg size={size}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Svg>
  );
}

export function StarIcon({ size = 14 }: IconProps) {
  return (
    <Svg size={size} filled strokeWidth={1.5}>
      <path d="M12 2.5l2.9 6.1 6.6.8-4.9 4.5 1.3 6.6L12 17.2l-5.9 3.3 1.3-6.6-4.9-4.5 6.6-.8z" />
    </Svg>
  );
}

export function ShuffleIcon({ size = 14 }: IconProps) {
  return (
    <Svg size={size} strokeWidth={2.4}>
      <path d="M16 3h5v5" />
      <path d="M4 20 21 3" />
      <path d="M21 16v5h-5" />
      <path d="M15 15l6 6" />
      <path d="M4 4l5 5" />
    </Svg>
  );
}
