import { describe, expect, it } from "vitest";
import { extractError } from "../extractError";

describe("extractError", () => {
  it("returns message when object has a string message", () => {
    expect(extractError({ message: "something went wrong" })).toBe(
      "something went wrong",
    );
  });

  it('returns "Unexpected error" when message is not a string', () => {
    expect(extractError({ message: 42 })).toBe("Unexpected error");
    expect(extractError({ message: null })).toBe("Unexpected error");
    expect(extractError({ message: undefined })).toBe("Unexpected error");
    expect(extractError({ message: true })).toBe("Unexpected error");
  });

  it('returns "Unexpected error" for empty object', () => {
    expect(extractError({})).toBe("Unexpected error");
  });

  it('returns "Unexpected error" for null', () => {
    expect(extractError(null)).toBe("Unexpected error");
  });

  it('returns "Unexpected error" for undefined', () => {
    expect(extractError(undefined)).toBe("Unexpected error");
  });

  it('returns "Unexpected error" for a string', () => {
    expect(extractError("some string")).toBe("Unexpected error");
  });

  it('returns "Unexpected error" for a number', () => {
    expect(extractError(123)).toBe("Unexpected error");
  });

  it("returns message from an Error instance", () => {
    expect(extractError(new Error("fail"))).toBe("fail");
  });
});
