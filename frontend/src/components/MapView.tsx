import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export interface MapMarker { id: string | number; lat: number; lon: number; label?: string; stale?: boolean; selected?: boolean }

const DEFAULT_CENTER: [number, number] = [-4.0, 22.0]; // centre approximatif de la RDC

function busIcon(stale?: boolean, selected?: boolean) {
  const color = stale ? "#94a3b8" : "#1d4ed8";
  const ring = selected ? "box-shadow:0 0 0 4px rgba(29,78,216,.35);" : "";
  return L.divIcon({
    className: "",
    iconSize: [26, 26],
    iconAnchor: [13, 13],
    html: `<div style="width:26px;height:26px;border-radius:50%;background:${color};border:3px solid #fff;${ring}box-shadow:0 1px 4px rgba(0,0,0,.45);display:grid;place-items:center;color:#fff;font:700 12px sans-serif">▲</div>`,
  });
}

/** Carte Leaflet (tuiles OpenStreetMap) : marqueurs de bus + tracé. Composant contrôlé par ses props. */
export default function MapView({ markers, trail, height = 420, onSelect, fitKey }: {
  markers: MapMarker[]; trail?: [number, number][]; height?: number | string; onSelect?: (id: string | number) => void; fitKey?: string | number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const lastFit = useRef<string | number | undefined>(undefined);

  useEffect(() => {
    if (!el.current || map.current) return;
    map.current = L.map(el.current, { zoomControl: true, attributionControl: true }).setView(DEFAULT_CENTER, 5);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 18, attribution: "© OpenStreetMap" }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    lastFit.current = undefined; // nouvelle carte : elle doit se recadrer (remontage React en développement)
    return () => { map.current?.remove(); map.current = null; };
  }, []);

  useEffect(() => {
    const m = map.current, g = layer.current;
    if (!m || !g) return;
    g.clearLayers();
    const bounds: L.LatLngExpression[] = [];
    if (trail && trail.length > 1) {
      L.polyline(trail, { color: "#1d4ed8", weight: 4, opacity: 0.75 }).addTo(g);
      bounds.push(...trail);
    }
    for (const mk of markers) {
      const marker = L.marker([mk.lat, mk.lon], { icon: busIcon(mk.stale, mk.selected), title: mk.label }).addTo(g);
      if (mk.label) marker.bindTooltip(mk.label, { direction: "top", offset: [0, -12] });
      if (onSelect) marker.on("click", () => onSelect(mk.id));
      bounds.push([mk.lat, mk.lon]);
    }
    // On recadre à chaque changement de `fitKey` (ex. autre bus choisi), pas à chaque rafraîchissement : l'utilisateur garde son zoom.
    if (bounds.length && lastFit.current !== fitKey) {
      lastFit.current = fitKey;
      m.invalidateSize();   // la carte peut être montée avant que son conteneur ait sa taille définitive
      m.fitBounds(L.latLngBounds(bounds), { padding: [40, 40], maxZoom: 15, animate: false });
    }
  }, [markers, trail, onSelect, fitKey]);

  return <div ref={el} style={{ height, width: "100%", borderRadius: 10, overflow: "hidden", border: "1px solid #e2e8f0" }} role="application" aria-label="Carte" />;
}
