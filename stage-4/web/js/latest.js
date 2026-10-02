// Latest-begun wins: a slow earlier read must never overwrite the result of a later one.
export function createLatestWins() {
  let latest = 0;
  return {
    begin: () => ++latest,
    isCurrent: (token) => token === latest,
  };
}
