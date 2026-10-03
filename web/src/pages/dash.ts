/** Types and helpers shared by the dashboard and the sitting page. Mirrors routers/dashboard.py. */

export interface Latest { value: number | null; n: number; ci95: [number, number] | null; anchor: number | null; pct_of_anchor: number | null; scale: number | null; session_id: string; form_id: string; started_at: string }
export interface Point { session_id: string; form_id: string; started_at: string; value: number; ci95: [number, number] | null; scale: number | null }
export interface Metric { id: string; unit: string; direction: 'higher' | 'lower' | 'none'; definition: { en: string; ko: string }; latest: Latest; trend: { points: Point[]; change: number | null; detectable: boolean | null } | null }
export interface Estimate { skill: string; cefr: string | null; toefl: [number, number] | null; ielts: [number, number] | null; based_on: { metric: string; value: number; level: string }[]; spread?: number; label: string; form_id?: string }
export interface SessionRow { id: string; form_id: string; form_kind: string; status: string; started_at: string; finished_at: string | null; takes: number; items_total: number | null; items_done: number; processed: number; headphone_override: boolean; mic: string | null }
export interface DashboardData {
  subject: { email: string; role: string };
  viewer: { email: string; role: string };
  sessions: SessionRow[];
  domains: Record<string, Metric[]>;
  estimates: Estimate[];
  anchors_available: Record<string, boolean>;
  per_session: { session: SessionRow; metrics: Record<string, Latest>; estimates: Estimate[] }[];
  costs: { sessions: Record<string, { total_usd: number; by_engine: Record<string, { cost_usd: number; calls: number; units: Record<string, number> }> }>; all_time: { total_usd: number; by_engine: Record<string, number> } } | null;
}

export const DOMAIN_ORDER = ['speaking', 'listening', 'reading', 'writing', 'vocabulary', 'self'];
/** Session-quality metrics are shown one row per sitting rather than as trends. */
export const QUALITY = ['noise_floor_dbfs', 'headphone_leak_db', 'clipped_takes', 'transcript_agreement', 'completion_pct'] as const;

export function fmt(v: number | null | undefined, unit = ''): string {
  if (v === null || v === undefined) return '—';
  const s = Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
  return unit ? `${s} ${unit}` : s;
}
