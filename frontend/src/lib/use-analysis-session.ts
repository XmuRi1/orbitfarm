"use client";

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { AnalysisSession } from "./analysis-session";

export function useAnalysisSession<T>(scope: string) {
  // A new scope has an empty snapshot immediately, before effects run.
  const session = useMemo(() => new AnalysisSession<T>(scope), [scope]);
  const snapshot = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);
  useEffect(() => () => session.cancel(), [session]);
  return { ...snapshot, run: session.run.bind(session), reset: session.reset };
}
