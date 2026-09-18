/**
 * Light / dark switch.
 *
 * Three states so the OS preference stays honoured until the user actually
 * expresses one: auto -> light -> dark -> auto. The choice is written to
 * <html data-theme> and remembered per browser.
 */
const NEXT = { auto: "light", light: "dark", dark: "auto" };
const LABEL = { auto: "theme: auto", light: "theme: light", dark: "theme: dark" };

export default function ThemeToggle({ theme, setTheme }) {
  return (
    <button
      className="theme-toggle"
      onClick={() => setTheme(NEXT[theme] || "auto")}
      title="Switch between automatic, light and dark"
    >
      {LABEL[theme] || LABEL.auto}
    </button>
  );
}
