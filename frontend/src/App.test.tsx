import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

describe("App", () => {
  it("renders the dashboard shell", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => []
      }))
    );
    render(<App />);
    expect(await screen.findByText("AURORA PRISM")).toBeInTheDocument();
    expect(screen.getByText("PRISM Board")).toBeInTheDocument();
  });
});
