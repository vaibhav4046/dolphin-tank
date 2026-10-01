// Classify one HTTP exchange. Callers map timeouts and aborts to networkError, and pass
// json undefined when the body could not be parsed.
export function classify({ networkError, status, json } = {}) {
  if (networkError) return 'uncertain';
  if (!Number.isInteger(status)) return 'uncertain';
  if (status >= 200 && status < 300) {
    if (status === 204 || status === 205) return 'success';
    return json === undefined || json === null ? 'uncertain' : 'success';
  }
  if (status === 401) return 'unauthenticated';
  if (status >= 400 && status < 500) return 'refused';
  return 'uncertain';
}
