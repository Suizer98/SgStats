export const sampleQueries = [
  "How many total EP workers in Singapore from 2020 to current",
  "How has CPI inflation changed since 2019",
  "HDB resale prices from 2015 to 2024",
  "Births and fertility trends in Singapore",
  "Analyse employment trends in the technology sector from 2020-2024",
];

export const sampleQuery = sampleQueries[0];

export const agentOrder = ["coordinator", "extractor", "analytics"];

export const agentBlurb: Record<string, string> = {
  general: "Handles ordinary conversation when the message is not asking for statistics",
  coordinator: "Searches Data.gov.sg, SingStat and the mock internal database, then plans which datasets answer the question",
  extractor: "Fetches each dataset through the MCP tools and normalises its periods and series",
  analytics: "Computes trends and drafts the grounded briefing",
};
