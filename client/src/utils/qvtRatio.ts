export type QvtRatioForComparison = {
  raw_value?: number | null;
  peer_rank?: number | null;
  n_peers?: number | null;
};

export function formatQvtRatio(r?: QvtRatioForComparison): string {
  if (r?.raw_value == null) return "—";
  return `${Number(r.raw_value).toFixed(1)}${r.peer_rank ? ` (#${r.peer_rank}/${r.n_peers})` : ""}`;
}
