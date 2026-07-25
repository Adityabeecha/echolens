import { useCallback, useEffect, useRef, useState } from "react";
import { Route, SCREEN_LABEL, formatRoute, parseRoute } from "./nav";

/** How the previous entry should be described on a Back control. */
export interface BackTarget {
  label: string;
  route: Route;
}

/**
 * Hash router with an in-app history stack.
 *
 * Back is the real thing: it returns you to where you actually came from, and
 * names it. Previously every case screen hardcoded "back to the Case Feed",
 * which lied whenever you'd arrived from Portfolio, Archive, Chat, Health or
 * the onboarding wizard.
 */
export function useRouter(initial: Route) {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash) ?? initial);
  // Parallel stack of where we've been. window.history can't be read back, and
  // we need the previous entry to label the Back control.
  const stack = useRef<Route[]>([]);
  // Set while we're the ones changing the hash, so the listener doesn't treat
  // our own navigation as a browser Back.
  const selfNav = useRef(false);

  useEffect(() => {
    const onPop = () => {
      const next = parseRoute(window.location.hash);
      if (!next) return;
      if (selfNav.current) {
        selfNav.current = false;
      } else {
        // Browser back/forward — keep our stack in step rather than growing it.
        stack.current.pop();
      }
      setRoute(next);
    };
    window.addEventListener("hashchange", onPop);
    return () => window.removeEventListener("hashchange", onPop);
  }, []);

  const navigate = useCallback((next: Route, opts?: { replace?: boolean }) => {
    setRoute((prev) => {
      // Tab and filter state are part of the entry: changing a filter must
      // change the URL (that is the point of putting it there), but it should
      // not push a history entry you have to press Back through five times.
      const sameEntry =
        prev.screen === next.screen &&
        prev.id === next.id &&
        prev.tab === next.tab &&
        prev.productId === next.productId &&
        formatRoute(prev) === formatRoute(next);
      if (sameEntry) return prev;
      if (opts?.replace) {
        stack.current[Math.max(0, stack.current.length - 1)] = prev;
      } else {
        stack.current.push(prev);
      }
      return next;
    });
    const url = formatRoute(next);
    selfNav.current = true;
    if (opts?.replace) window.history.replaceState(null, "", url);
    else window.history.pushState(null, "", url);
    // pushState doesn't fire hashchange; clear the guard ourselves.
    selfNav.current = false;
  }, []);

  const back = useCallback(() => {
    const prev = stack.current.pop();
    if (!prev) {
      window.history.back();
      return;
    }
    selfNav.current = true;
    window.history.replaceState(null, "", formatRoute(prev));
    selfNav.current = false;
    setRoute(prev);
  }, []);

  /**
   * Change list state (filter tab, search, severity…) without stacking history.
   *
   * Filters live in the URL so a view can be shared, but tapping through six
   * filters should not bury the screen you arrived from six presses deep.
   */
  const setParams = useCallback(
    (next: Record<string, string | null>) => {
      setRoute((prev) => {
        const params = { ...(prev.params ?? {}) };
        for (const [k, v] of Object.entries(next)) {
          if (v == null || v === "") delete params[k];
          else params[k] = v;
        }
        const updated: Route = { ...prev, params: Object.keys(params).length ? params : undefined };
        if (formatRoute(prev) === formatRoute(updated)) return prev;
        selfNav.current = true;
        window.history.replaceState(null, "", formatRoute(updated));
        selfNav.current = false;
        return updated;
      });
    },
    [],
  );

  const previous = stack.current[stack.current.length - 1];
  const backTarget: BackTarget | null = previous
    ? { label: SCREEN_LABEL[previous.screen], route: previous }
    : null;

  // Keep the address bar honest even on first paint.
  useEffect(() => {
    if (!parseRoute(window.location.hash)) {
      window.history.replaceState(null, "", formatRoute(route));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { route, navigate, back, backTarget, setParams };
}
