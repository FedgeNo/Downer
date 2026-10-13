"""Markdown extensions and local bibliography rendering."""
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from downer.converter import convert_markdown


class MarkdownTests(unittest.TestCase):
    def test_labeled_footnotes_have_forward_and_back_links(self):
        html = convert_markdown('A claim.[^smith]\n\n[^smith]: Smith, *A Study*, 2024.\n')
        self.assertIn('href="#fn1"', html)
        self.assertIn('href="#fnref1"', html)
        self.assertIn('<em>A Study</em>', html)
        self.assertEqual(html.count('class="footnote-item"'), 1)

    def test_reference_links_remain_supported(self):
        html = convert_markdown('[Smith 2024][smith]\n\n[smith]: https://example.com/paper')
        self.assertIn('href="https://example.com/paper"', html)

    def test_common_extensions(self):
        html = convert_markdown('~~old~~\n\n- [x] Done\n- [ ] Todo\n\nhttps://example.com\n\nTerm\n: Definition\n\nH~2~O and x^2^\n\n> [!NOTE]\n> Useful information.')
        for expected in ('<s>old</s>', 'type="checkbox"', 'checked', 'href="https://example.com"', '<dt>Term</dt>', '<dd>Definition</dd>', '<sub>2</sub>', '<sup>2</sup>', 'markdown-alert'):
            self.assertIn(expected, html)

    def test_front_matter_is_hidden_and_heading_ids_work(self):
        html = convert_markdown('---\ntitle: Private metadata\n---\n\n## Read Me {#custom-id}\n')
        self.assertNotIn('Private metadata', html)
        self.assertIn('<h2 id="custom-id">Read Me</h2>', html)

    def test_spaced_math_and_bracket_math_preserve_tex(self):
        expression = r'$ \mu_d\propto\frac{v_d}{D_d^\star}, $'
        html = convert_markdown(expression + '\n\n' + r'\(x^2\)' + '\n\n' + r'\[y^2\]')
        self.assertEqual(html.count('class="MathSpan"'), 2)
        self.assertIn('class="MathDiv"', html)
        self.assertIn(r'\frac{v_d}{D_d^\star}', html)

    def test_code_and_currency_are_not_math(self):
        html = convert_markdown('`$x$`\n\n```text\n$y$\n```\n\nPrices are $5 and $10.')
        self.assertNotIn('MathSpan', html)
        self.assertIn('$5 and $10', html)

    def test_code_highlighting_and_unknown_language(self):
        html = convert_markdown('```python\nprint("Hello")\n```\n\n```unknown-language\n<script>\n```')
        self.assertIn('class="Highlight"', html)
        self.assertIn('&lt;script&gt;', html)

    def test_missing_pandoc_preserves_content_with_notice(self):
        source = '---\nreferences:\n- id: smith\n  title: A Study\n---\nA claim [@smith].'
        with patch('downer.converter.shutil.which', return_value=None):
            html = convert_markdown(source)
        self.assertIn('Install Pandoc', html)
        self.assertIn('A claim', html)

    def test_remote_bibliography_is_rejected_without_starting_pandoc(self):
        source = '---\nbibliography: https://example.com/references.bib\n---\n[@smith]'
        with patch('downer.converter.shutil.which', return_value='/usr/bin/pandoc'), patch('downer.converter.subprocess.run') as run:
            html = convert_markdown(source)
        run.assert_not_called()
        self.assertIn('must be local', html)

    @unittest.skipUnless(shutil.which('pandoc'), 'Pandoc is optional')
    def test_local_bibtex_citations_and_math(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'references.bib').write_text('@article{smith2024, author={Alex Smith}, title={A Study}, year={2024}, journal={Example Journal}}')
            source = '---\nbibliography: references.bib\n---\nSee [@smith2024]. Math $x^2$.\n'
            html = convert_markdown(source, base_path=root)
        self.assertIn('href="#ref-smith2024"', html)
        self.assertIn('id="ref-smith2024"', html)
        self.assertIn('A Study', html)
        self.assertIn('class="math inline">x^2', html)

    @unittest.skipUnless(shutil.which('pandoc'), 'Pandoc is optional')
    def test_missing_citation_is_visible(self):
        source = '---\nreferences:\n- id: smith\n  title: A Study\n---\n[@missing]'
        html = convert_markdown(source)
        self.assertIn('citation missing not found', html)


if __name__ == '__main__':
    unittest.main()
