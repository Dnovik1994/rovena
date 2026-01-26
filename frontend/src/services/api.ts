const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

export interface ApiError {
  code: string;
  message: string;
}

export const parseApiError = async (response: Response): Promise<ApiError> => {
  try {
    const data = (await response.json()) as { error?: ApiError };
    if (data.error) {
      return data.error;
    }
  } catch (error) {
    return { code: String(response.status), message: "Unexpected error" };
  }
  return { code: String(response.status), message: response.statusText };
};

export const apiFetch = async <T>(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<T> => {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    throw await parseApiError(response);
  }

  return (await response.json()) as T;
};
