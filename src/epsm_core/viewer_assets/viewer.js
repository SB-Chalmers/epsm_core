import { mountViewer } from './renderer.js';
try {
  const response = await fetch('./model.json');
  if (!response.ok) throw new Error(`Scene HTTP ${response.status}`);
  const dispose = mountViewer(document, await response.json());
  window.addEventListener('pagehide', dispose, { once: true });
} catch (error) {
  document.getElementById('status').textContent = 'Viewer failed: ' + error.message;
}
