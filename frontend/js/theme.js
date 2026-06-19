/**
 * Theme Manager — Dark/Light Mode Toggle
 * Handles theme switching, persistence, and CSS variable updates
 */

const Theme = (function() {
  'use strict';

  const STORAGE_KEY = 'smartkcet-theme';
  const THEME_DARK = 'dark';
  const THEME_LIGHT = 'light';
  
  /**
   * Get the current theme from localStorage or system preference
   */
  function getCurrentTheme() {
    // Check localStorage first
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === THEME_DARK || stored === THEME_LIGHT) {
      return stored;
    }
    
    // Check system preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
      return THEME_LIGHT;
    }
    
    // Default to dark
    return THEME_DARK;
  }

  /**
   * Apply theme to the document
   */
  function applyTheme(theme) {
    const isDark = theme === THEME_DARK;
    
    // Set data attribute on html element
    document.documentElement.setAttribute('data-theme', theme);
    
    // Update CSS variables based on theme
    if (isDark) {
      applyDarkTheme();
    } else {
      applyLightTheme();
    }
    
    // Update toggle button if it exists
    updateToggleButton(isDark);
    
    // Store preference
    localStorage.setItem(STORAGE_KEY, theme);
    
    console.log(`[Theme] Switched to ${theme} mode`);
  }

  /**
   * Apply dark theme colors
   */
  function applyDarkTheme() {
    const root = document.documentElement;
    root.style.setProperty('--bg', '#060610');
    root.style.setProperty('--s1', '#0e0e1c');
    root.style.setProperty('--s2', '#14142a');
    root.style.setProperty('--s3', '#1a1a32');
    root.style.setProperty('--border', 'rgba(255,255,255,0.06)');
    root.style.setProperty('--border2', 'rgba(255,255,255,0.1)');
    root.style.setProperty('--text', '#eeeef8');
    root.style.setProperty('--muted', '#6868a0');
    root.style.setProperty('--muted2', '#9090c0');
  }

  /**
   * Apply light theme colors
   */
  function applyLightTheme() {
    const root = document.documentElement;
    root.style.setProperty('--bg', '#f8f9fc');
    root.style.setProperty('--s1', '#ffffff');
    root.style.setProperty('--s2', '#f3f4f8');
    root.style.setProperty('--s3', '#e8eaf0');
    root.style.setProperty('--border', 'rgba(0,0,0,0.08)');
    root.style.setProperty('--border2', 'rgba(0,0,0,0.12)');
    root.style.setProperty('--text', '#1a1a2e');
    root.style.setProperty('--muted', '#6b7280');
    root.style.setProperty('--muted2', '#4b5563');
  }

  /**
   * Update toggle button icon/state
   */
  function updateToggleButton(isDark) {
    const btn = document.getElementById('themeToggleBtn');
    if (!btn) return;
    
    if (isDark) {
      btn.setAttribute('aria-label', 'Switch to light mode');
      btn.title = 'Light Mode';
      btn.innerHTML = '☀️';
    } else {
      btn.setAttribute('aria-label', 'Switch to dark mode');
      btn.title = 'Dark Mode';
      btn.innerHTML = '🌙';
    }
  }

  /**
   * Toggle between themes
   */
  function toggle() {
    const current = getCurrentTheme();
    const next = current === THEME_DARK ? THEME_LIGHT : THEME_DARK;
    applyTheme(next);
    
    // Dispatch custom event for other modules to listen to
    window.dispatchEvent(new CustomEvent('themechange', { detail: { theme: next } }));
  }

  /**
   * Initialize theme system
   */
  function init() {
    const theme = getCurrentTheme();
    applyTheme(theme);
    
    // Wire up toggle button
    const btn = document.getElementById('themeToggleBtn');
    if (btn) {
      btn.addEventListener('click', toggle);
    }
    
    // Listen for system theme changes
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function(e) {
        if (!localStorage.getItem(STORAGE_KEY)) {
          applyTheme(e.matches ? THEME_LIGHT : THEME_DARK);
        }
      });
    }
    
    console.log('[Theme] Initialized with', theme, 'mode');
  }

  // Public API
  return {
    init: init,
    toggle: toggle,
    getCurrentTheme: getCurrentTheme,
    applyTheme: applyTheme,
    THEME_DARK: THEME_DARK,
    THEME_LIGHT: THEME_LIGHT,
  };
})();

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', Theme.init);
} else {
  Theme.init();
}
