/** Rebuild screenshots from exported Core scenes using epsm_viewer. See docs/usage.md. */
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {createServer} from 'node:http';
import {existsSync} from 'node:fs';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {resolve, extname} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const figures = fileURLToPath(new URL('.', import.meta.url));
const output = resolve(root, 'output/docs/viewers');
const python = process.env.EPSM_PYTHON || (existsSync(resolve(root, '.venv/bin/python')) ? resolve(root, '.venv/bin/python') : 'python3');
// Generate from maintained examples and the current installed source, without a simulation.
execFileSync(python, ['-c', `
from pathlib import Path
from examples.context import example_context
from epsm_core import Footprint, GeometrySpec
from epsm_viewer import write_scene
geometry = GeometrySpec.from_footprint(Footprint.rectangle(30, 20), storeys=3, storey_height_m=3)
for preset in ('custom', 'rural', 'urban_lowrise_dense', 'urban_highrise_dense'):
    context = example_context(geometry, preset)
    scene = geometry.scene(context=context)
    directory = Path('output/docs/viewers') / preset
    write_scene(scene, directory=directory / 'viewer')
`], {cwd: root, stdio: 'inherit'});

const modulePath = process.env.EPSM_PUPPETEER_MODULE || resolve(root, 'output/docs-tools/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js');
const {default: puppeteer} = await import(pathToFileURL(modulePath).href);
const mime = {'.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json'};
const server = createServer(async (req, res) => {
  const path = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const file = resolve(output, '.' + path, path.endsWith('/') ? 'index.html' : '');
  if (!file.startsWith(output + '/')) { res.writeHead(403).end(); return; }
  try {
    const body = await readFile(file);
    res.writeHead(200, {'Content-Type': mime[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store'}).end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
const checks = [];
try {
  browser = await puppeteer.launch({headless: true,
    ...(process.env.EPSM_BROWSER_EXECUTABLE ? {executablePath: process.env.EPSM_BROWSER_EXECUTABLE} : {}),
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  });
  const page = await browser.newPage();
  await page.setViewport({width: 1440, height: 1040, deviceScaleFactor: 1});
  await page.setCacheEnabled(false);
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  for (const preset of ['custom', 'rural', 'urban_lowrise_dense', 'urban_highrise_dense']) {
    await page.goto(`http://127.0.0.1:${server.address().port}/${preset}/viewer/`, {waitUntil: 'domcontentloaded'});
    // Read the public rendered DOM, including the viewer's encapsulated controls.
    await page.waitForFunction(() => {
      const roots = [document];
      for (let i = 0; i < roots.length; i++) {
        for (const node of roots[i].querySelectorAll('*')) if (node.shadowRoot) roots.push(node.shadowRoot);
      }
      return roots.some(root => root.querySelector('canvas')) && roots.some(root => {
        const text = root.querySelector('#status')?.textContent || '';
        return text && !/loading|failed/i.test(text);
      });
    });
    const state = await page.evaluate(() => {
      const roots = [document];
      for (let i = 0; i < roots.length; i++) {
        for (const node of roots[i].querySelectorAll('*')) if (node.shadowRoot) roots.push(node.shadowRoot);
      }
      return {
        canvasCount: roots.reduce((count, root) => count + root.querySelectorAll('canvas').length, 0),
        statusText: roots.map(root => root.querySelector('#status')?.textContent).find(Boolean),
      };
    });
    assert.ok(state.canvasCount > 0);
    assert.ok(state.statusText && !/failed/i.test(state.statusText));
    await page.screenshot({path: resolve(figures, `viewer-${preset}.png`), clip: {x: 0, y: 60, width: 1090, height: 980}});
    if (preset === 'urban_highrise_dense') await page.screenshot({path: resolve(figures, 'viewer-controls.png')});
    checks.push({preset, ...state, status: 'passed', check: 'browser-render-smoke'});
    console.log(`${preset}: exported scene rendered without browser errors`);
  }
  assert.deepEqual(errors, []);
  await mkdir(resolve(root, 'output/validation'), {recursive: true});
  await writeFile(resolve(root, 'output/validation/viewer-checks.json'), JSON.stringify({checks, page_errors: errors}, null, 2));
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
