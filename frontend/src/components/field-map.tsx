"use client";

import { useEffect } from "react";
import L from "leaflet";
import {
  MapContainer,
  Marker,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";

export type MapPoint = [number, number];

interface FieldMapProps {
  point: MapPoint;
  onSelect: (latitude: number, longitude: number) => void;
}

const markerIcon = L.divIcon({
  className: "orbitfarm-marker-shell",
  html: '<span class="orbitfarm-marker-dot"></span>',
  iconSize: [26, 26],
  iconAnchor: [13, 13],
});

function MapViewport({ point }: { point: MapPoint }) {
  const map = useMap();

  useEffect(() => {
    map.setView(point, map.getZoom(), { animate: false });
    map.invalidateSize({ pan: false });
  }, [map, point]);

  return null;
}

function MapClickHandler({ onSelect }: Pick<FieldMapProps, "onSelect">) {
  useMapEvents({
    click(event) {
      onSelect(event.latlng.lat, event.latlng.lng);
    },
  });

  return null;
}

export default function FieldMap({ point, onSelect }: FieldMapProps) {
  return (
    <div className="field-map-frame">
      <MapContainer
        center={point}
        zoom={8}
        minZoom={2}
        maxZoom={18}
        scrollWheelZoom
        zoomControl
        className="field-map"
        attributionControl
      >
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors'
          maxZoom={19}
        />
        <MapViewport point={point} />
        <MapClickHandler onSelect={onSelect} />
        <Marker position={point} icon={markerIcon} keyboard title="Выбранная точка анализа" />
      </MapContainer>
      <div className="map-caption">
        <span>Начальный центр — тестовый регион Беэр-Шевы. Геолокация пользователя не запрашивается.</span>
        <span>Нажмите на карту, чтобы выбрать точку.</span>
        <a href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noreferrer">Сообщить об ошибке карты</a>
      </div>
    </div>
  );
}
