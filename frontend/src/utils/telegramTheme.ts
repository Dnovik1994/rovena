export type TelegramThemeParams = Record<string, string | undefined>;

const THEME_VARIABLES: Record<string, string> = {
  "--tg-theme-bg": "bg_color",
  "--tg-theme-text": "text_color",
  "--tg-theme-hint": "hint_color",
  "--tg-theme-link": "link_color",
  "--tg-theme-button": "button_color",
  "--tg-theme-button-text": "button_text_color",
  "--tg-theme-secondary-bg": "secondary_bg_color",
  "--tg-theme-accent": "accent_text_color",
  "--tg-theme-danger": "destructive_text_color",
};

export const applyTelegramTheme = (themeParams?: TelegramThemeParams): void => {
  if (!themeParams) {
    return;
  }

  Object.entries(THEME_VARIABLES).forEach(([cssVar, key]) => {
    const value = themeParams[key];
    if (value) {
      document.documentElement.style.setProperty(cssVar, value);
    }
  });
};
