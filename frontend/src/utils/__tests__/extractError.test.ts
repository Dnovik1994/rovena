import { describe, expect, it } from "vitest";
import { extractError } from "../extractError";

describe("extractError", () => {
  it("returns message when object has a string message", () => {
    expect(extractError({ message: "something went wrong" })).toBe(
      "something went wrong",
    );
  });

  it("returns message value as-is when message is not a string", () => {
    // The function casts to { message: string } without validating the type,
    // so a non-string value passes through unchanged.
    expect(extractError({ message: 42 })).toBe(42);
    expect(extractError({ message: null })).toBeNull();
    expect(extractError({ message: undefined })).toBeUndefined();
    expect(extractError({ message: true })).toBe(true);
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
