"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, LoaderCircle, RotateCw, Sprout } from "lucide-react";
import type {
  RotationClimateContext,
  RotationCompareResponse,
  RotationFinding,
  RotationOptionsResponse,
  RotationPlan,
} from "@/lib/contracts";
import { analysisErrorText, requestJSON, stableKey } from "@/lib/analysis-session";
import { useAnalysisSession } from "@/lib/use-analysis-session";

interface RotationPlannerProps {
  climateContext: RotationClimateContext | null;
  contextStale: boolean;
  analysisScope: string;
  onResult: (value: RotationCompareResponse | null) => void;
}

type CropSequence = [string, string, string];

const initialPlanA: CropSequence = ["wheat", "chickpea", "wheat"];
const initialPlanB: CropSequence = ["wheat", "chickpea", "sorghum"];

const cropGroupNames: Record<string, string> = {
  cereal: "Зерновые",
  legume: "Бобовые",
};

const familyNames: Record<string, string> = {
  Fabaceae: "Бобовые (Fabaceae)",
  Poaceae: "Злаковые (Poaceae)",
};

function familyLabel(family: string) {
  return familyNames[family] ?? family;
}

const planLabels: Record<string, string> = {
  wheat_continuous: "ПЛАН 01",
  wheat_chickpea_wheat: "ПЛАН 02",
  wheat_chickpea_sorghum: "ПЛАН 03",
};

function findingData(finding: RotationFinding) {
  if (finding.used_data === null || finding.used_data === undefined) return "Нет данных";
  if (typeof finding.used_data === "string") return finding.used_data;
  return JSON.stringify(finding.used_data, null, 2);
}

function findingDataSummary(finding: RotationFinding, cropNames: Record<string, string>) {
  const data = finding.used_data;
  if (Array.isArray(data) && data.every((item) => typeof item === "string")) {
    return `Культуры: ${data.map((cropId) => cropNames[cropId] ?? cropId).join(", ")}`;
  }
  if (!Array.isArray(data) || !data.every((item) => item && typeof item === "object")) return "";
  return data.map((item) => {
    const record = item as Record<string, unknown>;
    const parts: string[] = [];
    if (typeof record.from_season === "number" && typeof record.to_season === "number") {
      parts.push(`Сезоны ${record.from_season} → ${record.to_season}`);
    }
    if (typeof record.crop_id === "string") parts.push(cropNames[record.crop_id] ?? record.crop_id);
    if (typeof record.next_crop_id === "string") parts.push(`следующая культура: ${cropNames[record.next_crop_id] ?? record.next_crop_id}`);
    if (typeof record.previous_crop_group === "string") {
      const group = cropGroupNames[record.previous_crop_group] ?? record.previous_crop_group;
      parts.push(`предыдущая группа: ${group.toLowerCase()}`);
    }
    if (typeof record.family === "string") parts.push(`семейство: ${familyLabel(record.family)}`);
    if (Array.isArray(record.intervening_crop_ids)) {
      const names = record.intervening_crop_ids.map((cropId) =>
        typeof cropId === "string" ? cropNames[cropId] ?? cropId : String(cropId),
      );
      parts.push(`между ними: ${names.join(", ")}`);
    }
    return parts.join(" · ");
  }).filter(Boolean).join("; ");
}

function RotationFindingList({ title, findings, emptyText, cropNames = {} }: {
  title: string;
  findings: RotationFinding[];
  emptyText: string;
  cropNames: Record<string, string>;
}) {
  return (
    <div className="rotation-finding-group">
      <h5>{title}</h5>
      {findings.length === 0 ? (
        <p className="rotation-empty-note">{emptyText}</p>
      ) : findings.map((finding, index) => (
        <article className="rotation-finding" key={`${finding.basis}-${index}`}>
          <span className={`rotation-finding-status status-${finding.status}`}>
            {finding.status === "known" ? "Данные есть" : "Неизвестно"}
          </span>
          <p>{finding.explanation}</p>
          {findingDataSummary(finding, cropNames) && (
            <p className="rotation-used-summary"><strong>Использовано:</strong> {findingDataSummary(finding, cropNames)}</p>
          )}
          <details>
            <summary>Технические данные и источник</summary>
            <pre>{findingData(finding)}</pre>
            <p>{finding.limitation}</p>
          </details>
        </article>
      ))}
    </div>
  );
}

function PlanCard({ plan, cropNames = {} }: { plan: RotationPlan; cropNames?: Record<string, string> }) {
  const indicators = plan.indicators;
  const legumeLabel = indicators.legume_presence.present === null
    ? "Неизвестно"
    : indicators.legume_presence.present
      ? `Есть · сезоны ${indicators.legume_presence.seasons?.join(", ")}`
      : "Нет";
  const diversityLabel = indicators.sequence_diversity.status === "unknown"
    ? "Неизвестно"
    : `${indicators.sequence_diversity.distinct_crop_count} разных crop_id из ${indicators.sequence_diversity.season_count}`;
  const adjacentCropRepeats = indicators.crop_repetition.adjacent_repeats;
  const cropReturns = indicators.crop_repetition.return_after_intermediate;
  const adjacentFamilyRepeats = indicators.family_repetition.adjacent_repeats;
  const familyReturns = indicators.family_repetition.return_after_intermediate;
  const adjacentFamilyLabel = adjacentFamilyRepeats === null
    ? "Неизвестно"
    : adjacentFamilyRepeats.length === 0
      ? "Не обнаружен"
      : adjacentFamilyRepeats.map((item) => `${familyLabel(item.family)}: сезоны ${item.from_season}–${item.to_season}`).join("; ");
  const cropReturnLabel = cropReturns === null
    ? "Неизвестно"
    : cropReturns.length === 0
      ? "Не обнаружен"
      : cropReturns.map((item) => `Сезоны ${item.from_season} и ${item.to_season}; между ними ${item.intervening_crop_ids.join(", ")}`).join("; ");
  const familyReturnLabel = familyReturns === null
    ? "Неизвестно"
    : familyReturns.length === 0
      ? "Не обнаружен"
      : familyReturns.map((item) => `${familyLabel(item.family)}: сезоны ${item.from_season} и ${item.to_season}`).join("; ");

  return (
    <article className="rotation-plan-card">
      <header className="rotation-plan-heading">
        <div>
          <span className="rotation-plan-id">{planLabels[plan.plan_id] ?? (plan.plan_id === "custom_a" ? "ПЛАН A" : plan.plan_id === "custom_b" ? "ПЛАН B" : "ДЕМО-ПЛАН")}</span>
          <h4>{plan.name_ru}</h4>
        </div>
        <span className="rotation-no-score">Без рейтинга</span>
      </header>

      <div className="rotation-seasons">
        {plan.seasons.map((season, index) => (
          <div className="rotation-season" key={`${season.season}-${season.crop_id}`}>
            <span className="rotation-season-number">Сезон {season.season}</span>
            <strong>{season.name_ru}</strong>
            <small>{season.crop_group ? cropGroupNames[season.crop_group] ?? season.crop_group : "Группа неизвестна"} · {season.botanical_family ? familyNames[season.botanical_family] ?? season.botanical_family : "Семейство неизвестно"}</small>
            {index < plan.seasons.length - 1 && <ArrowRight className="rotation-season-arrow" size={15} aria-hidden="true" />}
          </div>
        ))}
      </div>

      <dl className="rotation-indicators">
        <div>
          <dt>Повтор культуры подряд</dt>
          <dd>{adjacentCropRepeats === null ? "Неизвестно" : adjacentCropRepeats.length === 0 ? "Не обнаружен" : adjacentCropRepeats.map((item) => `Сезоны ${item.from_season}–${item.to_season}`).join(", ")}</dd>
        </div>
        <div>
          <dt>Возврат культуры после промежуточной</dt>
          <dd>{cropReturnLabel}</dd>
        </div>
        <div>
          <dt>Повтор семейства подряд</dt>
          <dd>{adjacentFamilyLabel}</dd>
        </div>
        <div>
          <dt>Возврат семейства после промежуточного</dt>
          <dd>{familyReturnLabel}</dd>
        </div>
        <div>
          <dt>Бобовое звено</dt>
          <dd>{legumeLabel}</dd>
        </div>
        <div>
          <dt>Разнообразие последовательности</dt>
          <dd>{diversityLabel}</dd>
        </div>
      </dl>

      <div className="rotation-findings">
        <RotationFindingList
          title="Возможные преимущества"
          findings={plan.potential_benefits}
          emptyText="Структурные преимущества по данным каталога не выявлены."
          cropNames={cropNames}
        />
        <RotationFindingList
          title="Возможные риски и замечания"
          findings={plan.potential_risks}
          emptyText="Совпадений с описанными ограничениями не выявлено; это не означает отсутствия агрономического риска."
          cropNames={cropNames}
        />
        <RotationFindingList
          title="Возвраты после промежуточного сезона"
          findings={plan.sequence_notes}
          emptyText="Возврат после промежуточного сезона не обнаружен."
          cropNames={cropNames}
        />
      </div>
      <details className="rotation-limitations">
        <summary>Ограничения интерпретации</summary>
        <ul>{plan.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
      </details>
    </article>
  );
}

interface PlanEditorProps {
  title: string;
  sequence: CropSequence;
  crops: RotationOptionsResponse["available_crops"];
  onChange: (seasonIndex: number, cropId: string) => void;
}

function PlanEditor({ title, sequence, crops, onChange }: PlanEditorProps) {
  return (
    <div className="rotation-editor-card">
      <h4>{title}</h4>
      <div className="rotation-editor-seasons">
        {sequence.map((cropId, seasonIndex) => (
          <label className="rotation-editor-field" key={seasonIndex}>
            <span>Сезон {seasonIndex + 1}</span>
            <select value={cropId} onChange={(event) => onChange(seasonIndex, event.target.value)}>
              {crops.map((crop) => (
                <option key={crop.crop_id} value={crop.crop_id}>{crop.name_ru}</option>
              ))}
            </select>
          </label>
        ))}
      </div>
    </div>
  );
}

export default function RotationPlanner({ climateContext, contextStale, analysisScope, onResult }: RotationPlannerProps) {
  const [options, setOptions] = useState<RotationOptionsResponse | null>(null);
  const [optionsError, setOptionsError] = useState("");
  const [planA, setPlanA] = useState<CropSequence>(initialPlanA);
  const [planB, setPlanB] = useState<CropSequence>(initialPlanB);
  const request = useAnalysisSession<RotationCompareResponse>(stableKey([analysisScope, climateContext, planA, planB]));
  const comparison = request.result, isLoading = request.loading;
  const errorMessage = analysisErrorText(request.error);
  const cropNames = Object.fromEntries((options?.available_crops ?? []).map((crop) => [crop.crop_id, crop.name_ru]));

  useEffect(() => {
    let active = true;
    requestJSON<RotationOptionsResponse>("/api/rotation/options")
      .then(({ value }) => {
        if (active) setOptions(value);
      })
      .catch((error: unknown) => {
        if (active && !(error instanceof DOMException && error.name === "AbortError")) {
          setOptionsError(error instanceof Error ? error.message : "Не удалось загрузить каталог культур.");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  function updateSequence(setSequence: (update: (current: CropSequence) => CropSequence) => void, seasonIndex: number, cropId: string) {
    request.reset(); onResult(null);
    setSequence((current) => current.map((value, index) => index === seasonIndex ? cropId : value) as CropSequence);
  }

  async function compare(includeCustomPlans: boolean) {
    onResult(null);
      const body: { climate_context: RotationClimateContext | null; plans?: Array<{ plan_id: string; crop_ids: string[] }> } = {
        climate_context: climateContext,
      };
      if (includeCustomPlans) {
        body.plans = [
          { plan_id: "custom_a", crop_ids: planA },
          { plan_id: "custom_b", crop_ids: planB },
        ];
      }
    const value = await request.run(() => requestJSON<RotationCompareResponse>("/api/rotation/compare", body));
    if (value) onResult(value);
  }

  return (
    <section className="rotation-section" id="rotation-planner">
      <div className="rotation-section-header">
        <div>
          <p className="eyebrow">03 · СЕВООБОРОТ</p>
          <h2>Планирование севооборота</h2>
          <p>Соберите два плана по три сезона или откройте демонстрационные примеры.</p>
        </div>
      </div>

      <div className="rotation-truth-note">
        <Sprout size={18} />
        <p><strong>Без прогноза и бонусных баллов</strong><span>Показываются только повторы подряд, возвраты после промежуточного сезона, семейства, бобовое звено и разнообразие. Урожайность, азотный эффект и устойчивость не рассчитываются.</span></p>
      </div>

      {options ? (
        <div className="rotation-builder">
          <div className="rotation-editor-grid">
            <PlanEditor
              title="План A"
              sequence={planA}
              crops={options.available_crops}
              onChange={(season, cropId) => updateSequence(setPlanA, season, cropId)}
            />
            <PlanEditor
              title="План B"
              sequence={planB}
              crops={options.available_crops}
              onChange={(season, cropId) => updateSequence(setPlanB, season, cropId)}
            />
          </div>

          <details className="rotation-examples">
            <summary>Три демонстрационных примера</summary>
            <div className="rotation-example-list">
              {options.example_plans.map((example) => {
                const sequenceName = example.crop_ids.map((cropId) =>
                  options.available_crops.find((crop) => crop.crop_id === cropId)?.name_ru ?? cropId,
                ).join(" → ");
                return (
                  <article className="rotation-example" key={example.plan_id}>
                    <div><strong>{example.name_ru}</strong><small>{sequenceName}</small></div>
                    <div className="rotation-example-actions">
                      <button type="button" onClick={() => { request.reset(); onResult(null); setPlanA([...example.crop_ids] as CropSequence); }}>В план A</button>
                      <button type="button" onClick={() => { request.reset(); onResult(null); setPlanB([...example.crop_ids] as CropSequence); }}>В план B</button>
                    </div>
                  </article>
                );
              })}
            </div>
          </details>

          <div className="rotation-actions">
            <button className="rotation-compare-button" type="button" onClick={() => compare(true)} disabled={isLoading || !options}>
              {isLoading ? <LoaderCircle className="spin" size={17} /> : <RotateCw size={16} />}
              {isLoading ? "Сравниваем…" : "Сравнить выбранные планы"}
            </button>
            <button className="rotation-examples-button" type="button" onClick={() => compare(false)} disabled={isLoading || !options}>
              Сравнить три демо-примера
            </button>
          </div>
        </div>
      ) : (
        <p className="rotation-options-loading">{optionsError || "Загружаем каталог культур…"}</p>
      )}

      {comparison && (
        <div className="rotation-result">
          <div className="rotation-climate-context">
            <div>
              <span className="rotation-context-label">Климатический контекст</span>
              <strong>{comparison.climate_context.status === "unknown" ? "Не передан" : `${comparison.climate_context.historical_period?.start} — ${comparison.climate_context.historical_period?.end}`}</strong>
              {comparison.climate_context.location && <span className="rotation-context-detail">Точка: {comparison.climate_context.location.latitude}, {comparison.climate_context.location.longitude}</span>}
              {comparison.climate_context.status !== "unknown" && <span className="rotation-context-detail">{comparison.climate_context.source_is_synthetic ? "Синтетические данные" : comparison.climate_context.retrieved_from_cache ? "NASA POWER · локальный кэш" : "NASA POWER · получено"}</span>}
            </div>
            <span className="rotation-future-unknown"><AlertTriangle size={14} /> Климат следующих сезонов: unknown</span>
            <p>{comparison.climate_context.explanation}</p>
            {contextStale && <p className="rotation-context-stale">Параметры участка или даты изменены после анализа; выше показан контекст предыдущего запроса.</p>}
          </div>

          <div className={`rotation-plan-grid rotation-plan-count-${comparison.plans.length}`}>
            {comparison.plans.map((plan) => <PlanCard plan={plan} cropNames={cropNames} key={plan.plan_id} />)}
          </div>

          <ul className="rotation-comparison-limitations">
            {comparison.comparison_limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
          </ul>
        </div>
      )}

      {errorMessage && <p className="rotation-error" role="alert">{errorMessage}</p>}
    </section>
  );
}
