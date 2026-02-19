export function extractError(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return (err as { message: string }).message;
  }
  return "Unexpected error";
}
