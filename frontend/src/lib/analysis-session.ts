/** UI orchestration only. No weather calculations or replacement API contracts. */
export interface AnalysisContext {
  latitude: string; longitude: string; start: string; end: string; cropId: string;
}
export function contextKey(context: AnalysisContext): string {
  return JSON.stringify([context.latitude, context.longitude, context.start, context.end, context.cropId]);
}
export function currentPublication<T>(publication: { scope: string; assumptions?: string; value: T } | null,
  scope: string, assumptions?: string): T | null {
  return publication?.scope === scope && (assumptions === undefined || publication.assumptions === assumptions) ? publication.value : null;
}
export function stableKey(value: unknown): string {
  return JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item)
    ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, item[key]])) : item);
}

export class AnalysisError extends Error {
  constructor(public status: number, public code: string, detail: string) { super(detail); }
}
export function analysisErrorText(error: AnalysisError | null): string {
  if (!error) return "";
  const messages: Record<string, string> = {
    nasa_upstream_unavailable: "NASA POWER недоступен или вернул неподходящие данные. Синтетической замены нет.",
    backend_unavailable: "Не удалось связаться с FastAPI. Проверьте локальный backend.",
    backend_not_configured: "Не задан серверный адрес FastAPI.",
    invalid_backend_response: "Сервер вернул неподходящий JSON.",
    rate_limited: "Общий лимит NASA исчерпан. Повторите запрос позже.",
    root_zone_inputs_incomplete: "Нужны полные ряды ET₀, потенциальной ETc и осадков. Проверьте высоту, Kc и календарь фаз.",
  };
  const detail = error.status === 404 ? "Маршрут API не найден. Перезапустите актуальный FastAPI."
    : messages[error.code] ?? error.message;
  return `${error.status ? `HTTP ${error.status}: ` : ""}${detail}`;
}

const cache = new Map<string, { value: unknown; expires: number }>();
const pending = new Map<string, Promise<unknown>>();
const TTL_MS = 5 * 60_000;

export async function requestJSON<T>(url: string, body?: unknown): Promise<{ value: T; reused: boolean }> {
  const key = stableKey([url, body ?? null]);
  const saved = cache.get(key);
  if (saved && saved.expires > Date.now()) return { value: saved.value as T, reused: true };
  const existing = pending.get(key);
  if (existing) return { value: await existing as T, reused: true };
  const operation = (async () => {
    let response: Response;
    try {
      response = await fetch(url, body === undefined ? { cache: "no-store" } : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store",
      });
    } catch { throw new AnalysisError(0, "backend_unavailable", "Нет связи с API."); }
    let payload;
    try { payload = await response.json(); }
    catch { throw new AnalysisError(response.status === 404 ? 404 : 502, "invalid_backend_response", "Неподходящий JSON."); }
    if (!response.ok) throw new AnalysisError(response.status, payload?.error ?? "api_error", payload?.detail ?? "Анализ не выполнен.");
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new AnalysisError(502, "invalid_backend_response", "Ожидался JSON-объект.");
    if (cache.size >= 32) cache.delete(cache.keys().next().value!);
    cache.set(key, { value: payload, expires: Date.now() + TTL_MS });
    return payload;
  })();
  pending.set(key, operation);
  try { return { value: await operation as T, reused: false }; }
  finally { pending.delete(key); }
}

export interface AnalysisSnapshot<T> {
  result: T | null; loading: boolean; error: AnalysisError | null; reused: boolean;
}
/** Generation fencing prevents late successes AND late failures from restoring old results. */
export class AnalysisSession<T> {
  constructor(public readonly scope = "") {}
  private generation = 0;
  private snapshot: AnalysisSnapshot<T> = { result: null, loading: false, error: null, reused: false };
  private listeners = new Set<() => void>();
  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private publish(snapshot: AnalysisSnapshot<T>) { this.snapshot = snapshot; this.listeners.forEach((fn) => fn()); }
  reset = () => { this.generation++; this.publish({ result: null, loading: false, error: null, reused: false }); };
  cancel = () => { this.generation++; };
  async run(operation: () => Promise<{ value: T; reused: boolean }>): Promise<T | null> {
    const generation = ++this.generation;
    this.publish({ result: null, loading: true, error: null, reused: false });
    try {
      const { value, reused } = await operation();
      if (generation !== this.generation) return null;
      this.publish({ result: value, loading: false, error: null, reused });
      return value;
    } catch (error) {
      if (generation !== this.generation) return null;
      this.publish({ result: null, loading: false, reused: false,
        error: error instanceof AnalysisError ? error : new AnalysisError(0, "api_error", error instanceof Error ? error.message : "Ошибка API.") });
      return null;
    }
  }
}
