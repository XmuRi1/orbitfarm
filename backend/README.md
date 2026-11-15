# OrbitFarm Backend — локальный MVP

Канонический API для локального запуска и Vercel — `app.py:app` (FastAPI). Весь Python-код, данные и тесты находятся в `backend/`. Для корневого quickstart, serverless ограничений и настройки двух Vercel Projects см. [README проекта](../README.md).

Этот пакет расширяет уже работающий движок OrbitFarm. Он делает **реальный запрос исторических данных NASA POWER на компьютере пользователя**, приводит ответ к каноническим `parameter_id` и запускает демонстрационную оценку 10 культур. При недоступности NASA ошибка отображается явно; **никакой замены реальных значений синтетическими нет**.

**Проверка NASA:** живой сквозной запрос NASA POWER выполнялся для тестового региона Беэр-Шевы. Текущие тесты используют синтетические данные или mock и не обращаются к NASA.

## 1. Запуск FastAPI на Windows

Из корня репозитория создайте окружение (если `backend/.venv` ещё нет) и установите зависимости:

```powershell
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements-local.txt -r backend/requirements-test.txt
```

В новом терминале из корня репозитория запустите API без активации окружения:

```powershell
.\backend\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

Проверка процесса: **http://127.0.0.1:8000/health**. Можно также запустить `backend/start_api_windows.bat`: он использует то же окружение и FastAPI на порту 8000, без reload. Основной интерфейс — Next.js на **http://127.0.0.1:3000**, его настройка описана в корневом README. Укажите `ORBITFARM_BACKEND_URL=http://127.0.0.1:8000` в `frontend/.env.local`.

Старый `backend/api_server.py` сохранён для совместимости с диагностической HTML-страницей на порту 8765 и её тестами. Он не поддерживает Rotation Planner и не используется основным интерфейсом. Корневой `api_server.py` — короткий запускатель FastAPI на порту 8000. Общая загрузка каталога и валидация вынесены в `api_contracts.py`; FastAPI не зависит от старого HTTP-сервера.

В интерфейсе есть тестовые координаты **31.25, 34.79 (регион Беэр-Шевы, не точка конкретного поля)** и пример периода **01.01.2025 — 31.03.2025**. Нажми «Получить климат NASA и рассчитать». Сервер сделает запрос к NASA; повторное обращение к той же точке и датам сможет взять локальный кэш.

**Дата и фаза:** выбранные даты — исторический диапазон, **не прогноз**. По умолчанию UI содержит включённое демо-допущение `active_growth`: оно помогает увидеть тестовые оценки, но **не означает**, что все 10 культур действительно проходили фазу активного роста в эти даты. Сними галочку для честной оценки без выдуманной фазы: многие stage-dependent факторы останутся без балла.

pH и тип почвы в форме **не поступают из NASA**, вводить их нужно только при наличии измерений. При пустых полях скоринг не подставляет почвенные данные.

## 2. Как работает поток

```text
Координаты + даты + опциональные сведения о почве
  ↓
NASA POWER Daily API [community=AG, time-standard=LST, исторические дни]
  ↓
nasa_power.py → нормализация 6 климатических параметров + проверки единиц
  ↓
Farm Observations (реальные климатические данные, soil при наличии)
  ↓
scoring.py → сопоставление с requirements 10 культур
  ↓
FastAPI → Next.js proxy → интерфейс OrbitFarm
```

Параметры в `farm.observations`:

| ID | NASA POWER key | Метод | Единица OrbitFarm |
|---|---|---|---|
| `CLIM_001` | `T2M` | средняя из ежедневных средних | °C |
| `CLIM_002` | `T2M_MIN` | минимальное значение за выбранный период | °C |
| `CLIM_003` | `T2M_MAX` | максимальное значение за выбранный период | °C |
| `CLIM_007` | `PRECTOTCORR` | сумма осадков за выбранные дни | mm per period |
| `CLIM_008` | `RH2M` | средняя относительная влажность за выбранные дни | % |
| `CLIM_009` | `ALLSKY_SFC_SW_DWN` | средняя дневная солнечная радиация | MJ/m²/day |

Для солнечной радиации конвертируем `kWh/m²/day` в `MJ/m²/day`, если именно эти единицы явно указаны ответом NASA. Единицы, которых адаптер не распознаёт, и пропуски не молча заменяются нулём. Для осадков нужно **100% покрытие ежедневными данными**, для остальных агрегатов — минимум 90%; иначе параметр пропускается с записью в `data_gaps`.

## 3. API — один запрос до всех 10 оценок

`POST http://127.0.0.1:8000/api/nasa/assess`

Тело запроса: `examples/nasa_request_beersheba_example.json`

```json
{
  "latitude": 31.25,
  "longitude": 34.79,
  "start": "2025-01-01",
  "end": "2025-03-31",
  "farm_id": "beer_sheva_region_example_not_a_field",
  "mode": "demo",
  "growth_stage": "active_growth",
  "soil_observations": []
}
```

Проверка в PowerShell (в папке `backend/`):

```powershell
$body = Get-Content 'examples/nasa_request_beersheba_example.json' -Raw
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/nasa/assess' `
    -Method Post -ContentType 'application/json' -Body $body |
    ConvertTo-Json -Depth 30
```

Результат содержит:

- `farm`: реальные климатические агрегаты, источники, период, единицы и пропуски.
- `assessment.crops`: десять культур, `demo_partial_score_0_100`, `factors`, `demo_weight_coverage`.
- `source_url` и `retrieved_from_cache`: ссылка на фактически запрошенный endpoint и использование локального кэша.
- `warnings`: объяснения ограничений.

В браузере Next.js вызывайте относительный proxy-маршрут:

```js
const response = await fetch('/api/assess', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    latitude: 31.25, longitude: 34.79,
    start: '2025-01-01', end: '2025-03-31',
    mode: 'demo', growth_stage: 'active_growth', soil_observations: []
  })
});
if (!response.ok) throw new Error(await response.text());
const {farm, assessment} = await response.json();
console.log(farm.observations, assessment.crops);
```

Браузер обращается к Next.js, а серверные proxy-маршруты — к FastAPI, поэтому CORS основному интерфейсу не нужен. В Vercel backend и frontend разворачиваются отдельными проектами; frontend получает HTTPS-адрес backend через серверную переменную `ORBITFARM_BACKEND_URL`.

FastAPI также предоставляет `GET /api/crops`, `GET /api/nasa/status` и `POST /api/assess` (готовые farm observations). Для севооборотов используются `GET /api/rotation/options` и `POST /api/rotation/compare`; Next.js проксирует их с теми же путями. Два пользовательских плана по три сезона и три демопримера работают через единый API. Существующие поля `schema_version=1.0.0`, `pipeline=orbitfarm_rotation_planner_v1`, `mode=descriptive_no_score` и статусы `unknown` сохранены; подробные тела запросов см. в корневом README.

## 4. CLI — без веб-интерфейса (из `backend/`)

```powershell
.\.venv\Scripts\python.exe main.py nasa-assess --lat 31.25 --lon 34.79 `
  --start 2025-01-01 --end 2025-03-31 --stage active_growth `
  --mode demo --output outputs/my_nasa_assessment.json
```

Вариант без предположения о стадии: убрать `--stage active_growth`. Исходный режим `python main.py demo` продолжает работать автономно на синтетическом участке. Старые `nasa`, `assess`, `merge`, `fixture` также остались доступными.

## 5. Что проверено / не проверено

**Проверено автоматически:** загрузка 10 культур; объединение climate+soil; работа scorer; валидация координат и дат; отсутствие подмены NASA на фикстуру; кэш; сезонные пропуски; строгий режим; распознавание и перевод единиц солнечной радиации; HTTP-маршруты (без внешнего доступа).

**Не проверено здесь:** успешное соединение с живым NASA POWER API, реальные значения погоды в Беэр-Шеве, точность агрономических требований, модели баланса воды, продукционный деплой. Если NASA изменит структуру ответа или единицы параметров, адаптер пропустит нераспознанный параметр вместо тихой ошибочной конверсии.

## 6. Ограничения честности модели

- `suitability_score_0_100` остаётся `null`: **настоящая пригодность пока не рассчитана**.
- `demo_partial_score_0_100` использует непроверенные интервалы из командной AgroWise и произвольные веса. Такой балл не является прогнозом урожая.
- `demo_weight_coverage` — доля использованных весов, а **не научная уверенность**.
- Одни и те же климатические даты нельзя выдавать за полноценный цикл роста каждой культуры. Для реальных рекомендаций нужны даты посадки, фазы, полив, почва, ET0/Kc и верификация диапазонов.
- POWER даёт региональную историческую оценку из климатических продуктов, не измерения на ферме. Осадки **не заменяют** доступный культуре водный баланс.

## 7. Диагностика

- `http://127.0.0.1:8000/health` — жив ли FastAPI; это **не** проверка NASA.
- `http://127.0.0.1:8000/api/crops` — все 10 культур.
- `http://127.0.0.1:8000/api/nasa/status` — описание текущей интеграции и кэша.
- `http://127.0.0.1:8000/api/rotation/options` — каталог и демопримеры севооборотов.
- Если порт занят: остановить старый сервер (Ctrl+C), новый не стартует поверх него.
- Если появится `nasa_upstream_unavailable`: интернет, DNS, доступность NASA, размер дат и метаданные ответа. **Синтетический fallback отсутствует**.
- Полный набор тестов из корня: `.\backend\.venv\Scripts\python.exe -B -m unittest discover -s backend/tests -v`.
- После production-сборки frontend: `.\backend\.venv\Scripts\python.exe -B backend/tests/smoke_local_stack.py` из корня запускает оба сервера на временных портах, проверяет HTTP-маршруты и proxy севооборотов и завершает свои процессы. Живой NASA не вызывается.

Официальные ссылки:

- https://power.larc.nasa.gov/docs/services/api/temporal/daily/
- https://power.larc.nasa.gov/docs/services/api/temporal/

Разработано как **учебный MVP** для NASA Space Apps Challenge. В FastAPI есть ограничение размера запроса и частоты NASA-запросов на экземпляр процесса, но нет аутентификации или общей распределённой квоты. Для публичного трафика нужны внешние ограничения; сохранённый диагностический `http.server` публиковать нельзя.
