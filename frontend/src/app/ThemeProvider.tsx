import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
type Theme = 'light' | 'dark';
const ThemeContext = createContext<{ theme: Theme; toggle: () => void }>({
  theme: 'light',
  toggle: () => {},
});
export function ThemeProvider({
  children,
  defaultTheme,
}: {
  children: ReactNode;
  defaultTheme: Theme;
}) {
  const [choice, setChoice] = useState<Theme | null>(() => {
    try {
      const saved = localStorage.getItem('crowd-safety-theme');
      return saved === 'light' || saved === 'dark' ? saved : null;
    } catch {
      return null;
    }
  });
  const theme = choice ?? defaultTheme;
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);
  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setChoice(next);
    try {
      localStorage.setItem('crowd-safety-theme', next);
    } catch {
      /* Storage may be unavailable. The in-memory preference still works. */
    }
  };
  return <ThemeContext value={{ theme, toggle }}>{children}</ThemeContext>;
}
export function useTheme() {
  return useContext(ThemeContext);
}
