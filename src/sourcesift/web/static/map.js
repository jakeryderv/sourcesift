// A small slippy map: tiles from this server, drag to pan, buttons and keys to zoom.
import { el, formatValue } from "/chart.js";

const TILE = 256;
const RADAR_MAX_ZOOM = 7;
const MIN_ZOOM = 2;
const MAX_ZOOM = 12;

function project(latitude, longitude, zoom) {
  const size = TILE * 2 ** zoom;
  const sin = Math.sin((latitude * Math.PI) / 180);
  return {
    x: ((longitude + 180) / 360) * size,
    y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * size,
  };
}

export function renderMap(container, view, loadTile) {
  container.replaceChildren();
  const frame = el("div", { class: "map", tabindex: "0", role: "application", "aria-label": `${view.title}. Map; drag or use arrow keys to move, plus and minus to zoom.` });
  const base = el("div", { class: "map-layer" });
  const radar = el("div", { class: "map-layer map-radar" });
  const pins = el("div", { class: "map-layer" });
  const controls = el("div", { class: "map-controls" });
  const zoomIn = el("button", { type: "button", "aria-label": "Zoom in" }, "+");
  const zoomOut = el("button", { type: "button", "aria-label": "Zoom out" }, "−");
  controls.append(zoomIn, zoomOut);
  const credit = el("div", { class: "map-credit" }, view.overlay === "radar" ? "Map © OpenStreetMap contributors · Radar by RainViewer" : "Map © OpenStreetMap contributors");
  frame.append(base, radar, pins, controls, credit);
  container.append(frame);

  // The same places as text, so nothing depends on seeing the map.
  const list = el("ul", { class: "map-list" });
  for (const marker of view.markers) {
    const value = marker.value === null ? "" : ` — ${formatValue(marker.value, marker.unit)}`;
    list.append(el("li", {}, `${marker.label}${value} (${marker.latitude.toFixed(2)}, ${marker.longitude.toFixed(2)})`));
  }
  container.append(list);

  let zoom = view.zoom;
  let center = project(view.latitude, view.longitude, zoom);
  const layers = [
    { node: base, name: "base", tiles: new Map(), zoomFor: (z) => z },
    ...(view.overlay === "radar" ? [{ node: radar, name: "radar", tiles: new Map(), zoomFor: (z) => Math.min(z, RADAR_MAX_ZOOM) }] : []),
  ];

  function clear(layer) {
    for (const image of layer.tiles.values()) { if (image.src) URL.revokeObjectURL(image.src); image.remove(); }
    layer.tiles.clear();
  }

  function layout() {
    const width = frame.clientWidth;
    const height = frame.clientHeight;
    const left = center.x - width / 2;
    const top = center.y - height / 2;
    for (const layer of layers) {
      const tileZoom = layer.zoomFor(zoom);
      const size = TILE * 2 ** (zoom - tileZoom);
      const count = 2 ** tileZoom;
      const wanted = new Set();
      for (let tx = Math.floor(left / size); tx * size < left + width; tx += 1) {
        for (let ty = Math.floor(top / size); ty * size < top + height; ty += 1) {
          if (ty < 0 || ty >= count) continue;
          const key = `${tileZoom}/${tx}/${ty}`;
          wanted.add(key);
          let image = layer.tiles.get(key);
          if (!image) {
            image = el("img", { alt: "", draggable: "false" });
            layer.tiles.set(key, image);
            layer.node.append(image);
            const wrapped = ((tx % count) + count) % count;
            loadTile(layer.name, tileZoom, wrapped, ty).then((url) => {
              if (layer.tiles.get(key) === image) image.src = url; else URL.revokeObjectURL(url);
            }, () => { /* a missing tile leaves a gap */ });
          }
          image.style.width = `${size}px`;
          image.style.height = `${size}px`;
          image.style.transform = `translate(${Math.round(tx * size - left)}px, ${Math.round(ty * size - top)}px)`;
        }
      }
      for (const [key, image] of layer.tiles) {
        if (wanted.has(key)) continue;
        if (image.src) URL.revokeObjectURL(image.src);
        image.remove();
        layer.tiles.delete(key);
      }
    }
    pins.replaceChildren();
    for (const marker of view.markers) {
      const at = project(marker.latitude, marker.longitude, zoom);
      const pin = el("div", { class: "map-pin" });
      const text = marker.value === null ? marker.label : `${marker.label} · ${formatValue(marker.value, marker.unit)}`;
      pin.append(el("span", { class: "map-dot" }), el("span", { class: "map-label" }, text));
      pin.style.transform = `translate(${Math.round(at.x - left)}px, ${Math.round(at.y - top)}px)`;
      pins.append(pin);
    }
    zoomIn.disabled = zoom >= MAX_ZOOM;
    zoomOut.disabled = zoom <= MIN_ZOOM;
  }

  function setZoom(next) {
    const clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, next));
    if (clamped === zoom) return;
    const factor = 2 ** (clamped - zoom);
    center = { x: center.x * factor, y: center.y * factor };
    zoom = clamped;
    layers.forEach(clear);
    layout();
  }
  function pan(dx, dy) {
    const size = TILE * 2 ** zoom;
    center = { x: center.x + dx, y: Math.max(0, Math.min(size, center.y + dy)) };
    layout();
  }

  zoomIn.addEventListener("click", () => setZoom(zoom + 1));
  zoomOut.addEventListener("click", () => setZoom(zoom - 1));
  let drag = null;
  frame.addEventListener("pointerdown", (event) => {
    if (event.target.closest("button")) return;
    drag = { x: event.clientX, y: event.clientY };
    frame.setPointerCapture(event.pointerId);
  });
  frame.addEventListener("pointermove", (event) => {
    if (!drag) return;
    pan(drag.x - event.clientX, drag.y - event.clientY);
    drag = { x: event.clientX, y: event.clientY };
  });
  const stop = () => { drag = null; };
  frame.addEventListener("pointerup", stop);
  frame.addEventListener("pointercancel", stop);
  frame.addEventListener("keydown", (event) => {
    const step = 60;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[event.key]) { event.preventDefault(); pan(...moves[event.key]); }
    else if (event.key === "+" || event.key === "=") setZoom(zoom + 1);
    else if (event.key === "-") setZoom(zoom - 1);
  });
  let pending = 0;
  new ResizeObserver(() => { cancelAnimationFrame(pending); pending = requestAnimationFrame(layout); }).observe(frame);
  layout();
}
