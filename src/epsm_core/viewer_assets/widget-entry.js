/*
 * File: viewer_assets/widget-entry.js
 * Purpose: Mount the shared geometry renderer inside an embedded notebook widget.
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Sanjay Somanath
 * License: MIT; see the project-root LICENSE for the full permission and warranty terms.
 * Author: Sanjay Somanath <sanjay.somanath@chalmers.se>
 * Project PI: Alexander Hollberg
 * Computational Sustainable Design Group
 * Research Area of Sustainable Built Environments
 * Chalmers University of Technology, Gothenburg
 * Date created: 2026-09-11 (documentation-header creation; not original file creation)
 * Date modified: 2026-09-11
 * Changelog:
 *   2026-09-11 - Add the standard documentation header for the notebook widget entry point.
 */

import { mountViewer } from './renderer.js';
const template = "<style>\n*{box-sizing:border-box}:host{margin:0;font:14px system-ui;color:#1c303d;background:#e9eff2}header{height:60px;background:#fff;padding:16px 24px;border-bottom:1px solid #cad5dc;display:flex;gap:22px;align-items:center}header b{font-size:21px}header span{color:#526976}main{display:grid;grid-template-columns:1fr 350px;height:calc(100% - 60px)}#scene{position:relative;min-width:0}canvas{display:block;width:100%;height:100%}aside{background:#fff;border-left:1px solid #cad5dc;overflow:auto;padding:20px}label{display:block;margin:12px 0}input[type=range],select{width:100%}fieldset{border:1px solid #d5dfe5;margin:16px 0;padding:12px}pre{font:12px ui-monospace;white-space:pre-wrap;overflow-wrap:anywhere}#legend{position:absolute;bottom:20px;left:20px;background:#fffffff0;padding:12px;border-radius:6px;pointer-events:none}#status{background:#fff3d8;padding:12px;margin:12px 0}button,select{padding:8px;border:1px solid #a8bac7;background:#fff;border-radius:4px}#details{border-top:1px solid #d5dfe5;padding-top:14px}h2{font-size:16px;margin:16px 0 8px}.muted{color:#607786}@media(max-width:800px){main{grid-template-columns:1fr 270px}aside{padding:12px}}\n</style><header><b>epsm</b><span id=\"representation\">Geometry review</span></header><main><div id=\"scene\"><div id=\"legend\">Drag to orbit \u00b7 scroll to zoom \u00b7 click to inspect<br>North: +Y \u00b7 grid: <span id=\"scale\"></span> m<br><span class=\"muted\">Blue: openings \u00b7 amber: ground \u00b7 violet: party walls</span></div></div><aside>\n<div id=\"status\">Loading geometry\u2026</div><label>Isolate storey<select id=\"storey\"><option value=\"all\">All storeys</option></select></label><label>Surface<select id=\"objects\"><option value=\"\">Select a surface</option></select></label>\n\n<!-- 4. Target-only clipping and opacity controls retain a complete context silhouette. -->\n<label><input id=\"cutaway\" type=\"checkbox\"> Building cutaway</label><label>Cut above elevation <output id=\"clip-value\"></output><input id=\"clip\" type=\"range\" step=\"0.1\" disabled></label><p class=\"muted\">Cutaway and storey isolation affect the target building. Context stays complete.</p><label>Building opacity<input id=\"opacity\" type=\"range\" min=\"0.1\" max=\"1\" step=\"0.05\" value=\"0.85\"></label>\n\n<!-- 5. Preparation and normal overlays expose geometry evidence independently of thermal detail. -->\n<fieldset><legend>Overlays</legend><label><input id=\"context\" type=\"checkbox\" checked> Context shading</label><label><input id=\"normals\" type=\"checkbox\"> Outward normals</label><label><input id=\"footprints\" type=\"checkbox\" checked> Source / cleaned footprints</label></fieldset>\n\n<!-- 6. Filter generated details without changing the underlying model or its reported quantities. -->\n<fieldset><legend>Geometry details</legend><label><input id=\"slabs\" type=\"checkbox\" checked> Floor slabs</label><label><input id=\"reveals\" type=\"checkbox\" checked> Window reveals</label><label><input id=\"overhangs\" type=\"checkbox\" checked> Overhangs</label><label><input id=\"balconies\" type=\"checkbox\" checked> Balconies</label><label><input id=\"roofs\" type=\"checkbox\" checked> Roofs</label><label><input id=\"dwellings\" type=\"checkbox\" checked> Apartment zones</label><label><input id=\"common\" type=\"checkbox\" checked> Common zones</label></fieldset><button id=\"reset\">Focus building</button> <button id=\"fit-context\">Fit context</button><div id=\"details\">Select a surface to inspect its identity and construction.</div><h2>Internal mass \u00b7 quantities only</h2><pre id=\"mass\"></pre><h2>Diagnostics and assumptions</h2><pre id=\"diagnostics\"></pre></aside></main>\n";
export function render({model, el}) {
  const host = document.createElement('div');
  host.style.cssText = 'display:block;width:100%;min-width:0';
  el.appendChild(host);
  const root = host.attachShadow({mode:'open'});
  let dispose = () => {};
  const resize = () => {host.style.height = model.get('height') + 'px';};
  const draw = () => {
    dispose(); root.innerHTML = template; resize();
    dispose = mountViewer(root, model.get('scene'), name => {
      model.set('selected_surface', name); model.save_changes();
    });
  };
  draw();
  model.on('change:scene', draw); model.on('change:height', resize);
  return () => {
    model.off('change:scene', draw); model.off('change:height', resize);
    dispose(); host.remove();
  };
}
