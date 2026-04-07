class ApiError extends Error {
  constructor(errorObj) {
    super(errorObj.message || "API error");
    this.code = errorObj.code;
    this.detail = errorObj;
  }
}

export async function get(path, signal) {
  const response = await fetch(path, { signal });
  if (!response.ok) {
    throw new ApiError({
      code: "HTTP_ERROR",
      message: `${response.status} ${response.statusText}`,
    });
  }
  const envelope = await response.json();
  if (envelope.error) {
    throw new ApiError(envelope.error);
  }
  return envelope.data;
}
