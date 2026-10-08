import { useEffect, useState } from "react";

// The shape of the JSON that /health/ready returns
type ReadyResponse = {
  status: "ok" | "degraded";
  checks: Record<string, "ok" | "error">;
};

// Everything the component can be showing
type State =
  | { kind: "loading" }
  | { kind: "loaded"; data: ReadyResponse }
  | { kind: "unreachable" };

export default function HealthStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    async function load() {
      try {
        const response = await fetch("/api/health/ready", {
          signal: controller.signal,
        });
        if (response.status !== 200 && response.status !== 503) {
          setState({ kind: "unreachable" });
          return;
        }
        const data: ReadyResponse = await response.json();
        setState({ kind: "loaded", data });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }
        setState({ kind: "unreachable" });
      }
    }

    load();

    return () => controller.abort();
  }, []);

  if (state.kind === "loading") {
    return <p>Checking system status…</p>;
  }
  if (state.kind === "unreachable") {
    return <p>Can't reach the API</p>;
  }
  if (state.kind === "loaded") {
    return (
      <div>
        <p
          style={{
            color: state.data.status === "ok" ? "green" : "red",
          }}
        >
          Overall status: {state.data.status}
        </p>
        <ul>
          {Object.entries(state.data.checks).map(([name, result]) => (
            <li key={name}>
              {name}: {result}
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return null;
}
