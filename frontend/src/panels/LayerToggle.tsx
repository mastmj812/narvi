// Floating map control to show/hide the Texas/NM survey grid (blocks + sections).
// The overlays are zoom-gated in gridLayers.ts (blocks z8, sections z11), so they
// only draw once the map is zoomed into the survey grid.
import { useStore } from "../store";

export function LayerToggle() {
  const showBlocks = useStore((s) => s.showBlocks);
  const showSections = useStore((s) => s.showSections);
  const setShowBlocks = useStore((s) => s.setShowBlocks);
  const setShowSections = useStore((s) => s.setShowSections);

  return (
    <div className="map-layers">
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
