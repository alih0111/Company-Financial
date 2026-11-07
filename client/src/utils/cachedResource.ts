/** Share in-flight reads and short-lived results, scoped to the current session. */
export function cachedResource<T>(load: () => Promise<T>, ttl: number) {
  let cache: { key: string; at: number; value: T } | undefined;
  let pending: { key: string; promise: Promise<T> } | undefined;
  let generation = 0;
  return {
    load(key: string): Promise<T> {
      if (cache?.key === key && Date.now() - cache.at < ttl) return Promise.resolve(cache.value);
      if (pending?.key === key) return pending.promise;
      const version = ++generation;
      const promise = load().then((value) => {
        if (generation === version) cache = { key, at: Date.now(), value };
        return value;
      }).finally(() => { if (generation === version) pending = undefined; });
      pending = { key, promise };
      return promise;
    },
    invalidate() {
      generation++;
      cache = undefined;
      pending = undefined;
    },
  };
}
