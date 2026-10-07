// MathJax settings for the docs: \( \) and \[ \] delimiters, only inside Material's arithmatex elements, and
// typeset again after each page change of the instant-navigation site.
window.MathJax = {
  tex: { inlineMath: [["\\(", "\\)"]], displayMath: [["\\[", "\\]"]], processEscapes: true, processEnvironments: true },
  options: { ignoreHtmlClass: ".*|", processHtmlClass: "arithmatex" }
};
document$.subscribe(() => { MathJax.typesetPromise(); });
