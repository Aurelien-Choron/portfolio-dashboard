/** Tailwind config for the compiled stylesheet.
 *
 * The app used to pull cdn.tailwindcss.com, which compiles in the browser on
 * every visit and prints a "should not be used in production" warning. This
 * reproduces that build ahead of time: stock v3 defaults plus preflight, which
 * is what the CDN was giving us — the hand-written component layer in
 * base.html depends on preflight having reset headings and margins.
 *
 * Rebuild with: python scripts/build_css.py
 */
module.exports = {
  content: ['./dashboard/templates/**/*.html'],
  darkMode: 'class',
  theme: { extend: {} },
  plugins: [],
};
