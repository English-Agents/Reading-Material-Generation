import axios from "axios";

// In production (Render static site), point at the deployed API URL.
// In development, "/" is proxied to localhost:8000 by Vite.
const BASE_URL = import.meta.env.VITE_API_URL ?? "/";

export const api = axios.create({ baseURL: BASE_URL });

// ── Types ─────────────────────────────────────────────────────────────────────

export interface SlideGenResult {
  generation_id: string;
  slide_index: number;
  skill_type: string;
  status: string;
  slide_title: string | null;
}

export interface GenerateResponse {
  deck_id: string;
  slide_count: number;
  deck_generation_id: string;
}

export interface Generation {
  generation_id: string;
  deck_id: string;
  slide_index: number;
  skill_type: string;
  status: string;
  eval_score: number | null;
  token_cost_usd: number | null;
  output_text: string | null;
  created_at: string | null;
}

export interface SkillStats {
  skill_type: string;
  total_generations: number;
  approved: number;
  rejected: number;
  needs_repair: number;
  avg_eval_score: number | null;
  avg_cost_usd: number | null;
  active_prompt_version: string | null;
}

export interface DashboardResponse {
  as_of: string;
  skills: SkillStats[];
  open_alerts: number;
  repair_queue_depth: number;
}

export interface AlertItem {
  id: string;
  alert_type: string;
  skill_type: string | null;
  message: string;
  created_at: string;
}

export interface RepairQueueItem {
  id: string;
  generation_id: string;
  skill_type: string;
  deck_id: string;
  retry_count: number;
  last_error: string | null;
  status: string;
  created_at: string;
}

export interface FeedbackSignal {
  signal_type: string;
  severity: number;
  section_id?: string;
  reviewer_note?: string;
}

export interface SourceContentItem {
  id: string;
  deck_id: string;
  topic_label: string;
  passage_text: string;
  source_title: string | null;
  page_ref: string | null;
  author: string | null;
  alignment_score: number | null;
  alignment_verdict: "pass" | "warn" | "fail" | null;
  char_count: number;
  created_at: string;
}

export interface SourceContentListResponse {
  passages: SourceContentItem[];
  total_chars: number;
  budget_chars: number;
  budget_remaining: number;
}

export interface PassageValidationResult {
  passage_id: string;
  source_title: string;
  alignment_score: number;
  verdict: "pass" | "warn" | "fail";
  reason: string;
}

export interface ValidationResponse {
  topic_id: string;
  topic_text: string;
  overall_verdict: "pass" | "warn" | "fail";
  overall_score: number;
  threshold: number;
  passage_results: PassageValidationResult[];
  generation_blocked: boolean;
  message: string;
}

// ── API calls ─────────────────────────────────────────────────────────────────

export const generateFromFile = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<GenerateResponse>("/generate/file", form);
};

export const generateFromUrl = (url: string) =>
  api.post<GenerateResponse>("/generate/url", { url });

export const listGenerations = (params: {
  deck_id?: string;
  status?: string;
  skill_type?: string;
  skip?: number;
  limit?: number;
}) => api.get<Generation[]>("/generate/generations", { params });

export const approveGeneration = (
  id: string,
  reviewer_id: string,
  eval_score?: number
) =>
  api.post(`/review/${id}/approve`, { reviewer_id, eval_score });

export const rejectGeneration = (
  id: string,
  reviewer_id: string,
  signals: FeedbackSignal[]
) =>
  api.post(`/review/${id}/reject`, { reviewer_id, signals });

export const postFeedback = (
  id: string,
  reviewer_id: string,
  signals: FeedbackSignal[]
) =>
  api.post(`/review/${id}/feedback`, { reviewer_id, signals });

export const getDashboard = () =>
  api.get<DashboardResponse>("/ops/dashboard");

export const getAlerts = (resolved = false) =>
  api.get<AlertItem[]>("/ops/alerts", { params: { resolved } });

export const resolveAlert = (id: string) =>
  api.post(`/ops/alerts/${id}/resolve`);

export const getRepairQueue = () =>
  api.get<RepairQueueItem[]>("/review/repair-queue");

export const exportDeck = (deck_id: string, format: string) =>
  api.post(`/export/${deck_id}`, { format }, { responseType: "blob" });

// ── Source Content ─────────────────────────────────────────────────────────────

export const addSourcePassage = (
  deck_id: string,
  data: {
    topic_label: string;
    passage_text: string;
    source_title?: string;
    page_ref?: string;
    author?: string;
    uploaded_by?: string;
  }
) => api.post<SourceContentItem>(`/source-content/${deck_id}`, data);

export const listSourcePassages = (deck_id: string) =>
  api.get<SourceContentListResponse>(`/source-content/${deck_id}`);

export const deleteSourcePassage = (deck_id: string, passage_id: string) =>
  api.delete(`/source-content/${deck_id}/${passage_id}`);

export const validateSourcePassages = (
  deck_id: string,
  topic_text: string,
  override_warn = false
) =>
  api.post<ValidationResponse>(`/source-content/${deck_id}/validate`, {
    topic_text,
    override_warn,
  });
