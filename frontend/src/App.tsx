import { MapView } from "./MapView";
import { GunBarrel } from "./panels/GunBarrel";
import { LayerToggle } from "./panels/LayerToggle";
import { PlanPanel } from "./panels/PlanPanel";
import { ScenarioBar } from "./panels/ScenarioBar";

export default function App() {
  return (
    <div className="app">
      <div className="sidebar">
        <h1>narvi</h1>
        <p className="sub">inventory planning</p>
        <PlanPanel />
        <ScenarioBar />
      </div>
      <div className="map-wrap">
        <MapView />
        <LayerToggle />
        <GunBarrel />
      </div>
    </div>
  );
}
