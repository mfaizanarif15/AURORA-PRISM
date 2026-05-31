import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { AnalysisEvent, AuthSession } from "./types";

class MockEventSource {
  static instances: MockEventSource[] = [];
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener as (event: MessageEvent<string>) => void);
    this.listeners.set(type, listeners);
  }

  close = vi.fn();

  emitAnalysis(event: AnalysisEvent) {
    const payload = new MessageEvent("analysis", { data: JSON.stringify(event) });
    this.listeners.get("analysis")?.forEach((listener) => listener(payload));
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  MockEventSource.instances = [];
});

describe("App", () => {
  it("renders the login screen before authentication", async () => {
    render(<App />);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("renders the dashboard shell for an authenticated session", async () => {
    storeTestSession();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/auth/me")) {
          return {
            ok: true,
            json: async () => testSession.user
          };
        }
        return {
          ok: true,
          json: async () => []
        };
      })
    );
    render(<App />);
    expect(await screen.findByText("Outputs")).toBeInTheDocument();
    expect(screen.getByText("Output Sections")).toBeInTheDocument();
    expect(screen.getByText("30-60s")).toBeInTheDocument();
    expect(screen.getByText("3-6m")).toBeInTheDocument();
    expect(screen.getByLabelText("TikTok enabled")).not.toBeChecked();
    expect(screen.getByLabelText("Reels enabled")).not.toBeChecked();
    expect(screen.getByLabelText("TikTok min seconds")).toHaveValue(30);
    expect(screen.getByLabelText("TikTok max seconds")).toHaveValue(60);
    expect(screen.getByLabelText("TikTok count")).toHaveValue(3);
    fireEvent.change(screen.getByLabelText("TikTok min seconds"), { target: { value: "" } });
    expect(screen.getByLabelText("TikTok min seconds")).toHaveValue(null);
  });

  it("shows analysis SSE progress only after Run Analysis is clicked", async () => {
    storeTestSession();
    vi.stubGlobal("EventSource", MockEventSource);
    vi.stubGlobal("fetch", vi.fn(fetchForAnalyzableEpisode));

    render(<App />);

    expect(screen.queryByText("Running section specialists")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByLabelText("TikTok enabled"));
    fireEvent.click(await screen.findByRole("button", { name: "Run Analysis" }));

    expect(await screen.findByText("Starting analysis")).toBeInTheDocument();
    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));
    expect(MockEventSource.instances[0].url).toContain("/episodes/episode-1/analysis-events");

    act(() => {
      MockEventSource.instances[0].emitAnalysis({
        id: 2,
        episode_id: "episode-1",
        event_type: "analysis.section_specialists",
        message: "Running section specialists",
        level: "info",
        progress: 55,
        data: {},
        created_at: new Date().toISOString()
      });
    });

    expect(await screen.findByText("Running section specialists")).toBeInTheDocument();
    expect(screen.getByText("55%")).toBeInTheDocument();
  });
});

const testSession: AuthSession = {
  access_token: "test-token",
  token_type: "bearer",
  expires_at: 9999999999,
  user: {
    id: "user-1",
    username: "operator",
    display_name: "Operator One"
  }
};

function storeTestSession() {
  window.localStorage.setItem("aurora-prism:auth-session", JSON.stringify(testSession));
}

async function fetchForAnalyzableEpisode(input: RequestInfo | URL, init?: RequestInit) {
  const url = String(input);
  if (url.includes("/auth/me")) {
    return jsonResponse(testSession.user);
  }
  if (url.includes("/episodes/episode-1/analyze") && init?.method === "POST") {
    return jsonResponse({
      id: "analysis-1",
      episode_id: "episode-1",
      status: "completed",
      mode: "hybrid",
      summary: "Done",
      generated_clip_count: 0
    });
  }
  if (url.includes("/clips")) {
    return jsonResponse([]);
  }
  if (url.includes("/episodes")) {
    return jsonResponse([
      {
        id: "episode-1",
        title: "Analyzable Episode",
        guest_name: "Demo Guest",
        status: "draft",
        clip_count: 0,
        asset_count: 0,
        media_asset_count: 0,
        transcript_segment_count: 12
      }
    ]);
  }
  return jsonResponse({});
}

function jsonResponse(value: unknown) {
  return {
    ok: true,
    json: async () => value,
    text: async () => JSON.stringify(value),
    statusText: "OK"
  } as Response;
}
