"""Markdown to HTML conversion using markdown-it-py."""
from markdown_it import MarkdownIt
from html import escape
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import unquote, urlsplit
import yaml
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound
from mdit_py_plugins.texmath import texmath_plugin
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.gfm import gfm_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.attrs import attrs_plugin, attrs_block_plugin
from mdit_py_plugins.subscript import sub_plugin
from mdit_py_plugins.superscript import superscript_plugin
from mdit_py_plugins.admon import admon_plugin


def highlight_code(code, language, attributes):
    if language in ('math', 'tex-math'):
        return '<pre class="MathDiv">' + escape(code) + '</pre>'
    if not language:
        return ''
    try:
        lexer = get_lexer_by_name(language)
    except ClassNotFound:
        return ''
    rendered = highlight(code, lexer, HtmlFormatter(nowrap=True))
    return '<pre class="Highlight"><code class="language-' + escape(language, quote=True) + '">' + rendered + '</code></pre>'

_md = MarkdownIt('commonmark', {'highlight': highlight_code})
_md.use(gfm_plugin, front_matter=True)
_md.options['strikethrough_single_tilde'] = False
_md.use(deflist_plugin)
_md.use(attrs_plugin, spans=True, allowed=['id', 'class', 'title', 'width', 'height'])
_md.use(attrs_block_plugin, allowed=['id', 'class', 'title'])
_md.use(sub_plugin)
_md.use(superscript_plugin)
_md.use(admon_plugin)
_md.use(anchors_plugin, max_level=6)
_md.use(texmath_plugin, delimiters='brackets')
_md.use(dollarmath_plugin, allow_space=True, allow_digits=False, double_inline=True)


def heading_ids(state):
    for index, token in enumerate(state.tokens):
        if token.type != 'heading_open':
            continue
        inline = state.tokens[index + 1]
        if not inline.children or inline.children[-1].type != 'text':
            continue
        match = re.search(r'\s+\{#([\w:.-]+)\}\s*$', inline.children[-1].content)
        if match:
            token.attrSet('id', match[1])
            inline.children[-1].content = inline.children[-1].content[:match.start()]


_md.core.ruler.push('heading_ids', heading_ids)


def render_math(self, tokens, idx, options, env):
    token = tokens[idx]
    tag = 'span'
    if token.block or token.type == 'math_inline_double':
        tag = 'div'
    if token.type == 'math_block_label':
        label = escape(token.info, quote=True)
        return f'<div id="{label}" class="Equation"><div class="MathDiv">{escape(token.content)}</div><a href="#{label}">({escape(token.info)})</a></div>'
    return f'<{tag} class="Math{tag.title()}">{escape(token.content)}</{tag}>'


for name in ('math_inline', 'math_inline_double', 'math_block', 'math_block_eqno', 'math_block_label'):
    _md.add_render_rule(name, render_math)


def local_resource(value, base_path):
    if not isinstance(value, str):
        raise ValueError('Bibliography and CSL paths must be strings')
    parts = urlsplit(value)
    if parts.scheme not in ('', 'file') or parts.netloc not in ('', 'localhost'):
        raise ValueError('Bibliography and CSL files must be local')
    path = Path(unquote(parts.path))
    if not path.is_absolute():
        path = base_path / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f'Bibliography or CSL file not found: {path.name}')
    return path


def render_citations(text, base_path):
    metadata_match = re.match(r'\A---\s*\n(.*?)\n(?:---|\.\.\.)\s*(?:\n|$)', text, re.DOTALL)
    if not metadata_match:
        return None
    metadata = yaml.safe_load(metadata_match[1]) or {}
    if not isinstance(metadata, dict):
        raise ValueError('Document metadata must be a YAML mapping')
    if not metadata.get('bibliography') and not metadata.get('references'):
        return None
    pandoc = shutil.which('pandoc')
    if pandoc is None:
        raise ValueError('Install Pandoc to render bibliography citations; footnotes and reference links remain available')
    command = [pandoc, '--from=markdown+tex_math_single_backslash', '--to=html5', '--citeproc', '--katex', '--sandbox', '--wrap=none', '--metadata=link-citations:true']
    bibliography = metadata.pop('bibliography', [])
    if isinstance(bibliography, str):
        bibliography = [bibliography]
    if not isinstance(bibliography, list):
        raise ValueError('Bibliography must name a local file or a list of local files')
    for filename in bibliography:
        command.append('--bibliography=' + str(local_resource(filename, base_path)))
    style = metadata.pop('csl', None)
    if style is not None:
        command.append('--csl=' + str(local_resource(style, base_path)))
    source = '---\n' + yaml.safe_dump(metadata, allow_unicode=True) + '---\n' + text[metadata_match.end():]
    result = subprocess.run(command, input=source, text=True, capture_output=True, cwd=base_path, timeout=5)
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Pandoc could not render the bibliography')
    warnings = [line for line in result.stderr.splitlines() if 'Citeproc:' in line]
    notice = ''
    if warnings:
        notice = '<aside class="Notice">' + escape(' '.join(warnings)) + '</aside>'
    return notice + result.stdout


def convert_markdown(text, base_path=None):
    """Convert Markdown text to an HTML fragment string."""
    if re.search(r'(?<![\w\\])@[-\w][\w:./-]*', text):
        try:
            rendered = render_citations(text, Path(base_path) if base_path else Path.cwd())
            if rendered is not None:
                return rendered
        except (ValueError, yaml.YAMLError, OSError, subprocess.TimeoutExpired) as error:
            return '<aside class="Notice">' + escape(f'Citation rendering unavailable: {error}') + '</aside>' + _md.render(text)
    return _md.render(text)
