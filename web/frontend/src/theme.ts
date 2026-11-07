// Тема оформления — одна на всё приложение.
//
// Первый визит: тема следует настройке системы. Для инструмента, в котором
// работают часами, это приятнее, чем навязанный тёмный экран; дальше выбор
// человека запоминается в браузере и важнее системного.

export type Theme = "dark" | "light";

const STORAGE_KEY = "winnow.theme";

export function initialTheme(): Theme {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  const system = window.matchMedia?.("(prefers-color-scheme: light)");
  return system?.matches ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  window.localStorage.setItem(STORAGE_KEY, theme);
}

export function toggleTheme(theme: Theme): Theme {
  return theme === "dark" ? "light" : "dark";
}
