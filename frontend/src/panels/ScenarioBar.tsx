import { useEffect, useState } from "react";
import { useStore } from "../store";

export function ScenarioBar() {
  const { scenarios, parcel, result, refreshScenarios, save, load, remove } = useStore();
  const [name, setName] = useState("");

  useEffect(() => { refreshScenarios(); }, [refreshScenarios]);

  return (
    <div className="section" style={{ marginTop: 18 }}>
      <h2>Scenarios</h2>
      <div className="row">
        <input
          type="text" placeholder="name…" value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ flex: 2, padding: "4px 6px", border: "1px solid var(--line)", borderRadius: 5 }}
        />
        <button className="ghost" disabled={!result || !parcel} onClick={() => save(name)}>Save</button>
      </div>
      <div style={{ marginTop: 8 }}>
        {scenarios.length === 0 && <div className="note">no saved scenarios</div>}
        {scenarios.map((s) => (
          <div className="scenario-row" key={`${s.deal_id}/${s.scenario_id}`}>
            <div>
              <div>{s.name ?? s.deal_id}</div>
              <div className="meta">
                {s.scenario_id} · {s.total_wells ?? 0}w
                {s.total_completed_ft != null && <> · {(s.total_completed_ft / 1000).toFixed(0)}k ft</>}
              </div>
            </div>
            <div className="row" style={{ flex: "0 0 auto" }}>
              <button className="ghost" onClick={() => load(s.deal_id, s.scenario_id)}>Load</button>
              <button className="ghost" onClick={() => remove(s.deal_id, s.scenario_id)}>✕</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
