/*
 * File: viewer_assets/renderer.js
 * Purpose: Inspect resolved geometry and simulation evidence using local Three.js assets.
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Sanjay Somanath
 * License: MIT; see the project-root LICENSE for full permission and warranty terms.
 * Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
 * Project PI: Alexander Hollberg
 * Computational Sustainable Design Group
 * Research Area of Sustainable Built Environments
 * Chalmers University of Technology, Gothenburg
 * Date created: 2026-09-06 (documentation-header creation; not original file creation)
 * Date modified: 2026-09-11
 * Changelog:
 *   2026-09-11 - Correct the shared renderer filename in the documentation header.
 *   2026-09-06 - Document scene setup, transforms, controls and inspection helpers.
 */

/**
 * @file Offline geometry viewer entry point, loaded as an ES module by index.html.
 * @example
 * // Generate and serve the bundle from Python with an existing epJSON file:
 * // with view_epjson('output/run/model.epJSON', launch_browser=False) as handle:
 * //     print(handle.url)
 * // Open that URL while the handle remains active, then select a surface.
 * @note Requires the bundled HTML controls, WebGL, ResizeObserver and model.json
 * emitted by viewer_data. Serve through the Python loopback viewer; file:// loading
 * is not the supported fetch/import workflow. This code does not run EnergyPlus.
 */

import * as THREE from 'three';
import { OrbitControls } from './OrbitControls.js';
/**
 * Look up a required viewer control by its stable HTML ID.
 * @param {string} id ID defined by index.html.
 * @returns {HTMLElement|null} Matching element; callers rely on the bundled DOM contract.
 * @example $('status').textContent = 'Ready';
 */
export function mountViewer(root, data, onSelect = () => {}) {
const $ = id => root.querySelector('#' + id);
let dispose = () => {};
try {
  // 2. Establish a metric +Z-up scene and a bounded pixel ratio for predictable rendering cost.
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#e9eff2');
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.localClippingEnabled = true;
  $('scene').appendChild(renderer.domElement);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 100000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(16777215, 7832972, 2));
  const light = new THREE.DirectionalLight(16777215, 2);
  light.position.set(40, -30, 70);
  scene.add(light);
  const plane = new THREE.Plane(new THREE.Vector3(0, 0, -1), 10000);
  const meshes = [], normalGroup = new THREE.Group(), footprints = new THREE.Group();
  scene.add(normalGroup, footprints);
  normalGroup.visible = false;
  const byName = new Map();
  // 3. Keep each thermal/shading identity on its mesh for inspection and filter decisions.
  for (const obj of data.objects) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(obj.triangles, 3));
    geometry.computeVertexNormals();
    const color = obj.kind === 'opening' ? 2587823 : obj.kind === 'context' ? obj.metadata.surface_type === 'Roof' ? 12108486 : 10990005 : obj.boundary === 'Ground' ? 12226892 : obj.boundary === 'Adiabatic' ? 10254771 : obj.epjson.surface_type === 'Roof' ? 8625576 : 14800315;
    const clipPlanes = obj.kind === 'context' ? [] : [plane];
    const material = new THREE.MeshStandardMaterial({
      color,
      side: THREE.DoubleSide,
      transparent: obj.kind !== 'context',
      opacity: obj.kind === 'context' ? 1 : obj.kind === 'opening' ? 0.55 : 0.85,
      clippingPlanes: clipPlanes,
      roughness: 0.8
    });
    const mesh = new THREE.Mesh(geometry, material);
    mesh.userData = obj;
    scene.add(mesh);
    meshes.push(mesh);
    byName.set(obj.name, mesh);
    const lines = new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 10), new THREE.LineBasicMaterial({
      color: 6780801,
      transparent: true,
      opacity: 0.4,
      clippingPlanes: clipPlanes
    }));
    mesh.add(lines);
    const center = new THREE.Vector3();
    obj.vertices.forEach(v => center.add(new THREE.Vector3(...v)));
    center.divideScalar(obj.vertices.length);
    normalGroup.add(new THREE.ArrowHelper(new THREE.Vector3(...obj.normal), center, 1, 13322555));
    const option = document.createElement('option');
    option.value = obj.name;
    option.textContent = obj.name;
    $('objects').appendChild(option);
  }
  // 4. Track target and full-context bounds separately so each focus action has a clear extent.
  const box = new THREE.Box3(), contextBox = new THREE.Box3();
  for (const mesh of meshes) {
    contextBox.expandByObject(mesh);
    if (mesh.userData.kind !== 'context')
      box.expandByObject(mesh);
  }
  const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3()), span = Math.max(size.x, size.y, size.z, 1);
  const step = 10 ** Math.floor(Math.log10(span / 5));
  $('scale').textContent = step;
  const grid = new THREE.GridHelper(step * 20, 20, 10333107, 13424348);
  grid.rotation.x = Math.PI / 2;
  grid.position.set(center.x, center.y, box.min.z - 0.05);
  scene.add(grid);
  scene.add(new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), new THREE.Vector3(box.min.x - span * 0.1, box.min.y, 0), span * 0.2, 3042445));
  /**
   * Fit all eight corners of a world-space box into the perspective viewport.
   * The view direction stays diagonal with +Z up. Projecting corners onto camera
   * axes handles both wide and tall viewports; eight-percent padding retains edges.
   * @param {THREE.Box3} bounds Nonempty target or context bounds, in metres.
   * @returns {void} Mutates camera, clipping distances and the orbit target.
   * @example fit(box); // Focus the target building.
   * @example fit(contextBox); // Include surrounding shading objects.
   */
  function fit(bounds) {
    const midpoint = bounds.getCenter(new THREE.Vector3()), direction = new THREE.Vector3(1, -1, 0.9).normalize();
    const right = new THREE.Vector3().crossVectors(camera.up, direction).normalize(), up = new THREE.Vector3().crossVectors(direction, right);
    const tanVertical = Math.tan(camera.fov * Math.PI / 360), tanHorizontal = tanVertical * camera.aspect;
    let distance = 1;
    for (const x of [
        bounds.min.x,
        bounds.max.x
      ])
      for (const y of [
          bounds.min.y,
          bounds.max.y
        ])
        for (const z of [
            bounds.min.z,
            bounds.max.z
          ]) {
          const corner = new THREE.Vector3(x, y, z).sub(midpoint);
          distance = Math.max(distance, corner.dot(direction) + Math.max(Math.abs(corner.dot(right)) / tanHorizontal, Math.abs(corner.dot(up)) / tanVertical));
        }
    distance *= 1.08;
    controls.target.copy(midpoint);
    camera.position.copy(midpoint).add(direction.multiplyScalar(distance));
    camera.near = distance / 10000;
    camera.far = Math.max(distance, contextBox.getSize(new THREE.Vector3()).length()) * 100;
    camera.updateProjectionMatrix();
    controls.update();
  }
  const hasContext = meshes.some(m => m.userData.kind === 'context');
  $('reset').onclick = () => fit(box);
  $('fit-context').onclick = () => fit(contextBox);
  $('fit-context').disabled = !hasContext;
  $('clip').min = box.min.z - 1;
  $('clip').max = box.max.z + 1;
  $('clip').value = box.max.z + 1;
  /**
   * Add an always-visible diagnostic polyline to a scene group.
   * @param {Array<Array<number>>} points World-space metric vertex triples.
   * @param {number} color Three.js hexadecimal colour.
   * @param {THREE.Group} group Overlay owner whose visibility controls this line.
   * @returns {void} Allocates geometry/material and appends a child to group.
   * @example line([[0, 0, 0.02], [2, 0, 0.02]], 0xff9400, footprints);
   * @note depthTest=false keeps preparation evidence visible through model meshes.
   */
  function line(points, color, group) {
    const geometry = new THREE.BufferGeometry().setFromPoints(points.map(p => new THREE.Vector3(...p)));
    group.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({
      color,
      depthTest: false
    })));
  }
  // 5. Overlay preparation evidence in the same translated/rotated frame as the building.
  const preparation = data.preparation;
  /**
   * Translate a source footprint point and apply the reported clockwise rotation.
   * @param {Array<number>} point Source-frame [x, y] coordinates in metres.
   * @returns {Array<number>} World [x, y, z], raised 0.02 m for overlay visibility.
   * @example toLocal([100, 200]);
   * @note Missing report origin/orientation defaults to the identity transform.
   * This helper does not perform a CRS conversion.
   */
  const toLocal = ([x, y]) => {
    const origin = data.report.origin_m || [
        0,
        0
      ], angle = -(data.report.orientation_deg || 0) * Math.PI / 180;
    const a = x - origin[0], b = y - origin[1];
    return [
      a * Math.cos(angle) - b * Math.sin(angle),
      a * Math.sin(angle) + b * Math.cos(angle),
      0.02
    ];
  };
  /**
   * Draw exterior and courtyard rings of a preparation GeoJSON geometry.
   * @param {Object|null} g Polygon or MultiPolygon in the source metric frame.
   * @param {number} color Three.js hexadecimal colour for all rings.
   * @returns {void} Appends lines to footprints; missing/unsupported geometry adds none.
   * @example drawFootprint(preparation.source_geometry, 0xcf554c);
   * @note Source and cleaned outlines are evidence overlays, not thermal surfaces.
   */
  function drawFootprint(g, color) {
    if (!g)
      return;
    let ps = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
    const origin = data.report.origin_m || [
      0,
      0
    ];
    for (const p of ps)
      for (const ring of p)
        line(ring.map(toLocal), color, footprints);
  }
  if (preparation) {
    drawFootprint(preparation.source_geometry, 13587788);
    drawFootprint(preparation.cleaned_geometry, 2592103);
    for (const edge of preparation.edge_lineage || [])
      if (edge.changed)
        line([
          toLocal(edge.start),
          toLocal(edge.end)
        ], 16749568, footprints);
  } else {
    $('footprints').disabled = true;
  }
  // 6. Derive available storeys from actual payload metadata, including basement/attic indices.
  const storeys = [...new Set(data.objects.map(o => o.metadata.storey).filter(v => v !== undefined))].sort((a, b) => a - b);
  for (const v of storeys) {
    const o = document.createElement('option');
    o.value = v;
    o.textContent = `Storey ${ v }`;
    $('storey').appendChild(o);
  }
  /**
   * Evaluate geometry-detail toggles for one render object.
   * @param {Object} o Record emitted by Python viewer_data, with kind/epjson/metadata.
   * @returns {boolean} Whether its geometry category is enabled.
   * @example detailVisible(meshes[0].userData);
   * @note Storey filtering and cutaway clipping are handled separately by update.
   * Context has its own toggle and is kept complete during target isolation.
   */
  function detailVisible(o) {
    if (o.kind === 'context')
      return $('context').checked;
    const group = {
      reveal: 'reveals',
      overhang: 'overhangs',
      balcony: 'balconies',
      slab_visual: 'slabs'
    }[o.kind];
    if (group && !$(group).checked)
      return false;
    if ([
        'Floor',
        'Ceiling'
      ].includes(o.epjson.surface_type) && !$('slabs').checked)
      return false;
    if (o.epjson.surface_type === 'Roof' && !$('roofs').checked)
      return false;
    if (o.metadata.zone_kind === 'dwelling' && !$('dwellings').checked)
      return false;
    if ([
        'common',
        'stairwell'
      ].includes(o.metadata.zone_kind) && !$('common').checked)
      return false;
    return true;
  }
  /**
   * Synchronize mesh visibility, opacity, clipping and overlays from DOM controls.
   * @returns {void} Mutates renderer/material/group state and the elevation readout.
   * @example $('cutaway').checked = true; update();
   * @note Clipping and storey isolation affect the target only. Normal arrows and
   * footprint evidence are independent overlays controlled by their own toggles.
   */
  function update() {
    const cutaway = $('cutaway').checked;
    renderer.localClippingEnabled = cutaway;
    plane.constant = +$('clip').value;
    $('clip').disabled = !cutaway;
    $('clip-value').textContent = `${ plane.constant.toFixed(1) } m`;
    for (const m of meshes) {
      m.visible = detailVisible(m.userData) && (m.userData.kind === 'context' || $('storey').value === 'all' || String(m.userData.metadata.storey) === $('storey').value);
      m.material.opacity = m.userData.kind === 'context' ? 1 : +$('opacity').value * (m.userData.kind === 'opening' ? 0.65 : 1);
    }
    normalGroup.visible = $('normals').checked;
    footprints.visible = $('footprints').checked;
  }
  // 7. Route control changes through one visibility update to keep filters consistent.
  for (const id of [
      'cutaway',
      'clip',
      'opacity',
      'context',
      'normals',
      'footprints',
      'storey',
      'slabs',
      'reveals',
      'overhangs',
      'balconies',
      'roofs',
      'dwellings',
      'common'
    ])
    $(id).oninput = update;
  update();
  /**
   * Highlight a mesh and display its original geometry and construction evidence.
   * @param {THREE.Mesh} mesh Render mesh whose userData contains the viewer payload.
   * @returns {void} Updates emissive highlights, selection control and details DOM.
   * @example select(meshes[0]);
   * @note Uses textContent for source values so object names/metadata remain text.
   */
  function select(mesh) {
    for (const m of meshes)
      m.material.emissive.setHex(m === mesh ? 3231064 : 0);
    const o = mesh.userData;
    $('objects').value = o.name;
    onSelect(o.name);
    $('details').replaceChildren();
    const title = document.createElement('h2');
    title.textContent = o.name;
    $('details').appendChild(title);
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify({
      kind: o.kind,
      parent: o.parent,
      ...o.metadata,
      boundary: o.boundary,
      zone: o.zone,
      area_m2: o.area_m2,
      net_area_m2: o.net_area_m2,
      construction: o.construction_name,
      layers: o.layers,
      nominal_u_w_m2k: o.construction_report.nominal_u_w_m2k,
      applied_u_w_m2k: o.construction_report.applied_u_w_m2k,
      epjson: o.epjson
    }, null, 2);
    $('details').appendChild(pre);
  }
  $('objects').onchange = () => {
    const m = byName.get($('objects').value);
    if (m)
      select(m);
  };
  // 8. Pick only visible, unclipped objects; GPU clipping alone does not constrain raycasting.
  const ray = new THREE.Raycaster();
  renderer.domElement.addEventListener('click', event => {
    const r = renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2((event.clientX - r.left) / r.width * 2 - 1, -(event.clientY - r.top) / r.height * 2 + 1), camera);
    const hit = ray.intersectObjects(meshes, false).find(h => h.object.visible && (!renderer.localClippingEnabled || h.object.userData.kind === 'context' || h.point.z <= plane.constant));
    if (hit)
      select(hit.object);
  });
  // 9. Display source diagnostics and assumptions without interpreting a preview as simulation success.
  $('mass').textContent = Object.keys(data.internal_mass).length ? JSON.stringify(data.internal_mass, null, 2) : 'No InternalMass objects.';
  const annotations = [...new Set(data.objects.flatMap(o => o.metadata.annotations || []))];
  $('diagnostics').textContent = JSON.stringify({
    assumptions: annotations,
    approximations: data.report.approximations || [],
    layout: data.report.layout || {},
    zoning: data.report.zoning || {},
    context: data.report.context || {},
    facades: data.report.facades || [],
    simulation: data.diagnostics
  }, null, 2);
  $('representation').textContent = data.report.geometry_only ? 'Geometry review \xB7 resolved surfaces' : 'Geometry review \xB7 actual epJSON surfaces';
  $('status').textContent = `${ meshes.length } ${ data.report.geometry_only ? 'geometry' : 'epJSON' } objects · ${ data.diagnostics.accepted === false ? 'simulation rejected' : data.diagnostics.accepted === true ? 'diagnostics accepted' : 'preview \xB7 simulation not run' }`;
  /**
   * Match renderer size and perspective aspect to the scene's current CSS bounds.
   * @returns {void} Updates renderer dimensions and the camera projection matrix.
   * @example resize(); // Also called by ResizeObserver after layout changes.
   * @note The bundled layout must provide a nonzero viewport height.
   */
  const resize = () => {
    const rect = $('scene').getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    renderer.setSize(rect.width, rect.height);
    camera.aspect = rect.width / rect.height;
    camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize);
  observer.observe($('scene'));
  dispose = () => {
    observer.disconnect();
    renderer.setAnimationLoop(null);
    controls.dispose();
    scene.traverse(object => {
      object.geometry?.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.filter(Boolean).forEach(material => material.dispose());
    });
    renderer.dispose();
    renderer.forceContextLoss();
  };
  resize();
  fit(hasContext ? contextBox : box);
  // 10. Advance orbit damping before rendering each frame; geometry remains unchanged.
  renderer.setAnimationLoop(() => {
    controls.update();
    renderer.render(scene, camera);
  });
} catch (error) {
  // NOTE: Retain a visible failure message when loading or rendering cannot complete.
  $('status').textContent = 'Viewer failed: ' + error.message;
  console.error(error);
}

return () => { dispose(); root.replaceChildren(); };
}
