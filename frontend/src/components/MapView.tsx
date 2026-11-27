import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export interface MapMarker { id: string | number; lat: number; lon: number; label?: string; stale?: boolean; selected?: boolean; heading?: number | null }

const DEFAULT_CENTER: [number, number] = [-4.0, 22.0]; // centre approximatif de la RDC

// Animation « pulsation » du bus sélectionné (injectée une seule fois).
const CSS_ID = "transit-map-css";
function ensureCss() {
  if (document.getElementById(CSS_ID)) return;
  const st = document.createElement("style");
  st.id = CSS_ID;
  st.textContent = "@keyframes transit-pulse{0%{transform:scale(.8);opacity:.7}100%{transform:scale(2.4);opacity:0}}" +
    ".transit-pulse{position:absolute;inset:0;border-radius:50%;animation:transit-pulse 1.8s ease-out infinite}";
  document.head.appendChild(st);
}

function busIcon(m: MapMarker) {
  const color = m.stale ? "#94a3b8" : "#16a34a";
  const size = m.selected ? 32 : 26;
  const rot = m.heading != null ? m.heading : 0;
  const pulse = m.selected && !m.stale ? `<span class="transit-pulse" style="background:${color}"></span>` : "";
  return L.divIcon({
    className: "", iconSize: [size, size], iconAnchor: [size / 2, size / 2],
    html: `<div style="position:relative;width:${size}px;height:${size}px">${pulse}<div style="position:relative;width:${size}px;height:${size}px;border-radius:50%;background:${color};border:3px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.5);display:grid;place-items:center;color:#fff;font:700 12px sans-serif"><span style="display:block;transform:rotate(${rot}deg)">▲</span></div></div>`,
  });
}

const cursorIcon = L.divIcon({ className: "", iconSize: [18, 18], iconAnchor: [9, 9],
  html: '<div style="width:18px;height:18px;border-radius:50%;background:#f59e0b;border:3px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.5)"></div>' });

/**
 * Carte Leaflet (tuiles OpenStreetMap) : bus, tracé, curseur de rejeu. Contrôlée par ses props.
 * - `fitKey` : le changement recadre sur l'ensemble des éléments (pas à chaque rafraîchissement : l'utilisateur garde son zoom).
 * - `follow` : suit le bus sélectionné à chaque nouvelle position.
 */
export default function MapView({ markers, trail, cursor, height = 420, onSelect, fitKey, follow }: {
  markers: MapMarker[]; trail?: [number, number][]; cursor?: [number, number] | null; height?: number | string;
  onSelect?: (id: string | number) => void; fitKey?: string | number; follow?: boolean;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const cursorLayer = useRef<L.Marker | null>(null);
  const lastFit = useRef<string | number | undefined>(undefined);

  useEffect(() => {
    if (!el.current || map.current) return;
    ensureCss();
    map.current = L.map(el.current, { zoomControl: true, attributionControl: true }).setView(DEFAULT_CENTER, 5);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    lastFit.current = undefined; // nouvelle carte : elle doit se recadrer (remontage React en développement)
    return () => { map.current?.remove(); map.current = null; cursorLayer.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current, g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const bounds: L.LatLngExpression[] = [];
    if (trail && trail.length > 1) {
      L.polyline(trail, { color: "#ffffff", weight: 8, opacity: 0.9 }).addTo(g);      // liseré blanc : le tracé reste lisible sur tout fond
      L.polyline(trail, { color: "#2563eb", weight: 4, opacity: 0.95 }).addTo(g);
      L.circleMarker(trail[0], { radius: 6, color: "#fff", weight: 2, fillColor: "#0f172a", fillOpacity: 1 }).bindTooltip("Départ du suivi").addTo(g);
      bounds.push(...trail);
    }
    let selectedPos: L.LatLngExpression | null = null;
    for (const mk of markers) {
      const marker = L.marker([mk.lat, mk.lon], { icon: busIcon(mk), title: mk.label, zIndexOffset: mk.selected ? 1000 : 0 }).addTo(g);
      if (mk.label) marker.bindTooltip(mk.label, { direction: "top", offset: [0, -14] });
      if (onSelect) marker.on("click", () => onSelect(mk.id));
      bounds.push([mk.lat, mk.lon]);
      if (mk.selected) selectedPos = [mk.lat, mk.lon];
    }
    if (bounds.length && lastFit.current !== fitKey) {
      lastFit.current = fitKey;
      m.invalidateSize();   // la carte peut être montée avant que son conteneur ait sa taille définitive
      m.fitBounds(L.latLngBounds(bounds), { padding: [50, 50], maxZoom: 15, animate: true });
    } else if (follow && selectedPos) {
      m.panTo(selectedPos, { animate: true });
    }
  }, [markers, trail, onSelect, fitKey, follow]);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    if (!cursor) { cursorLayer.current?.remove(); cursorLayer.current = null; return; }
    if (!cursorLayer.current) cursorLayer.current = L.marker(cursor, { icon: cursorIcon, zIndexOffset: 2000, interactive: false }).addTo(m);
    else cursorLayer.current.setLatLng(cursor);
  }, [cursor]);

  return <div ref={el} style={{ height, width: "100%", borderRadius: 12, overflow: "hidden", border: "1px solid #e2e8f0" }} role="application" aria-label="Carte" />;
}
