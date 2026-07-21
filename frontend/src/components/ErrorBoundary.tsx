import { Component, ReactNode } from "react";
import { C, mono } from "../theme";

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
          <div style={{ fontSize: 15.5, fontWeight: 600, color: C.text3, marginBottom: 8 }}>
            This screen hit an error
          </div>
          <div style={{ fontSize: 13, color: C.dim, lineHeight: 1.6, marginBottom: 14 }}>
            The rest of EchoLens is still working — pick another screen from the sidebar, or reload to
            start fresh. If it keeps happening, the detail below is what to report.
          </div>
          <pre style={{ fontFamily: mono, fontSize: 11, color: C.faint, background: C.card,
                        border: `1px solid ${C.border2}`, borderRadius: 8, padding: "10px 12px",
                        textAlign: "left", overflow: "auto", maxHeight: 140 }}>
            {error.message}
          </pre>
          <button onClick={() => window.location.reload()} className="el-btn"
            style={{ marginTop: 14, background: "transparent", color: C.accent,
                     border: `1px solid rgba(240,166,60,.4)`, borderRadius: 7,
                     padding: "9px 18px", fontSize: 13, cursor: "pointer" }}>
            Reload EchoLens
          </button>
        </div>
      </div>
    );
  }
}
