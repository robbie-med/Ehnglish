// Mirrors server/app/content.py and server/app/schemas.py.
export interface Text2 { en: string; ko: string }
export interface Timing { prep_s: number; respond_s: number; max_s: number }
export interface Item { id: string; text?: string | null; prompt?: Text2 | null; audio?: string | null; image?: string | null; timing?: Timing | null; scale?: Scale | null; target: Record<string, unknown> }
export type TaskType = 'silence' | 'read_aloud' | 'sentence_repeat' | 'quick_answer' | 'phone_call' | 'describe_opinion' | 'dictation' | 'rating' | 'typed_response';
export interface Scale { min: number; max: number; labels: Record<string, Text2> }
export interface Task { id: string; type: TaskType; title: Text2; instructions: Text2; timing: Timing; allow_rerecord: boolean; tone_hz?: number | null; target?: Record<string, unknown>; items: Item[] }
export interface Form { id: string; version: number; kind: string; title: Text2; tasks: Task[] }
export interface FormSummary { id: string; version: number; kind: string; title: Text2; task_count: number; item_count: number }

export interface TakeOut {
  id: string; session_id: string; task_id: string; item_id: string; attempt: number;
  kind: 'audio' | 'typed'; status: string; sample_rate: number | null; channels: number | null;
  duration_s: number | null; sha256: string | null; wav_path: string | null;
  quality: Record<string, unknown> | null; error: string | null; created_at: string; finalized_at: string | null;
  text?: string | null; keystroke_count?: number | null;
  events: { name: string; t_client_ms: number; meta: unknown }[];
  results: { id: string; kind: string; pipeline_version: string; result: Record<string, unknown>; created_at: string }[];
}
export interface SessionOut {
  id: string; form_id: string; form_version: number; status: string; setup: Record<string, unknown>;
  client: Record<string, unknown>; started_at: string; finished_at: string | null; takes: TakeOut[];
}
export interface UploadStatus { take_id: string; status: string; received: number[] }
export interface Keystroke { t: number; type: 'down' | 'up' | 'input'; key?: string; code?: string; len?: number }
export interface EventIn { name: string; t_client_ms: number; meta?: Record<string, unknown> }
