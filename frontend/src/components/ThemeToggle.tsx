import { useTheme } from "../theme";
import { MoonIcon, SunIcon } from "./Icons";

/** Switches between light (Sticker pop) and dark (Night glow). */
export default function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const dark = theme === "dark";

  return (
    <button
      type="button"
      className="icon-button"
      onClick={toggle}
      aria-pressed={dark}
      aria-label="Night mode"
      title={dark ? "Switch to light mode" : "Switch to night mode"}
    >
      {dark ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}
