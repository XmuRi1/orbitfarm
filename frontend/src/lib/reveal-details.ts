type LinkActivation = Pick<MouseEvent, "button" | "ctrlKey" | "metaKey" | "shiftKey" | "altKey" | "defaultPrevented" | "preventDefault">;

/** Reveal existing controls, then navigate after layout settles; never edits form state. */
export function revealDetailsFromLink(event: LinkActivation, targetId: string) {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const target = document.getElementById(targetId);
  if (!(target instanceof HTMLDetailsElement)) return; // Keep the native href fallback.
  event.preventDefault();
  target.open = true;
  const hash = `#${targetId}`;
  if (window.location.hash !== hash) window.history.pushState(null, "", hash);
  target.querySelector<HTMLElement>(":scope > summary")?.focus({ preventScroll: true });
  requestAnimationFrame(() => {
    if (target.isConnected) target.scrollIntoView({ block: "start", behavior: "auto" });
  });
}
