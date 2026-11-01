// The document app/reports/document.py builds. Keep the two in step.

export type Brand = {
  name: string; is_you: boolean; color: string; mention: number; recommend: number; range: string;
  avg_rank: number | null; sov: number; score: number; wins: number;
};

export type Stage = {
  key: string; label: string; desc: string; color: string; count: number; open: number; you: number;
  segments: { name: string; count: number; color: string }[]; wins: Record<string, number>;
};

export type QuestionRow = {
  n: number; text: string; stage: string; you: "PICKED" | "NAMED" | "MISSING"; picked: string[]; open: boolean;
  why?: string; priority?: string;
};

export type Doc = {
  estimate_note: string;
  brand: string; website: string; category: string; country: string; scan_no: number; baseline: boolean;
  scan_date: string; generated: string; engines: string[]; questions: number; answers: number; answers_expected: number;
  competitors: number; you: Brand; leader: Brand | null; brands: Brand[]; by_score: Brand[]; open_count: number;
  score: number; score_label: string;
  summary: { lead: string; body: string }[];
  findings: { lead: string; body: string }[];
  do_first: { title: string; detail: string } | null;
  metrics: { name: string; you: string; range: string; delta: number | null; leader: string; measures: string }[];
  gaps: { name: string; you: number; leader: number }[];
  engine_rows: { name: string; type: string; scanned: boolean; answers?: number; mention?: string; recommend?: string; cited?: string }[];
  web_scanned: boolean;
  stages: Stage[];
  open_rows: QuestionRow[]; open_more: number;
  question_rows: QuestionRow[]; questions_per_page: number; grid_brands: Brand[];
  stage_labels: Record<string, string>;
  competitor_why: { name: string; color: string; wins: number; items: { title: string; detail: string; stated: boolean }[]; quote: string | null }[];
  claims: { claim: string; competitor: string; page: string }[];
  sources: { domain: string; citations: number; with_you: number; owner: string | null; source_type: string | null }[];
  actions: { title: string; detail: string; targets: string; impact: string; effort: string; when: string; start: number; length: number }[];
  goals: { metric: string; today: string; d30: string; d90: string; values: number[] | null; where: string }[];
  next_setup: { big: string; title: string; detail: string }[];
  toc: { n: string; title: string; desc: string; page: number }[];
};
