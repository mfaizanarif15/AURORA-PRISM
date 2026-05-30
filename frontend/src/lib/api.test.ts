import { describe, expect, it } from "vitest";
import { apiErrorMessage } from "./api";

describe("apiErrorMessage", () => {
  it("formats FastAPI validation errors", () => {
    const raw = JSON.stringify({
      detail: [
        {
          type: "string_too_short",
          loc: ["body", "password"],
          msg: "String should have at least 8 characters",
          ctx: { min_length: 8 }
        }
      ]
    });

    expect(apiErrorMessage(raw)).toBe("Password must be at least 8 characters.");
  });

  it("formats plain backend detail messages", () => {
    expect(apiErrorMessage(JSON.stringify({ detail: "Username already exists" }))).toBe(
      "Username already exists"
    );
  });
});
