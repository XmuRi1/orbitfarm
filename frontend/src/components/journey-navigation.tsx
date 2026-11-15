"use client";

import { useEffect, useRef, useState } from "react";
import { currentJourneyStage, journeyStages } from "@/lib/result-presentation";

export default function JourneyNavigation() {
  const navigation = useRef<HTMLElement>(null);
  const [active, setActive] = useState("site");
  useEffect(() => {
    let frame = 0;
    const root = document.documentElement;
    const previousOffset = root.style.getPropertyValue("--journey-offset");
    function update() {
      frame = 0;
      const offset = (navigation.current?.getBoundingClientRect().height ?? 80) + 20;
      root.style.setProperty("--journey-offset", `${offset}px`);
      const positions = journeyStages.flatMap(stage => {
        const section = document.getElementById(stage.id);
        return section ? [{ id: stage.id, top: section.getBoundingClientRect().top }] : [];
      });
      setActive(currentJourneyStage(positions, offset, window.scrollY > 0 && window.innerHeight + window.scrollY >= root.scrollHeight - 3));
    }
    function schedule() { if (!frame) frame = requestAnimationFrame(update); }
    const resize = new ResizeObserver(schedule);
    if (navigation.current) resize.observe(navigation.current);
    // Sections grow when results/settings appear, even without a viewport resize.
    const page = navigation.current?.closest("main");
    if (page) resize.observe(page);
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    window.addEventListener("hashchange", schedule);
    schedule();
    return () => {
      cancelAnimationFrame(frame); resize.disconnect();
      window.removeEventListener("scroll", schedule); window.removeEventListener("resize", schedule); window.removeEventListener("hashchange", schedule);
      if (previousOffset) root.style.setProperty("--journey-offset", previousOffset); else root.style.removeProperty("--journey-offset");
    };
  }, []);
  return <nav ref={navigation} className="journey-nav" aria-label="Этапы анализа">
    {journeyStages.map((stage, index) => <a key={stage.id} href={`#${stage.id}`} aria-current={active === stage.id ? "step" : undefined}>
      <span className="journey-number">0{index + 1}</span><span>{stage.label}</span>
    </a>)}
  </nav>;
}
