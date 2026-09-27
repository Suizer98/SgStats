export type AgentEvent = {
  id?: number;
  agent?: string;
  step: string;
  content?: string;
  created_at?: string;
  result?: AnalysisResult;
};

export type ChartSeries = {
  key: string;
  label: string;
};

export type ChartSpec = {
  id: string;
  title: string;
  subtitle: string;
  type: string;
  xKey: string;
  xLabel: string;
  yLabel: string;
  unit: string;
  series: ChartSeries[];
  data: Record<string, string | number>[];
};

export type Metric = {
  label: string;
  value: number;
  unit: string;
  detail: string;
  change?: number | null;
};

export type PlanItem = {
  provider: string;
  id: string;
  title: string;
  agency: string;
  coverage: string;
  score: number;
};

export type Outlier = {
  series: string;
  period: string;
  value: number;
};

export type Quality = {
  ok: boolean;
  rows: number;
  missing_columns: string[];
  nulls: Record<string, number>;
  duplicates_removed?: number;
  series?: number;
  periods?: number;
  coverage?: string;
  outliers?: Outlier[];
  checks?: string[];
};

export type Correlation = {
  a: string;
  b: string;
  r: number;
  periods: number;
  strength: string;
};

export type Dataset = {
  provider?: string;
  dataset_id?: string;
  title?: string;
  source: string;
  format: string;
  citation: string;
  mode: string;
  grain?: string;
  note?: string;
  quality: Quality;
  records: Record<string, unknown>[];
};

export type AnalysisResult = {
  kind?: "chat" | "data";
  query: string;
  scope: {
    year_from: number;
    year_to: number;
    sector: string | null;
    notes?: string[];
  };
  plan?: PlanItem[];
  datasets: Dataset[];
  summary: {
    metrics: Metric[];
    charts: ChartSpec[];
    correlations?: Correlation[];
  };
  report: {
    title: string;
    insights: string[];
    briefing: string;
    citations: string[];
    llm_provider: string;
    llm_providers?: string[];
    llm_usage?: {
      input_tokens: number;
      output_tokens: number;
      seconds: number;
    };
    llm_error?: string;
    grounding: {
      passed: boolean;
      unsupported_numbers: number[];
    };
  };
};

export type AnalysisRow = {
  id: string;
  conversation_id: string;
  query: string;
  status: string;
  created_at: string;
  result: AnalysisResult | null;
  error?: string | null;
  events: AgentEvent[];
};

export type CreatedAnalysis = {
  id: string;
  conversation_id: string;
  status: string;
};

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  analyses: AnalysisRow[];
};
