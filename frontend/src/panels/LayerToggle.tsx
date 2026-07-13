// Floating map control to show/hide the Texas/NM survey grid (blocks + sections).
// The overlays are zoom-gated in gridLayers.ts (blocks z8, sections z11), so they
// only draw once the map is zoomed into the survey grid.
import { useStore } from "../store";

export function LayerToggle() {
  const showBlocks = useStore((s) => s.showBlocks);
  const showSections = useStore((s) => s.showSections);
  const showPdpWells = useStore((s) => s.showPdpWells);
  const supportColor = useStore((s) => s.supportColor);
  const setShowBlocks = useStore((s) => s.setShowBlocks);
  const setShowSections = useStore((s) => s.setShowSections);
  const setShowPdpWells = useStore((s) => s.setShowPdpWells);
  const setSupportColor = useStore((s) => s.setSupportColor);

  return (
    <div className="map-layers">
      <h3>Wells</h3>
      <label>
        <input type="checkbox" checked={showPdpWells} onChange={(e) => setShowPdpWells(e.target.checked)} />
        PDP producers
      </label>
      <label title="Color remaining PUD/RES by offset-PDP support (0=red…8+=green) and dim unsupported sticks.">
        <input type="checkbox" checked={supportColor} onChange={(e) => setSupportColor(e.target.checked)} />
        Color by PDP support
      </label>
      <h3>Survey grid</h3>
      <label>
        <input type="checkbox" checked={showBlocks} onChange={(e) => setShowBlocks(e.target.checked)} />
        Blocks
      </label>
      <label>
        <input type="checkbox" checked={showSections} onChange={(e) => setShowSections(e.target.checked)} />
        Sections
      </label>
    </div>
  );
}
