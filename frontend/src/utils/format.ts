import type { AnalysisResult } from "../types/analysis";

const numberFormat = new Intl.NumberFormat("en-SG", { maximumFractionDigits: 1 });

export function formatNumber(value: unknown): string {
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value ?? "");
  return numberFormat.format(num);
}

export function labelCase(text: string): string {
  const spaced = text.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function parseTimestamp(value?: string): Date | null {
  if (!value) return null;
  const date = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  return Number.isNaN(date.getTime()) ? null : date;
}

export function clockTime(value?: string): string {
  const date = parseTimestamp(value);
  if (!date) return "";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function relativeTime(value?: string): string {
  const date = parseTimestamp(value);
  if (!date) return "";
  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return date.toLocaleDateString();
}

export function toCsv(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return "";
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const escape = (value: unknown) => {
    const text = value === null || value === undefined ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const body = rows.map((row) => columns.map((column) => escape(row[column])).join(","));
  return [columns.join(","), ...body].join("\n");
}

export function toMarkdown(result: AnalysisResult): string {
  const { report, summary, scope } = result;
  const lines = [
    `# ${report.title}`,
    "",
    `Query: ${result.query}`,
    `Period: ${scope.year_from}-${scope.year_to}`,
    `Written by: ${report.llm_provider} · grounding ${report.grounding.passed ? "passed" : "failed"}`,
    "",
    ...(scope.notes ?? []).flatMap((note) => [`> ${note}`, ""]),
    "## Key insights",
    ...report.insights.map((insight) => `- ${insight}`),
    "",
    "## Briefing",
    report.briefing,
    "",
    "## Metrics",
    "| Metric | Value | Detail |",
    "| --- | --- | --- |",
    ...summary.metrics.map((metric) => `| ${metric.label} | ${formatNumber(metric.value)}${metric.unit} | ${metric.detail} |`),
  ];
  if (summary.correlations?.length) {
    lines.push("", "## Correlations", "| Series | Compared with | r | Periods |", "| --- | --- | --- | --- |");
    lines.push(...summary.correlations.map((item) => `| ${item.a} | ${item.b} | ${item.r} | ${item.periods} |`));
  }
  lines.push("", "## Data quality");
  for (const dataset of result.datasets) {
    lines.push(`- ${dataset.title ?? dataset.source} (${dataset.mode}): ${(dataset.quality.checks ?? []).join(" ")}`);
  }
  lines.push("", "## Sources", ...report.citations.map((citation, index) => `${index + 1}. ${citation}`));
  return lines.join("\n");
}

export function downloadFile(content: string, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
