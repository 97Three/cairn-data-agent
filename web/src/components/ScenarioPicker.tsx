import type { Scenario } from "../types";
import { ASSET_KIND_LABELS } from "../ui";

interface ScenarioPickerProps {
  scenarios: Scenario[];
  selectedName: string;
  onSelect: (name: string) => void;
}

function scenarioMonogram(name: string): string {
  return name
    .split("-")
    .map((part) => part[0]?.toUpperCase())
    .join("")
    .slice(0, 2);
}

export function ScenarioPicker({ scenarios, selectedName, onSelect }: ScenarioPickerProps) {
  return (
    <section className="rail-section" aria-labelledby="scenario-heading">
      <div className="section-title">
        <span>01</span>
        <div>
          <p className="eyebrow">Scenario</p>
          <h2 id="scenario-heading">选择分析场景</h2>
        </div>
      </div>
      <div className="scenario-list" role="radiogroup" aria-label="分析场景">
        {scenarios.map((scenario) => {
          const selected = scenario.name === selectedName;
          return (
            <label className={`scenario-card${selected ? " is-selected" : ""}`} key={scenario.name}>
              <input
                type="radio"
                name="scenario"
                value={scenario.name}
                checked={selected}
                onChange={() => onSelect(scenario.name)}
              />
              <span className="scenario-icon" aria-hidden="true">
                {scenarioMonogram(scenario.name)}
              </span>
              <span className="scenario-copy">
                <strong>{scenario.displayName}</strong>
                <small>{scenario.description}</small>
                <span className="chip-row">
                  {scenario.supportedAssetTypes.map((kind) => (
                    <span key={kind}>{ASSET_KIND_LABELS[kind]}</span>
                  ))}
                  <span>v{scenario.version}</span>
                </span>
              </span>
              <span className="scenario-check" aria-hidden="true">
                ✓
              </span>
            </label>
          );
        })}
      </div>
    </section>
  );
}
