"use client";

import { ArrowRight, Check, LoaderCircle } from "lucide-react";

export default function FirstRunExperience({ open, onOpen, accepted, onAccepted, onStart, loading, progress, error }: {
  open: boolean; onOpen: (open: boolean) => void; accepted: boolean; onAccepted: (accepted: boolean) => void;
  onStart: () => void; loading: boolean; progress: string; error: string;
}) {
  const complete = !loading && !error && progress === "Пример рассчитан";
  return <section id="first-run" className="first-run" aria-labelledby="first-run-heading">
    <div><p className="eyebrow">С ЧЕГО НАЧАТЬ</p><h2 id="first-run-heading">Посмотрите пример или выберите свой участок</h2><p>OrbitFarm покажет историческую погоду, условную потребность в воде и различия двух планов севооборота.</p></div>
    <div className="first-run-actions">
      {complete ? <><a className="rotation-compare-button" href="#climate-water">Посмотреть готовые результаты <ArrowRight size={16} /></a><button className="rotation-examples-button" type="button" onClick={() => onOpen(true)}>Повторить пример</button></> : <button className="rotation-compare-button" type="button" onClick={() => onOpen(true)}>Попробовать на примере Беэр-Шевы <ArrowRight size={16} /></button>}
      <a className="own-site-link" href="#site">Выбрать свой участок <ArrowRight size={15} /></a>
    </div>
    <details className="provenance-details demo-consent" open={open} onToggle={(event) => onOpen(event.currentTarget.open)}>
      <summary>Что используется в примере</summary>
      <div className="season-detail-body">
        <p className="demo-brief"><strong>Беэр-Шева · пшеница · январь–март 2025</strong><span>Реальная историческая погода NASA POWER. Высота 288 м — оценка SRTM v3; Kc, почва и три полива по 25 мм — тестовые предположения.</span></p>
        <p className="field-hint">Это учебный сценарий, не измерения параметров поля или агрономическая рекомендация. Все исходные значения доступны ниже.</p>
        <details className="provenance-details demo-expert"><summary>Все параметры, источники и допущения примера</summary><div className="season-detail-body"><ul className="demo-input-list">
          <li><strong>Участок и культура:</strong> 31.25, 34.79 · 01.01–31.03.2025 · пшеница (wheat).</li>
          <li><strong>Высота:</strong> 288 м, оценка SRTM v3, не геодезический замер. <a href="https://www.opentopodata.org/datasets/srtm/" target="_blank" rel="noreferrer">Источник SRTM v3</a>.</li>
          <li><strong>Культура:</strong> пользовательские Kc 0.3 / 1.1 / 0.4; четыре фазы 20 / 25 / 25 / 20 дней.</li>
          <li><strong>Почва:</strong> θFC=0.30, θWP=0.12 м³/м³; Zr=0.6 м, p=0.5; начальное истощение Dr=27 мм.</li>
          <li><strong>Полив B:</strong> по 25 мм чистой глубины 15 января, 15 февраля и 15 марта. Сценарий A — без полива.</li>
        </ul>
        <p className="field-hint">Kc, почва, корни, начальное состояние и поливы — тестовые предположения, не измерения. В почвенной модели сток и капиллярный подъём равны нулю, осадки полностью инфильтрируются; дождь/полив — до ET, остаточный дренаж — после ET в тот же день.</p>
        </div></details>
        <label className="water-check demo-confirmation"><input type="checkbox" checked={accepted} disabled={loading} onChange={(event) => onAccepted(event.target.checked)} /><span>Подтверждаю источник оценочной высоты и все перечисленные демонстрационные допущения. Понимаю, что они не являются измеренными параметрами участка или агрономическими рекомендациями.</span></label>
        <button className={complete ? "rotation-examples-button" : "rotation-compare-button"} type="button" disabled={!accepted || loading} onClick={onStart}>{loading ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}{loading ? progress || "Запускаем пример…" : complete ? "Повторно рассчитать подтверждённый пример" : "Запустить подтверждённый пример"}</button>
        {!accepted && <p className="field-hint">Для запуска отметьте подтверждение выше. Настройки своего участка можно вводить без запуска примера.</p>}
        {loading && <p className="field-hint" role="status">{progress} · результаты появятся по мере готовности.</p>}
        {!loading && progress === "Пример рассчитан" && <p className="calculation-state" role="status">Пример рассчитан. <a href="#climate-water">Посмотреть климат и воду</a> · <a href="#analysis-summary">Перейти к итогам</a>. Все исходные настройки доступны для просмотра и изменения.</p>}
        {error && <p className="error-message" role="alert">{error}</p>}
      </div>
    </details>
  </section>;
}
