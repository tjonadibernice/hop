import { useSyncExternalStore } from "react";

/**
 * Light mode is the "Sticker pop" style and dark mode is "Night glow".
 * The chosen theme is written to <html data-theme="...">, and index.css
 * swaps every color, font, and shadow based on that attribute.
 *
 * Until the user presses the toggle, Hop follows the operating system's
 * light or dark setting. Pressing it saves the choice in localStorage.
 * index.html runs the same logic in a tiny inline script before the page
 * paints, so the wrong theme never flashes on load.
 */
export type Theme = "light" | "dark";

const STORAGE_KEY = "hop-theme";
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
const listeners = new Set<() => void>();

/** The saved choice, or null if the user never pressed the toggle. */
function savedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    // Storage can be blocked (private mode, strict settings)
    return null;
  }
}

export function currentTheme(): Theme {
  return savedTheme() ?? (darkQuery.matches ? "dark" : "light");
}

function apply() {
  document.documentElement.dataset.theme = currentTheme();
  listeners.forEach((listener) => listener());
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Still switch for this visit, even if it can't be remembered
    document.documentElement.dataset.theme = theme;
    listeners.forEach((listener) => listener());
    return;
  }
  apply();
}

// Follow the OS setting when it changes, and keep other open tabs in sync
darkQuery.addEventListener("change", apply);
window.addEventListener("storage", (event) => {
  if (event.key === STORAGE_KEY) {
    apply();
  }
});

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The active theme, plus a function that switches to the other one. */
export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(subscribe, () =>
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );
  const toggle = () => setTheme(theme === "dark" ? "light" : "dark");
  return [theme, toggle];
}
