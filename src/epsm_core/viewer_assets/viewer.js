/*
 * File: viewer_assets/viewer.js
 * Purpose: Load an offline scene and mount the browser geometry viewer.
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
 *   2026-09-11 - Add the standard documentation header for the browser entry point.
 */

import { mountViewer } from './renderer.js';
try {
  const response = await fetch('./model.json');
  if (!response.ok) throw new Error(`Scene HTTP ${response.status}`);
  const dispose = mountViewer(document, await response.json());
  window.addEventListener('pagehide', dispose, { once: true });
} catch (error) {
  document.getElementById('status').textContent = 'Viewer failed: ' + error.message;
}
