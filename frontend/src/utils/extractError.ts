export function extractError(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    if (typeof (err as { message: unknown }).message !== "string") {
      return "Unexpected error";
    }
    return (err as { message: string }).message;
  }
  return "Unexpected error";
}
