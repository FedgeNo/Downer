"""Preview styling for the markdown editor."""
from pygments.formatters import HtmlFormatter

PREVIEW_CSS = """
/* downer preview styles */
:root {
    --bg-color: #ffffff;
    --text-color: #1a1a1a;
    --border-color: #e0e0e0;
    --code-bg: #f5f5f5;
    --link-color: #2563eb;
}

:root.Dark {
        --bg-color: #1e1e1e;
        --text-color: #e0e0e0;
        --border-color: #404040;
        --code-bg: #2d2d2d;
        --link-color: #60a5fa;
}

html { background: var(--bg-color); color-scheme: light; }
html.Dark { color-scheme: dark; }

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
        "Helvetica Neue", Arial, sans-serif;
    font-size: 16px;
    line-height: 1.7;
    color: var(--text-color);
    background: var(--bg-color);
    max-width: 800px;
    margin: 0 auto;
    padding: 2rem 1rem;
}

h1, h2, h3, h4, h5, h6 {
    margin-top: 1.5rem;
    margin-bottom: 1rem;
    line-height: 1.25;
    font-weight: 600;
}

h1 {
    font-size: 2rem;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 0.3rem;
}

h2 {
    font-size: 1.5rem;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 0.3rem;
}

h3 { font-size: 1.25rem; }
h4 { font-size: 1.1rem; }
h5 { font-size: 1rem; }
h6 { font-size: 0.9rem; }

p { margin-bottom: 1rem; }

a {
    color: var(--link-color);
    text-decoration: none;
}

a:hover { text-decoration: underline; }

code {
    font-family: "SF Mono", Consolas, "Liberation Mono", monospace;
    font-size: 0.9em;
    background: var(--code-bg);
    padding: 0.1em 0.3em;
    border-radius: 3px;
}

pre {
    background: var(--code-bg);
    padding: 1rem;
    border-radius: 6px;
    overflow-x: auto;
    margin-bottom: 1rem;
}

pre code {
    background: none;
    padding: 0;
}

blockquote {
    border-left: 4px solid var(--border-color);
    margin: 0 0 1rem 0;
    padding: 0.5rem 1rem;
    opacity: 0.8;
}

ul, ol {
    margin-bottom: 1rem;
    padding-left: 2rem;
}

li { margin-bottom: 0.25rem; }

table {
    border-collapse: collapse;
    margin-bottom: 1rem;
    width: 100%;
}

th, td {
    border: 1px solid var(--border-color);
    padding: 0.5rem 1rem;
    text-align: left;
}

th { background: var(--code-bg); }

img { max-width: 100%; height: auto; }

hr {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 2rem 0;
}

.footnotes, .references { font-size: 0.9em; border-top: 1px solid var(--border-color); margin-top: 2rem; padding-top: 1rem; }
.footnote-ref { font-size: 0.8em; }
.csl-entry { margin-bottom: 0.75rem; }
.hanging-indent .csl-entry { padding-left: 1.5rem; text-indent: -1.5rem; }
dt { font-weight: 600; }
dd { margin-bottom: 1rem; }
.task-list-item { list-style: none; }
.task-list-item input { margin-right: 0.5rem; }
.markdown-alert, .admonition, .Notice { border-left: 4px solid var(--link-color); background: var(--code-bg); padding: 0.75rem 1rem; margin: 1rem 0; }
.markdown-alert-title, .admonition-title { font-weight: 600; }
.Notice { border-color: #d29922; }
.Equation { display: flex; align-items: center; gap: 1rem; }
.Equation .MathDiv { flex: 1; min-width: 0; }
.MathDiv, .katex-display { overflow-x: auto; overflow-y: hidden; }
"""

PREVIEW_CSS += HtmlFormatter(style='friendly').get_style_defs('.Highlight')
PREVIEW_CSS += HtmlFormatter(style='monokai').get_style_defs(':root.Dark .Highlight')
