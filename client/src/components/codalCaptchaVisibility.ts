/**
 * Whether a captcha panel is currently rendered inside one of the modals.
 *
 * The global watcher shows a floating panel only when no modal already shows the
 * same challenge, so the operator never sees two inputs for one captcha.
 */
let mounted = 0;
const listeners = new Set<() => void>();

export function setCaptchaPanelMounted(isMounted: boolean): void {
  mounted = Math.max(0, mounted + (isMounted ? 1 : -1));
  listeners.forEach((listener) => listener());
}

export function getCaptchaPanelCount(): number {
  return mounted;
}

export function subscribeCaptchaPanel(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
