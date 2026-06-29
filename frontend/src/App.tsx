import { MapView } from "./MapView";
import { CuratePanel } from "./panels/CuratePanel";
import { GunBarrel } from "./panels/GunBarrel";
import { ParamsPanel } from "./panels/ParamsPanel";
import { ScenarioBar } from "./panels/ScenarioBar";
import { useStore } from "./store";

export default function App() {
  const appMode = useStore((s) => s.appMode);
  const setAppMode = useStore((s) => s.setAppMode);

  return (
    <div className="app">
      <div className="sidebar">
        <h1>narvi</h1>
        <p className="sub">inventory planning</p>

        <div className="segmented" style={{ marginBottom: 16 }}>
          <button className={appMode === "curate" ? "active" : ""} onClick={() => setAppMode("curate")}>
            Curate
          </button>
          <button className={appMode === "override" ? "active" : ""} onClick={() => setAppMode("override")}>
            Override
          </button>
        </div>

        {appMode === "curate" ? <CuratePanel /> : <ParamsPanel />}
        <ScenarioBar />
      </div>
      <div className="map-wrap">
        <MapView />
        <GunBarrel />
      </div>
    </div>
  );
}
