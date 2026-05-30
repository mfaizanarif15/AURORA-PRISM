import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { AuthSession, EpisodeEvent } from "./types";

class MockEventSource {
  static instances: MockEventSource[] = [];

  onopen: (() => void) | null = null;
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

  emitEpisode(event: EpisodeEvent) {
    const payload = new MessageEvent("episode", { data: JSON.stringify(event) });
    this.listeners.get("episode")?.forEach((listener) => listener(payload));
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
    expect(await screen.findByText("PRISM Board")).toBeInTheDocument();
  });

  it("removes completed SSE events from the operation progress UI", async () => {
    storeTestSession();
    vi.stubGlobal("EventSource", MockEventSource);
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
        if (url.includes("/clips")) {
          return {
            ok: true,
            json: async () => []
          };
        }

        return {
          ok: true,
          json: async () => [
            {
              id: "episode-1",
              title: "SSE Test Episode",
              guest_name: "Demo Guest",
              status: "draft",
              clip_count: 0,
              asset_count: 0,
              media_asset_count: 0,
              transcript_segment_count: 0
            }
          ]
        };
      })
    );

    render(<App />);

    await waitFor(() => expect(MockEventSource.instances).toHaveLength(1));

    act(() => {
      MockEventSource.instances[0].emitEpisode({
        id: 1,
        episode_id: "episode-1",
        event_type: "analysis.requested",
        message: "Analysis request received",
        level: "info",
        progress: 5,
        data: {},
        created_at: "2026-05-31T00:00:00.000Z"
      });
    });

    expect(await screen.findByText("Analysis request received")).toBeInTheDocument();

    act(() => {
      MockEventSource.instances[0].emitEpisode({
        id: 2,
        episode_id: "episode-1",
        event_type: "analysis.completed",
        message: "Analysis completed with 3 clips",
        level: "success",
        progress: 100,
        data: { analysis_run_id: "analysis-1", generated_clip_count: 3 },
        created_at: "2026-05-31T00:00:01.000Z"
      });
    });

    expect(screen.queryByText("Analysis completed with 3 clips")).not.toBeInTheDocument();
    expect(screen.queryByText("Analysis request received")).not.toBeInTheDocument();
  });
});

const testSession: AuthSession = {
  access_token: "test-token",
  token_type: "bearer",
  expires_at: 9999999999,
  user: {
    id: "user-1",
    username: "operator",
    display_name: "Operator One",
    role: "Reviewer"
  }
};

function storeTestSession() {
  window.localStorage.setItem("aurora-prism:auth-session", JSON.stringify(testSession));
}
