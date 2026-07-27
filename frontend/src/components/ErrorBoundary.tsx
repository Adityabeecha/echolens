import { Component, ReactNode } from "react";
import { C, R, S, T, mono } from "../theme";

interface Props {
  children: ReactNode;
  /** Changing this resets the boundary — pass the current route so navigating
   *  away from a broken screen recovers instead of staying stuck. */
  resetKey?: string;
  onGoHome?: () => void;
}
interface State {
  error: Error | null;
}

/** One screen throwing used to blank the entire app. Now it's contained to the
 *  content pane: the sidebar still works, and you're told what to do. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 28 }}>
        <div style={{ maxWidth: 460, textAlign: "center" }}>
          <div style={{ fontSize: T.md, fontWeight: 600, color: C.text3, marginBottom: S[2] }}>
            This screen hit an error
          </div>
          <div style={{ fontSize: T.base, color: C.dim, lineHeight: "var(--el-lh-normal)", marginBottom: S[3] }}>
            The rest of EchoLens is still working — pick another screen from the sidebar, or reload to
            start fresh. If it keeps happening, the detail below is what to report.
          </div>
          <pre style={{ fontFamily: mono, fontSize: T.xs, color: C.faint, background: C.card,
                        border: `1px solid ${C.border2}`, borderRadius: R.control, padding: `${S[2]} ${S[3]}`,
                        textAlign: "left", overflow: "auto", maxHeight: 140 }}>
            {error.message}
          </pre>
          <div style={{ display: "flex", gap: S[2], justifyContent: "center", marginTop: S[3] }}>
            {this.props.onGoHome && (
              <button onClick={this.props.onGoHome} className="el-btn el-btn--primary"
                style={{ borderRadius: R.control,
                         padding: `${S[2]} ${S[4]}`, fontSize: T.base, fontWeight: 600 }}>
                Go to Today
              </button>
            )}
            <button onClick={() => window.location.reload()} className="el-btn"
              style={{ background: "transparent", color: C.accent,
                       border: `1px solid var(--el-accent-line)`, borderRadius: R.control,
                       padding: `${S[2]} ${S[4]}`, fontSize: T.base }}>
              Reload EchoLens
            </button>
          </div>
        </div>
      </div>
    );
  }
}
