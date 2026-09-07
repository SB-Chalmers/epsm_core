"""Validate notebook structure and export self-contained HTML for visual review."""
import ast
import base64
import json
import mimetypes
import re
from collections import Counter
from pathlib import Path

import nbformat
from bs4 import BeautifulSoup
from nbconvert import HTMLExporter

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/notebook-refinement'


def main():
    exporter = HTMLExporter(exclude_input_prompt=True, exclude_output_prompt=True)
    report, figures = [], Counter()
    for path in sorted((ROOT / 'demo').glob('*/*.ipynb')):
        notebook = nbformat.read(path, 4)
        nbformat.validate(notebook)
        for cell in notebook.cells:
            if cell.cell_type == 'code':
                for node in ast.walk(ast.parse(cell.source)):
                    if isinstance(node, ast.Call) and ast.unparse(node.func) in ('plt.figure', 'plt.subplots'):
                        assert any(k.arg == 'figsize' for k in node.keywords), (path, cell.id)
                assert not any(o.output_type == 'error' for o in cell.outputs), path
        markdown = '\n'.join(c.source for c in notebook.cells if c.cell_type == 'markdown')
        figures.update(re.findall(r'!\[[^\]]*\]\(([^)]+)\)', markdown))
        for link in re.findall(r'\]\(([^)]+)\)', markdown):
            if not link.startswith(('http:', 'https:', '#', 'attachment:')):
                assert (path.parent / link.split('#')[0]).exists(), (path, link)
        html, _ = exporter.from_notebook_node(notebook, resources={'metadata': {'path': str(path.parent)}})
        soup = BeautifulSoup(html, 'html.parser')
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if not src.startswith('data:'):
                asset = (path.parent / src).resolve()
                img['src'] = ('data:' + mimetypes.guess_type(asset)[0] + ';base64,'
                              + base64.b64encode(asset.read_bytes()).decode())
        target = OUTPUT / 'html' / path.parent.name / (path.stem + '.html')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(soup))
        report.append({'notebook': str(path.relative_to(ROOT)), 'images': len(soup.find_all('img')),
                       'html': str(target.relative_to(OUTPUT / 'html'))})
    assert all(count == 1 for count in figures.values()), figures
    (OUTPUT / 'audit.json').write_text(json.dumps({'notebooks': report, 'reference_figures': figures}, indent=2))
    links = '\n'.join(f'<li><a href="{r["html"]}">{r["notebook"]}</a></li>' for r in report)
    (OUTPUT / 'html/index.html').write_text('<h1>Executed EPSM notebook review</h1><ul>' + links + '</ul>')
    print(f'{len(report)} notebooks; {sum(r["images"] for r in report)} images; {len(figures)} unique reference figures')


if __name__ == '__main__':
    main()
