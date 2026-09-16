/** VITalWatch — local Tailwind build (Phase 1; replaces the CDN script tag).
 *
 * The templates were written against the Tailwind Play CDN, which is the v3
 * engine with preflight enabled — this config reproduces exactly that, offline.
 * The class set is frozen at build time by scanning every Jinja template
 * (including the macro files, where several classes live). A template that
 * introduces a new utility class needs `npm run build:css` re-run; the class
 * is otherwise silently absent, which the Phase 6 verification pass catches.
 */
module.exports = {
  content: ["./app/templates/**/*.html"],
  theme: { extend: {} },
  plugins: [],
};
