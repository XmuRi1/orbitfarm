"use client";

import { useState } from "react";
import { AlertTriangle, ArrowDownToLine, ArrowRight, CalendarDays, Check, ChevronDown, CloudSun, Droplets, LoaderCircle, MapPin, Sun, Thermometer, Wind } from "lucide-react";
import type { WaterAssessment } from "@/lib/water-contracts";
import type { RootZoneComparison } from "@/lib/root-zone-contracts";
import type { SeasonAssessment } from "@/lib/season-contracts";
import WaterDemand from "@/components/water-demand";
import type { ScenarioBindings } from "@/lib/scenario-inputs";

const metricLabels: Record<string, string> = {
  mean_temperature: "Средняя температура", minimum_temperature: "Минимальная температура",
  maximum_temperature: "Максимальная температура", total_precipitation: "Сумма осадков",
  rainy_days: "Дни с осадками > 0 мм", mean_solar_radiation: "Средняя солнечная радиация",
  mean_relative_humidity: "Средняя влажность",
};
const units: Record<string, string> = { "mm per period": "мм за сезон", days: "дней" };
const format = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });
const metricIcons = { mean_temperature: Thermometer, minimum_temperature: Thermometer, maximum_temperature: Thermometer, total_precipitation: Droplets, rainy_days: CalendarDays, mean_solar_radiation: Sun, mean_relative_humidity: Wind };
const missingReasons: Record<string, string> = {
  missing_day: "Нет наблюдения за день", fill_value: "Пропуск в источнике NASA",
  invalid_value: "Некорректное значение", outside_physical_range: "За физически допустимым диапазоном",
  unsupported_or_missing_unit: "Единицы неизвестны или несовместимы",
};

export default function SeasonalAnalysis({ result, loading, error, reused, onWaterResult, onRootResult, bindings }: {
  result: SeasonAssessment | null; loading: boolean;
  error: { message: string; status?: number } | null; reused: boolean;
  onWaterResult: (value: WaterAssessment | null, assumptions?: string) => void;
  onRootResult: (value: RootZoneComparison | null, waterAssumptions?: string, rootAssumptions?: string) => void;
  bindings: ScenarioBindings;
}) {
  const [dailyParameter, setDailyParameter] = useState("CLIM_001");
  const dailySeries = result?.daily.parameters.find((series) => series.parameter_id === dailyParameter);

  function download() {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `orbitfarm-season-${result.crop.crop_id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="season-section" id="seasonal-analysis" aria-busy={loading} aria-label="Сезонные исторические наблюдения">
      <div className="season-layout integrated-season-layout">
        <div className="season-results" aria-live="polite" aria-atomic="false">
          {reused && <p className="field-hint">Повторно использован ответ для тех же участка, периода и культуры; нового запроса NASA не было.</p>}
          {loading && <div className="season-state" role="status"><LoaderCircle size={25} className="spin" /><h3>Получаем ежедневные наблюдения</h3><p>Проверяем температуру, осадки, влажность и солнечную радиацию за выбранные даты.</p></div>}
          {!loading && error && <div className="error-message" role="alert"><AlertTriangle size={19} /><div><strong>{error.status ? `HTTP ${error.status} · ` : ""}{error.status === 404 ? "Сезонный API не найден" : "Анализ не выполнен"}</strong><p>{error.message}</p></div></div>}
          {!loading && !error && !result && <div className="season-state"><CloudSun size={30} /><h3>Климат вашего периода</h3><p>Выберите культуру и даты в разделе «Участок» и запустите сезонный анализ. Здесь появятся семь метрик, полнота наблюдений и источник данных.</p><span className="data-count">ЕЖЕДНЕВНЫЕ ДАННЫЕ · LST · НЕ ПРОГНОЗ</span></div>}
          {result && !loading && <div className="season-result">
            <div className="section-title-row"><div><p className="eyebrow">ИСТОРИЧЕСКИЙ АНАЛИЗ ЗАВЕРШЁН</p><h3>{result.crop.name_ru} · {result.season.duration_days} дней</h3></div></div>
            <div className="result-meta"><span><CalendarDays size={14} />{result.season.sowing_date} — {result.season.end_date}</span><span><MapPin size={14} />{result.location.latitude}, {result.location.longitude}</span></div>
            <div className="source-banner"><div className="source-check"><Check size={14} /></div><div><strong>{result.source_is_synthetic ? "Синтетическая тестовая фикстура" : "NASA POWER · исторические наблюдения"}</strong><span>{result.retrieved_from_cache ? "Получено из кэша" : "Получено от источника"} · местное солнечное время LST · не прогноз</span></div>{result.source.url && <a href={result.source.url} target="_blank" rel="noreferrer" aria-label="Открыть источник сезонных данных NASA"><ArrowRight size={16} /></a>}</div>
            <div className="season-coverage"><div><strong>Полнота наблюдений</strong><span>{result.coverage.complete_days} из {result.coverage.expected_days} дней содержат все шесть параметров</span></div><strong>{format.format(result.coverage.fraction * 100)}%</strong></div>
            <p className="field-hint season-coverage-note">Доля доступных ежедневных значений, не научная уверенность.</p>
            <div className="metric-grid season-metrics">{Object.entries(result.metrics).map(([name, metric]) => {
              const Icon = metricIcons[name as keyof typeof metricIcons] ?? CloudSun;
              return <article className={`metric-cell${metric.value === null ? " is-missing" : ""}`} key={name}>
                <div className="metric-top"><Icon size={16} /><span>{metric.days_available}/{metric.days_expected} дней</span></div>
                <p>{metricLabels[name] ?? name}</p>
                {metric.value === null ? <span className="metric-empty">{metric.days_available === 0 ? "Нет данных" : "Полное значение неизвестно"}</span> : <span className="metric-value">{format.format(metric.value)} <small>{units[metric.unit] ?? metric.unit}</small></span>}
                <small className="metric-coverage">{metric.status === "complete" ? "Полные наблюдения" : metric.status === "partial" ? "Только доступные дни" : "Наблюдений нет"}</small>
                {metric.value === null && metric.observed_value !== null && <p className="season-partial">По доступным дням: {format.format(metric.observed_value)} {units[metric.unit] ?? metric.unit}</p>}
                {metric.reason && <p className="season-metric-reason">{metric.reason}</p>}
              </article>;
            })}</div>
            <details className="provenance-details season-details"><summary>Экспертные подробности сезона и JSON</summary><div className="season-detail-body">
              <button type="button" className="download-button" onClick={download}><ArrowDownToLine size={15} /> JSON</button>
            <details className="provenance-details season-details"><summary>Ежедневные наблюдения и пропуски <ChevronDown size={15} /></summary><div className="season-detail-body">
              <p className="field-hint">LST {result.daily.time_standard_basis === "response_header" ? "подтверждено метаданными ответа" : "явно задано в запросе; в метаданных ответа не указано"}. Пропуски не заполняются.</p>
              <label className="field-label select-label season-series-select"><span>Показатель ежедневного ряда</span><select value={dailyParameter} onChange={(event) => setDailyParameter(event.target.value)}>{result.daily.parameters.map((series) => <option key={series.parameter_id} value={series.parameter_id}>{series.nasa_parameter} · {series.unit}</option>)}</select></label>
              {dailySeries && <div className="season-daily" tabIndex={0} role="region" aria-label="Таблица ежедневных наблюдений"><table><thead><tr><th scope="col">Дата</th><th scope="col">{dailySeries.unit}</th><th scope="col">Наблюдение</th></tr></thead><tbody>{dailySeries.values.map((row) => <tr key={row.date}><td>{row.date}</td><td>{row.value === null ? "—" : format.format(row.value)}</td><td>{row.missing_reason ? missingReasons[row.missing_reason] ?? row.missing_reason : "Доступно"}</td></tr>)}</tbody></table></div>}
            </div></details>
            <details className="provenance-details season-details"><summary>Требования культуры и неизвестные значения <ChevronDown size={15} /></summary><div className="season-detail-body"><p className="field-hint">Пригодность не рассчитана. Справочные диапазоны не являются подтверждёнными критическими границами.</p>{result.crop_requirements.map((requirement) => <div key={requirement.parameter_id} className="season-requirement"><strong>{requirement.parameter_id}</strong>{requirement.reference && <span> · Справочный диапазон: {requirement.reference.min}–{requirement.reference.max} {units[requirement.reference.unit] ?? requirement.reference.unit}</span>}<p>{requirement.comparison ? requirement.comparison === "within_reference" ? "В пределах совместимого справочного диапазона." : "Вне совместимого справочного диапазона." : "Сопоставление неизвестно (unknown)."} {requirement.reasons.join(" ")}</p></div>)}</div></details>
            <details className="provenance-details season-details"><summary>Ограничения анализа <ChevronDown size={15} /></summary><ul className="season-limitations">{result.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></details>
            </div></details>
            <WaterDemand season={result} onResult={onWaterResult} onRootResult={onRootResult} bindings={bindings} />
          </div>}
        </div>
      </div>
    </section>
  );
}
