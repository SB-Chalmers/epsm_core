/** Rebuild viewer screenshots and check context clipping. See docs/usage.md. */
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
import json
from pathlib import Path
from examples.context import example_context
from epsm_core import Footprint, GeometrySpec
from epsm_core.inspection import geometry_scene
from epsm_core.viewer import write_viewer
geometry = GeometrySpec.from_footprint(Footprint.rectangle(30, 20), storeys=3, storey_height_m=3)
for preset in ('custom', 'rural', 'urban_lowrise_dense', 'urban_highrise_dense'):
    context = example_context(geometry, preset)
    scene, report = geometry_scene(geometry, context=context)
    directory = Path('output/docs/viewers') / preset
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'scene.json').write_text(json.dumps(scene))
    (directory / 'compilation.json').write_text(json.dumps(report))
    write_viewer(directory / 'scene.json', directory / 'viewer')
`], {cwd: root, stdio: 'inherit'});

const modulePath = process.env.EPSM_PUPPETEER_MODULE || resolve(root, 'output/docs-tools/node_modules/puppeteer/lib/esm/puppeteer/puppeteer.js');
const {default: puppeteer} = await import(pathToFileURL(modulePath).href);
const mime = {'.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json'};
const server = createServer(async (req, res) => {
  const path = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  const file = resolve(output, '.' + path, path.endsWith('/') ? 'index.html' : '');
  if (!file.startsWith(output + '/')) { res.writeHead(403).end(); return; }
  try {
    let body = await readFile(file);
    if (file.endsWith('/viewer.js')) {
      // Expose render state only in this temporary test server; bundled assets stay unchanged.
      body = body.toString().replace('renderer.setAnimationLoop(', 'globalThis.viewerCheck={meshes,renderer,camera,plane};\nrenderer.setAnimationLoop(');
    }
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
    await page.waitForFunction(() => globalThis.viewerCheck);
    const original = await page.evaluate(() => {
      const {meshes, renderer} = viewerCheck;
      const context = meshes.filter(m => m.userData.kind === 'context');
      const roofs = context.filter(m => m.userData.metadata.surface_type === 'Roof');
      return {clipping: renderer.localClippingEnabled, contextCount: context.length, roofs: roofs.length,
        roofsComplete: roofs.every(m => m.visible && !m.material.clippingPlanes.length && !m.children[0].material.clippingPlanes.length),
        sliderDisabled: document.querySelector('#clip').disabled};
    });
    assert.equal(original.clipping, false);
    assert.equal(original.sliderDisabled, true);
    assert.ok(original.roofs > 0 && original.roofsComplete);
    // Capture the unmodified default view, including real UI labels and geometry.
    await page.screenshot({path: resolve(figures, `viewer-${preset}.png`), clip: {x: 0, y: 60, width: 1090, height: 980}});
    if (preset === 'urban_highrise_dense') await page.screenshot({path: resolve(figures, 'viewer-controls.png')});
    await page.$eval('#opacity', el => {el.value = 0.2; el.dispatchEvent(new Event('input', {bubbles: true}));});
    assert.ok(await page.evaluate(() => viewerCheck.meshes.filter(m => m.userData.kind === 'context').every(m => m.material.opacity === 1 && !m.material.transparent)));
    await page.click('#cutaway');
    await page.$eval('#clip', el => {el.value = 4.5; el.dispatchEvent(new Event('input', {bubbles: true}));});
    await page.select('#storey', '1');
    const cut = await page.evaluate(() => ({
      enabled: viewerCheck.renderer.localClippingEnabled,
      contextVisible: viewerCheck.meshes.filter(m => m.userData.kind === 'context' && m.visible).length,
      contextUnclipped: viewerCheck.meshes.filter(m => m.userData.kind === 'context').every(m => !m.material.clippingPlanes.length && !m.children[0].material.clippingPlanes.length),
      targetClipped: viewerCheck.meshes.filter(m => m.userData.kind !== 'context').every(m => m.material.clippingPlanes.length === 1),
    }));
    assert.equal(cut.enabled, true);
    assert.equal(cut.contextVisible, original.contextCount);
    assert.ok(cut.contextUnclipped && cut.targetClipped);
    if (preset === 'urban_highrise_dense') {
      const roofPoints = await page.evaluate(() => {
        const {meshes, camera} = viewerCheck, V = camera.position.constructor;
        const rect = document.querySelector('canvas').getBoundingClientRect();
        return meshes.filter(m => m.userData.kind === 'context' && m.userData.metadata.surface_type === 'Roof').map(m => {
          const center = m.userData.vertices.reduce((v, p) => v.add(new V(...p)), new V()).divideScalar(m.userData.vertices.length);
          const distance = center.distanceTo(camera.position), p = center.project(camera);
          return {name: m.userData.name, x: rect.x + (p.x + 1) * rect.width / 2, y: rect.y + (1 - p.y) * rect.height / 2, distance};
        }).sort((a, b) => a.distance - b.distance);
      });
      let selectedCap = false;
      for (const point of roofPoints) {
        await page.mouse.click(point.x, point.y);
        if (await page.$eval('#objects', el => el.value) === point.name) {selectedCap = true; break;}
      }
      assert.ok(selectedCap, 'A context roof above the target cut must remain selectable');
    }
    await page.click('#context');
    assert.equal(await page.evaluate(() => viewerCheck.meshes.filter(m => m.userData.kind === 'context' && m.visible).length), 0);
    await page.click('#context');
    // Camera controls must give distinct building and neighbourhood scales.
    await page.click('#reset');
    const near = await page.evaluate(() => viewerCheck.camera.position.length());
    await page.click('#fit-context');
    assert.notEqual(await page.evaluate(() => viewerCheck.camera.position.length()), near);
    checks.push({preset, ...original, ...cut, status: 'passed'});
    console.log(`${preset}: roof caps, cutaway, storey isolation, context toggle and camera checks passed`);
  }
  assert.deepEqual(errors, []);
  await mkdir(resolve(root, 'output/validation'), {recursive: true});
  await writeFile(resolve(root, 'output/validation/viewer-checks.json'), JSON.stringify({checks, page_errors: errors}, null, 2));
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
