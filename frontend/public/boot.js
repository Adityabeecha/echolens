// Runs before first paint (a classic, blocking script in <head>).
// A file rather than inline script so the Content-Security-Policy can be
// script-src 'self' with no 'unsafe-inline' and no hash to keep in sync.
(() => {
  let theme = "light";
  try {
    theme = localStorage.getItem("echolens_theme") === "dark" ? "dark" : "light";
  } catch {
    // Restricted storage is a valid browser state; Light remains safe.
  }
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = theme === "dark" ? "#0B0B0F" : "#FFFFFF";

  // Non-blocking web fonts: the stylesheet is requested with media="print" and
  // switched on once loaded. This replaces an inline onload="" handler, which
  // the CSP would block.
  const fonts = document.getElementById("el-fonts");
  if (fonts) {
    const on = () => { fonts.media = "all"; };
    if (fonts.sheet) on();
    else fonts.addEventListener("load", on);
  }
})();
