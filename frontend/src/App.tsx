import { MapView } from "./MapView";
import { GunBarrel } from "./panels/GunBarrel";
import { ParamsPanel } from "./panels/ParamsPanel";
import { ScenarioBar } from "./panels/ScenarioBar";

export default function App() {
  return (
    <div className="app">
      <div className="sidebar">
        <h1>narvi</h1>
        <p className="sub">inventory planning</p>
        <ParamsPanel />
        <ScenarioBar />
      </div>
      <div className="map-wrap">
        <MapView />
        <GunBarrel />
      </div>
    </div>
  );
}
