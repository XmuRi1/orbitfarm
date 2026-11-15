"use client";

import { useRef, useState, type FormEvent } from "react";
import dynamic from "next/dynamic";
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowRight,
  CalendarDays,
  Check,
  ChevronDown,
  CircleHelp,
  CloudSun,
  Droplets,
  Leaf,
  LoaderCircle,
  MapPin,
  RotateCcw,
  Sun,
  Thermometer,
  Wind,
} from "lucide-react";
import type {
  ApiError,
  AssessRequest,
  CropAssessment,
  NasaAssessResponse,
  Observation,
  SoilObservation,
} from "@/lib/contracts";
import RotationPlanner from "@/components/rotation-planner";

const FieldMap = dynamic(() => import("@/components/field-map"), {
  ssr: false,
  loading: () => <div className="field-map-loading">Загружаем карту…</div>,
});

interface FormState {
  latitude: string;
  longitude: string;
  start: string;
  end: string;
  mode: "demo" | "strict";
  activeGrowth: boolean;
  pH: string;
  texture: string;
}

const initialForm: FormState = {
  latitude: "31.25",
  longitude: "34.79",
  start: "2025-01-01",
  end: "2025-03-31",
  mode: "demo",
  activeGrowth: false,
  pH: "",
  texture: "",
};

const climateMetrics = [
  { id: "CLIM_001", label: "Средняя температура", icon: Thermometer },
  { id: "CLIM_002", label: "Минимум периода", icon: Thermometer },
  { id: "CLIM_003", label: "Максимум периода", icon: Thermometer },
  { id: "CLIM_007", label: "Осадки за период", icon: Droplets },
  { id: "CLIM_008", label: "Влажность воздуха", icon: CloudSun },
  { id: "CLIM_009", label: "Солнечная радиация", icon: Sun },
] as const;

const factorLabels: Record<string, string> = {
  CLIM_001: "Средняя температура",
  CLIM_002: "Минимальная температура",
  CLIM_003: "Максимальная температура",
  CLIM_007: "Осадки",
  CLIM_008: "Влажность воздуха",
  CLIM_009: "Солнечная радиация",
  SOIL_001: "pH почвы",
  SOIL_005: "Текстура почвы",
  WATER_007: "Водный баланс",
};

const factorStatusLabels: Record<string, string> = {
  DEMO_REFERENCE_MATCH: "Внутри справочного диапазона",
  DEMO_OUTSIDE_REFERENCE: "Вне справочного диапазона",
  DEMO_LISTED_PREFERRED_TEXTURE: "В списке предпочтений",
  FARM_OBSERVATION_MISSING: "Нет наблюдения участка",
  GROWTH_STAGE_MISMATCH_OR_MISSING: "Не задана подходящая фаза роста",
  WATER_BALANCE_REQUIRED: "Нужен расчёт водного баланса",
  REQUIREMENT_UNVERIFIED: "Требование не проверено",
  CROP_REQUIREMENT_MISSING: "Требование культуры отсутствует",
  TEXTURE_NOT_LISTED_UNKNOWN_COMPATIBILITY: "Совместимость неизвестна",
  incompatible_units: "Несовпадение единиц",
  aggregation_mismatch: "Несовпадение агрегации",
};

const messageTranslations: Record<string, string> = {
  "NASA POWER point data may differ from conditions at your actual farm.":
    "NASA POWER описывает условия в районе координат. На конкретном поле погода и микроклимат могут отличаться.",
  "The selected date window does not establish the planting date or growth stage of any crop.":
    "Выбранный период сам по себе не подтверждает даты посева или фазу развития культур.",
  "CLIM_007 is total precipitation, not effective crop-available rainfall or ETc.":
    "CLIM_007 — сумма осадков. Она не показывает, сколько воды доступно растениям, и не является ETc.",
  "No crop growth stage assigned: stage-dependent crop factors remain unscored.":
    "Фаза развития не указана. Факторы, для которых важна фаза культуры, не оценивались.",
  "No soil observations supplied. NASA POWER does not measure the farm's soil pH or texture.":
    "Нет измерений почвы. NASA POWER не определяет pH или механический состав на участке.",
  "No scientific validation of the crop requirement dataset.":
    "Требования культур в наборе данных пока не прошли научную проверку.",
  "Demo partial score uses arbitrary weights and linear penalties; not a forecast, yield estimate or farming recommendation.":
    "Частичный демо-балл использует условные веса и штрафы. Это не прогноз урожая и не рекомендация по выращиванию.",
  "NASA POWER is weather/climate context, not field-measured soil information.":
    "NASA POWER предоставляет климатические данные, а не результаты измерений почвы на поле.",
  "Water balance must use effective rainfall, ET0/Kc, storage, irrigation and losses for each crop's planting window.":
    "Для водного баланса нужны эффективные осадки, ET0/Kc, запас воды в почве, орошение и потери за период выращивания культуры.",
  "Crop requirements are unverified team draft.":
    "Требования к этой культуре пока остаются непроверенным командным черновиком.",
  "Seasonal water balance is not implemented; cannot give an overall suitability score.":
    "Сезонный водный баланс ещё не реализован, поэтому итоговая пригодность не рассчитывается.",
  "The same scenario period is not necessarily a valid crop growing season for every crop.":
    "Один и тот же период не обязательно соответствует сезону выращивания каждой культуры.",
  "Unverified source range and illustrative linear penalty, not agronomic yield prediction.":
    "Диапазон и линейный штраф не проверены; это демонстрационное сопоставление, а не прогноз урожайности.",
  "Preference list is non-exhaustive; do not assign a penalty for unlisted textures.":
    "Список предпочтительных типов почвы неполный. Для неуказанных типов штраф не назначается.",
  "Precipitation alone cannot be compared with crop water demand. Calculate crop-cycle available water/ETc.":
    "Одних осадков недостаточно для сравнения со спросом культуры на воду. Нужен водный баланс за цикл выращивания и ETc.",
  "No production score from team-draft thresholds.":
    "Численный производственный балл не рассчитывается по непроверенным порогам из командного черновика.",
};

const aggregationLabels: Record<string, string> = {
  mean_daily_mean_over_period: "Среднее суточных средних за период",
  minimum_daily_minimum_over_period: "Минимум суточных минимумов за период",
  maximum_daily_maximum_over_period: "Максимум суточных максимумов за период",
  sum_daily_precipitation_over_period: "Сумма суточных осадков за период",
  mean_daily_total_over_period: "Среднее суточных сумм за период",
};

const numberFormat = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

function parseCoordinates(latitude: string, longitude: string): [number, number] | null {
  if (!latitude.trim() || !longitude.trim()) return null;
  const parsedLatitude = Number(latitude);
  const parsedLongitude = Number(longitude);
  if (
    !Number.isFinite(parsedLatitude) ||
    !Number.isFinite(parsedLongitude) ||
    parsedLatitude < -90 || parsedLatitude > 90 ||
    parsedLongitude < -180 || parsedLongitude > 180
  ) {
    return null;
  }
  return [parsedLatitude, parsedLongitude];
}

function formatHemisphere(value: string, positive: string, negative: string) {
  const parsed = Number(value);
  if (!value.trim() || !Number.isFinite(parsed)) return "—";
  return `${numberFormat.format(Math.abs(parsed))}° ${parsed < 0 ? negative : positive}`;
}

function formatValue(value: number | string) {
  return typeof value === "number" ? numberFormat.format(value) : value;
}

function formatReference(factor: CropAssessment["factors"][number]) {
  if (!factor.reference) return "Нет справочного требования";
  const { min, max, unit, preferred_categories: categories } = factor.reference;
  if (typeof min === "number" && typeof max === "number") {
    return `${formatValue(min)}–${formatValue(max)} ${unit ?? ""}`.trim();
  }
  if (categories?.length) return categories.join(", ");
  return "Справочное значение не задано";
}

function findObservation(observations: Observation[], id: string) {
  return observations.find((observation) => observation.parameter_id === id);
}

function displayError(apiError: ApiError) {
  if (apiError.error === "nasa_upstream_unavailable") {
    return "NASA POWER не вернул пригодные данные. Проверьте подключение и повторите запрос.";
  }
  if (apiError.error === "backend_unavailable") {
    return "Не удалось подключиться к Python API. Проверьте, что backend запущен и ORBITFARM_BACKEND_URL задан.";
  }
  if (apiError.error === "backend_not_configured") {
    return "Адрес Python API не задан. Настройте ORBITFARM_BACKEND_URL на сервере Next.js.";
  }
  return apiError.detail ?? "Не удалось выполнить анализ. Проверьте введённые данные.";
}

function factorValue(factor: CropAssessment["factors"][number]) {
  if (factor.observed_value === null) return "Нет данных";
  return `${formatValue(factor.observed_value)} ${factor.observed_unit ?? ""}`.trim();
}

function cropStatusLabel(crop: CropAssessment) {
  if (crop.demo_partial_score_0_100 === null) return "Недостаточно сопоставимых данных";
  return "Частичный демо-балл по доступным факторам";
}

function UserMessage({ message }: { message: string }) {
  const translation = messageTranslations[message];

  return (
    <div className="user-message">
      <span>{translation ?? message}</span>
      {translation && (
        <details className="raw-message">
          <summary>Исходный текст</summary>
          <code>{message}</code>
        </details>
      )}
    </div>
  );
}

function MetricValue({ observation }: { observation?: Observation }) {
  if (!observation) return <span className="metric-empty">Нет данных</span>;
  return (
    <span className="metric-value">
      {formatValue(observation.value)} <small>{observation.unit}</small>
    </span>
  );
}

function CropResult({ crop }: { crop: CropAssessment }) {
  const coverage = Math.round(crop.demo_weight_coverage * 100);

  return (
    <details className="crop-row">
      <summary className="crop-summary">
        <span className="crop-identity">
          <strong>{crop.name_ru}</strong>
          <small>{crop.name_en}</small>
        </span>
        <span className="crop-demo-score">
          <small>Демо-балл · частично</small>
          <strong>
            {crop.demo_partial_score_0_100 === null
              ? "Не рассчитан"
              : <>{numberFormat.format(crop.demo_partial_score_0_100)}<small> / 100</small></>}
          </strong>
        </span>
        <span className="crop-coverage">
          <span>Учтено демо-весов</span>
          <strong>{coverage}%</strong>
          <span className="coverage-track" aria-label={`Покрытие ${coverage}%`}>
            <span style={{ width: `${coverage}%` }} />
          </span>
        </span>
        <ChevronDown className="crop-chevron" size={17} aria-hidden="true" />
      </summary>
      <div className="crop-detail">
        <div className="crop-detail-head">
          <span>{cropStatusLabel(crop)}</span>
          <span>
            Итоговая пригодность: <strong>{crop.suitability_score_0_100 === null ? "не рассчитана" : crop.suitability_score_0_100}</strong>
          </span>
        </div>
        <div className="factor-list">
          {crop.factors.map((factor) => (
            <div className="factor-row" key={factor.parameter_id}>
              <strong className="factor-name">{factorLabels[factor.parameter_id] ?? factor.parameter_id}</strong>
              <div className="factor-observed">
                <small>Данные участка</small>
                <strong>{factorValue(factor)}</strong>
              </div>
              <div className="factor-reference">
                <small>Ориентир модели</small>
                <strong>{formatReference(factor)}</strong>
              </div>
              <div className={`factor-status${factor.demo_factor_score_0_100 === null ? " is-unavailable" : " is-available"}`}>
                <small>Статус</small>
                <strong>{factorStatusLabels[factor.status] ?? factor.status}</strong>
              </div>
              <span className="factor-score">
                {factor.demo_factor_score_0_100 === null
                  ? "Не оценён"
                  : `Демо ${numberFormat.format(factor.demo_factor_score_0_100)}`}
              </span>
              {factor.warning && <div className="factor-warning"><UserMessage message={factor.warning} /></div>}
            </div>
          ))}
        </div>
        {crop.warnings.length > 0 && (
          <ul className="crop-warnings">
            {crop.warnings.map((warning) => <li key={warning}><UserMessage message={warning} /></li>)}
          </ul>
        )}
      </div>
    </details>
  );
}

export default function Home() {
  const [form, setForm] = useState<FormState>(initialForm);
  const [mapPoint, setMapPoint] = useState<[number, number]>([31.25, 34.79]);
  const coordinatesRef = useRef({ latitude: initialForm.latitude, longitude: initialForm.longitude });
  const [result, setResult] = useState<NasaAssessResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateCoordinate(key: "latitude" | "longitude", value: string) {
    coordinatesRef.current = { ...coordinatesRef.current, [key]: value };
    const point = parseCoordinates(coordinatesRef.current.latitude, coordinatesRef.current.longitude);
    if (point) setMapPoint(point);
    update(key, value);
  }

  function selectMapPoint(latitude: number, longitude: number) {
    const point: [number, number] = [
      Number(latitude.toFixed(5)),
      Number(longitude.toFixed(5)),
    ];
    coordinatesRef.current = { latitude: String(point[0]), longitude: String(point[1]) };
    setMapPoint(point);
    setForm((current) => ({
      ...current,
      latitude: String(point[0]),
      longitude: String(point[1]),
    }));
  }

  function useBeershebaExample() {
    coordinatesRef.current = { latitude: "31.25", longitude: "34.79" };
    setMapPoint([31.25, 34.79]);
    setForm((current) => ({
      ...current,
      latitude: "31.25",
      longitude: "34.79",
      start: "2025-01-01",
      end: "2025-03-31",
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage("");
    setResult(null);
    setIsLoading(true);

    const soilObservations: SoilObservation[] = [];
    if (form.pH.trim()) {
      soilObservations.push({
        parameter_id: "SOIL_001",
        value: Number(form.pH),
        unit: "pH",
        context: { soil_depth_cm: null },
        source: { name: "user_entered_unverified", synthetic: false },
      });
    }
    if (form.texture) {
      soilObservations.push({
        parameter_id: "SOIL_005",
        value: form.texture,
        unit: "USDA / FAO texture class",
        context: { soil_depth_cm: null },
        source: { name: "user_entered_unverified", synthetic: false },
      });
    }

    const body: AssessRequest = {
      latitude: Number(form.latitude),
      longitude: Number(form.longitude),
      start: form.start,
      end: form.end,
      farm_id: "orbitfarm_frontend_site",
      mode: form.mode,
      growth_stage: form.activeGrowth ? "active_growth" : null,
      soil_observations: soilObservations,
    };

    try {
      const response = await fetch("/api/assess", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json() as NasaAssessResponse | ApiError;
      if (!response.ok) {
        setErrorMessage(displayError(payload as ApiError));
        return;
      }
      setResult(payload as NasaAssessResponse);
    } catch {
      setErrorMessage("Не удалось обработать ответ. Проверьте локальный API и повторите запрос.");
    } finally {
      setIsLoading(false);
    }
  }

  function downloadResult() {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "orbitfarm-nasa-assessment.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  const observations = result?.farm.observations ?? [];
  const warnings = result
    ? [...new Set([...result.warnings, ...result.assessment.warnings])]
    : [];
  const displayCrops = result
    ? [...result.assessment.crops].sort((first, second) => first.name_ru.localeCompare(second.name_ru, "ru"))
    : [];
  const rotationClimateContext = result
    ? {
        historical_period: result.historical_period,
        location: result.farm.location,
        source_is_synthetic: result.source_is_synthetic,
        retrieved_from_cache: result.retrieved_from_cache,
        observations: result.farm.observations,
      }
    : null;
  const currentPoint = parseCoordinates(form.latitude, form.longitude);
  const coordinatesChanged = Boolean(
    result &&
    (!currentPoint ||
      currentPoint[0] !== result.farm.location.latitude ||
      currentPoint[1] !== result.farm.location.longitude),
  );
  const rotationContextStale = Boolean(
    result &&
    (coordinatesChanged ||
      form.start !== result.historical_period.start ||
      form.end !== result.historical_period.end),
  );

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="OrbitFarm, главная">
          <span className="brand-mark"><Leaf size={19} strokeWidth={2.2} /></span>
          <span>orbit<span>farm</span></span>
        </a>
        <div className="topbar-meta">
          <span className="service-dot" />
          <span>NASA POWER · исторические данные</span>
          <span className="topbar-divider" />
          <span className="local-label">FIELD LAB / MVP</span>
        </div>
      </header>

      <section className="page-heading" id="top">
        <div>
          <p className="eyebrow">Климатический профиль участка</p>
          <h1>Проверьте климат.<br /><em>Изучите потенциал.</em></h1>
        </div>
        <p className="heading-note">
          Исторические наблюдения NASA POWER и прозрачное сопоставление факторов
          для десяти культур. Не прогноз урожая.
        </p>
      </section>

      <div className="dashboard-grid">
        <aside className="control-rail">
          <div className="rail-heading">
            <div>
              <p className="eyebrow">Новый анализ</p>
              <h2>Параметры участка</h2>
            </div>
            <button className="icon-button" type="button" onClick={useBeershebaExample} title="Подставить пример Беэр-Шевы" aria-label="Подставить пример Беэр-Шевы">
              <RotateCcw size={16} />
            </button>
          </div>

          <form onSubmit={submit}>
            <div className="form-section">
              <div className="section-label"><MapPin size={15} /><span>Координаты центра участка</span></div>
              <div className="coordinate-grid">
                <label className="field-label">
                  <span>Широта</span>
                  <input aria-label="Широта" type="number" step="any" min="-90" max="90" required value={form.latitude} onChange={(event) => updateCoordinate("latitude", event.target.value)} />
                </label>
                <label className="field-label">
                  <span>Долгота</span>
                  <input aria-label="Долгота" type="number" step="any" min="-180" max="180" required value={form.longitude} onChange={(event) => updateCoordinate("longitude", event.target.value)} />
                </label>
              </div>
              <FieldMap point={mapPoint} onSelect={selectMapPoint} />
              <div className="coordinate-note"><span>{formatHemisphere(form.latitude, "N", "S")}</span><span>{formatHemisphere(form.longitude, "E", "W")}</span><span>Точка NASA POWER</span></div>
              <button className="preset-button" type="button" onClick={useBeershebaExample}>
                <MapPin size={14} /> Пример региона Беэр-Шевы <ArrowRight size={14} />
              </button>
              {coordinatesChanged && result && (
                <div className="coordinate-change" role="status">
                  <AlertTriangle size={16} />
                  <p><strong>Точка изменена</strong><span>Показанный результат относится к {numberFormat.format(result.farm.location.latitude)}, {numberFormat.format(result.farm.location.longitude)}. Чтобы получить данные для новой точки, запустите анализ.</span></p>
                </div>
              )}
            </div>

            <div className="form-section">
              <div className="section-label"><CalendarDays size={15} /><span>Исторический период</span></div>
              <div className="coordinate-grid date-grid">
                <label className="field-label">
                  <span>С</span>
                  <input aria-label="Дата начала" type="date" required value={form.start} onChange={(event) => update("start", event.target.value)} />
                </label>
                <label className="field-label">
                  <span>По</span>
                  <input aria-label="Дата окончания" type="date" required value={form.end} onChange={(event) => update("end", event.target.value)} />
                </label>
              </div>
              <p className="field-hint">NASA POWER предоставляет прошедшие наблюдения, не прогноз.</p>
            </div>

            <div className="form-section">
              <div className="section-label"><Wind size={15} /><span>Сценарий оценки</span></div>
              <label className="field-label select-label">
                <span>Режим модели</span>
                <select value={form.mode} onChange={(event) => update("mode", event.target.value as FormState["mode"])}>
                  <option value="demo">Демо · частичные факторы</option>
                  <option value="strict">Строгий · без непроверенных баллов</option>
                </select>
              </label>
              <label className="check-row">
                <input type="checkbox" checked={form.activeGrowth} onChange={(event) => update("activeGrowth", event.target.checked)} />
                <span className="check-box"><Check size={12} /></span>
                <span><strong>Фаза активного роста</strong><small>Включайте только если весь период соответствует активному росту культуры. Это ручное допущение.</small></span>
              </label>
            </div>

            <div className="form-section soil-section">
              <div className="section-label"><CircleHelp size={15} /><span>Измерения почвы <small>необязательно</small></span></div>
              <div className="coordinate-grid">
                <label className="field-label">
                  <span>pH по замеру</span>
                  <input aria-label="pH почвы" type="number" min="0" max="14" step="0.1" placeholder="нет данных" value={form.pH} onChange={(event) => update("pH", event.target.value)} />
                </label>
                <label className="field-label">
                  <span>Текстура</span>
                  <select aria-label="Текстура почвы" value={form.texture} onChange={(event) => update("texture", event.target.value)}>
                    <option value="">Неизвестно</option>
                    <option value="loam">loam</option>
                    <option value="sandy_loam">sandy_loam</option>
                    <option value="clay_loam">clay_loam</option>
                    <option value="sand">sand</option>
                    <option value="clay">clay</option>
                    <option value="silt_loam">silt_loam</option>
                  </select>
                </label>
              </div>
              <p className="field-hint">Передаются только введённые вами значения; NASA не измеряет pH или текстуру.</p>
            </div>

            <button className="submit-button" type="submit" disabled={isLoading}>
              {isLoading ? <LoaderCircle className="spin" size={17} /> : <CloudSun size={17} />}
              {isLoading ? "Запрашиваем NASA POWER…" : "Запустить анализ"}
              {!isLoading && <ArrowRight size={16} />}
            </button>
          </form>

          {errorMessage && (
            <div className="error-message" role="alert">
              <AlertTriangle size={18} />
              <span>{errorMessage}</span>
            </div>
          )}
        </aside>

        <section className="results-area" aria-live="polite">
          {!result && !isLoading && !errorMessage && (
            <div className="welcome-state">
              <div className="welcome-art" aria-hidden="true">
                <div className="art-sun" />
                <div className="art-horizon" />
                <div className="art-row row-one" />
                <div className="art-row row-two" />
                <div className="art-row row-three" />
                <span className="art-coordinate">31°15&apos; N<br />34°47&apos; E</span>
              </div>
              <div className="welcome-copy">
                <span className="status-kicker"><span className="service-dot" /> READY FOR ANALYSIS</span>
                <h2>Климат участка<br />в контексте культур</h2>
                <p>Введите координаты и исторический период. OrbitFarm запросит данные NASA POWER и покажет, какие факторы доступны для сопоставления.</p>
                <div className="welcome-foot"><span>10 культур</span><span>6 климатических показателей</span><span>Без синтетического fallback</span></div>
              </div>
            </div>
          )}

          {isLoading && (
            <div className="loading-state">
              <div className="loader-orbit"><span /><span /><Leaf size={22} /></div>
              <p className="eyebrow">Получение исторических данных</p>
              <h2>Связываемся с NASA POWER</h2>
              <p>Загрузка суточных параметров, проверка покрытия и оценка факторов культур.</p>
              <div className="loading-steps"><span className="step-done">Запрос</span><span>Нормализация</span><span>Сопоставление</span></div>
            </div>
          )}

          {result && (
            <div className="result-content">
              <div className="result-header">
                <div>
                  <p className="eyebrow">Анализ завершён</p>
                  <h2>Климатический профиль</h2>
                </div>
                <button className="download-button" type="button" onClick={downloadResult}>
                  <ArrowDownToLine size={16} /> <span>JSON</span>
                </button>
              </div>

              <div className="result-meta">
                <span><MapPin size={14} /> {numberFormat.format(result.farm.location.latitude)}, {numberFormat.format(result.farm.location.longitude)}</span>
                <span><CalendarDays size={14} /> {result.historical_period.start} — {result.historical_period.end}</span>
                <span className="source-state"><span className="service-dot" /> {result.retrieved_from_cache ? "Локальный кэш" : "Ответ NASA"}</span>
              </div>

              <div className="source-banner">
                <div className="source-check"><Check size={14} /></div>
                <div><strong>{result.source_is_synthetic ? "Синтетический источник" : "NASA POWER · реальные исторические данные"}</strong><span>{result.retrieved_from_cache ? "Получено из локального кэша" : "Получено напрямую от NASA в этом запросе"} · не прогноз</span></div>
                <a href={result.source_url} target="_blank" rel="noreferrer" aria-label="Открыть URL источника NASA"><ArrowRight size={16} /></a>
              </div>

              <section className="data-section">
                <div className="section-title-row">
                  <div><p className="eyebrow">NASA POWER · DAILY</p><h3>Наблюдения за период</h3></div>
                  <span className="data-count">{observations.length} / 6 параметров</span>
                </div>
                <div className="metric-grid">
                  {climateMetrics.map((metric) => {
                    const observation = findObservation(observations, metric.id);
                    const Icon = metric.icon;
                    return (
                      <article className={`metric-cell${observation ? "" : " is-missing"}`} key={metric.id}>
                        <div className="metric-top"><Icon size={16} /><span>{metric.id}</span></div>
                        <p>{metric.label}</p>
                        <MetricValue observation={observation} />
                        {observation && <small className="metric-coverage">{observation.context?.days_available}/{observation.context?.days_requested} дней</small>}
                      </article>
                    );
                  })}
                </div>
              </section>

              {result.farm.data_gaps.length > 0 && (
                <div className="gap-banner">
                  <AlertTriangle size={17} />
                  <div><strong>Некоторые климатические данные отсутствуют</strong><ul>{result.farm.data_gaps.map((gap) => <li key={gap}><UserMessage message={gap} /></li>)}</ul></div>
                </div>
              )}

              <section className="crop-section">
                <div className="section-title-row crop-title-row">
                  <div><p className="eyebrow">СОПОСТАВЛЕНИЕ ФАКТОРОВ</p><h3>Результаты по культурам <span>{result.assessment.crops.length}</span></h3><p className="crop-sort-note">Список по названию, не рейтинг пригодности</p></div>
                  <span className="demo-chip">{result.assessment.mode === "demo" ? "ДЕМО · НЕ РЕКОМЕНДАЦИЯ" : "СТРОГИЙ РЕЖИМ"}</span>
                </div>
                <div className="score-honesty">
                  <div className="honesty-icon"><CircleHelp size={17} /></div>
                  <p><strong>{result.assessment.suitability_score_0_100 === null ? "Итоговая пригодность не рассчитана" : "Итоговая пригодность"}</strong><span>{result.assessment.mode === "demo" ? "Демо-балл показывает только совпадение части факторов. Низкое покрытие означает, что многие веса не вошли в расчёт; это не научная оценка уверенности." : "Строгий режим не выдаёт баллы по непроверенным требованиям."} Научно подтверждённая оценка: {result.assessment.suitability_score_0_100 === null ? "нет данных" : result.assessment.suitability_score_0_100}.</span></p>
                </div>
                <div className="crop-list">
                  {displayCrops.map((crop) => <CropResult crop={crop} key={crop.crop_id} />)}
                </div>
              </section>

              <section className="warnings-section">
                <div className="section-title-row"><div><p className="eyebrow">КАЧЕСТВО И ОГРАНИЧЕНИЯ</p><h3>Что важно учитывать</h3></div><AlertTriangle size={18} /></div>
                <ul>{warnings.map((warning) => <li key={warning}><UserMessage message={warning} /></li>)}</ul>
              </section>

              <details className="provenance-details">
                <summary>Параметры источника и агрегации <ChevronDown size={15} /></summary>
                <div className="provenance-grid">
                  {observations.map((observation) => (
                    <div key={observation.parameter_id}><strong>{factorLabels[observation.parameter_id] ?? observation.parameter_id}</strong><span>{aggregationLabels[observation.aggregation ?? ""] ?? observation.aggregation}</span><code>{observation.aggregation}</code><small>{observation.source.name} · синтетические данные: {observation.source.synthetic ? "да" : "нет"}</small></div>
                  ))}
                </div>
              </details>
            </div>
          )}
        </section>
      </div>

      <RotationPlanner
        key={result ? `${result.farm.location.latitude}-${result.farm.location.longitude}-${result.historical_period.start}-${result.historical_period.end}` : "no-climate-context"}
        climateContext={rotationClimateContext}
        contextStale={rotationContextStale}
      />

      <footer className="page-footer">
        <span><Leaf size={14} /> OrbitFarm Field Lab</span>
        <span>Региональные климатические данные не заменяют измерения на поле.</span>
        <a href="https://power.larc.nasa.gov/docs/services/api/temporal/daily/" target="_blank" rel="noreferrer">NASA POWER API <ArrowRight size={13} /></a>
      </footer>
    </main>
  );
}