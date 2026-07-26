import { useEffect, useRef, useState } from "react";
import { C, R, S, T } from "../theme";

/**
 * Google Sign-In, rendered by Google Identity Services.
 *
 * The script is loaded on demand rather than from index.html, so a deployment
 * with no Google client id never talks to Google at all — no third-party
 * request on a page that will not use it.
 *
 * The button Google draws is theirs by requirement (their branding guidelines
 * forbid a custom-drawn "Sign in with Google" control), so it is configured to
 * their dark filled style to sit in this UI rather than fought with CSS.
 */

const SRC = "https://accounts.google.com/gsi/client";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (o: Record<string, unknown>) => void;
          renderButton: (el: HTMLElement, o: Record<string, unknown>) => void;
        };
      };
    };
  }
}

let loading: Promise<void> | null = null;

/** Load the GIS script once, no matter how many components ask. */
function loadScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (loading) return loading;
  loading = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${SRC}"]`);
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("blocked")));
      return;
    }
    const s = document.createElement("script");
    s.src = SRC;
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    // Ad blockers and strict privacy extensions block this host. That must
    // degrade to "the button is not there", never to a broken screen.
    s.onerror = () => {
      loading = null;
      reject(new Error("blocked"));
    };
    document.head.appendChild(s);
  });
  return loading;
}

export function GoogleButton({
  clientId,
  onCredential,
  disabled,
}: {
  clientId: string;
  onCredential: (credential: string) => void;
  disabled?: boolean;
}) {
  const host = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);
  // The callback must not be stale by the time Google invokes it, and
  // re-running initialize on every render would re-draw the button.
  const cb = useRef(onCredential);
  cb.current = onCredential;

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;

    loadScript()
      .then(() => {
        if (cancelled || !host.current || !window.google) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: (res: { credential?: string }) => {
            if (res?.credential) cb.current(res.credential);
          },
        });
        window.google.accounts.id.renderButton(host.current, {
          theme: "filled_black",
          size: "large",
          text: "signin_with",
          shape: "rectangular",
          logo_alignment: "left",
          width: 320,
        });
      })
      .catch(() => !cancelled && setFailed(true));

    return () => {
      cancelled = true;
    };
  }, [clientId]);

  if (!clientId) return null;

  if (failed) {
    return (
      <div
        style={{
          fontSize: T.sm,
          color: C.dim,
          border: `1px dashed ${C.border3}`,
          borderRadius: R.control,
          padding: `${S[2]} ${S[3]}`,
          lineHeight: "var(--el-lh-snug)",
        }}
      >
        Google sign-in could not load — an ad blocker or privacy extension is
        usually the cause. Use email and password below, or continue as a guest.
      </div>
    );
  }

  return (
    <div
      ref={host}
      // Google renders its own button here; while it is in flight the box keeps
      // its height so the form does not jump when it appears.
      style={{
        minHeight: 40,
        display: "flex",
        justifyContent: "center",
        opacity: disabled ? 0.5 : 1,
        pointerEvents: disabled ? "none" : "auto",
      }}
    />
  );
}
