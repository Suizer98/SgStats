import { useState } from "react";
import {
  Box,
  Button,
  ButtonGroup,
  Flex,
  Text,
  useColorModeValue,
} from "@chakra-ui/react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ChartSeries, ChartSpec } from "../../types/analysis";
import { formatNumber, labelCase } from "../../utils/format";

const chartTypes = ["line", "area", "bar"] as const;
type ChartType = (typeof chartTypes)[number];

const lightPalette = ["#2b6cb0", "#c05621", "#2f855a", "#6b46c1", "#b7791f", "#b83280"];
const darkPalette = ["#63b3ed", "#f6ad55", "#68d391", "#b794f4", "#f6e05e", "#f687b3"];
const legendLimit = 36;

type LegacyChart = Partial<ChartSpec> & { dataKey?: string; series?: (ChartSeries | string)[] };

// Analyses saved before chart specs carried series labels still render.
function seriesOf(chart: LegacyChart): ChartSeries[] {
  if (chart.series?.length) {
    return chart.series.map((item) =>
      typeof item === "string" ? { key: item, label: item } : item,
    );
  }
  return chart.dataKey ? [{ key: chart.dataKey, label: chart.title ?? chart.dataKey }] : [];
}

function shorten(text: string): string {
  return text.length > legendLimit ? `${text.slice(0, legendLimit - 1)}…` : text;
}

export function ChartBlock({ chart }: { chart: ChartSpec }) {
  const legacy = chart as LegacyChart;
  const initial = chartTypes.includes(chart.type as ChartType)
    ? (chart.type as ChartType)
    : "line";
  const [type, setType] = useState<ChartType>(initial);
  const data = chart.data;
  const series = seriesOf(legacy);
  const xKey = chart.xKey || "year";
  const unit = chart.unit ?? "";
  const title = chart.subtitle === undefined ? labelCase(chart.title) : chart.title;
  const fillId = `fill-${String(chart.id).replace(/[^a-zA-Z0-9_-]/g, "-")}`;

  // Recharts renders raw SVG, so colours come from the color mode rather than tokens.
  const gridStroke = useColorModeValue("#edf2f7", "#2d3748");
  const tickFill = useColorModeValue("#4a5568", "#a0aec0");
  const palette = useColorModeValue(lightPalette, darkPalette);
  const tooltipBg = useColorModeValue("#ffffff", "#2d3748");
  const tooltipBorder = useColorModeValue("#e2e8f0", "#4a5568");
  const tooltipText = useColorModeValue("#1a202c", "#f7fafc");

  const colorFor = (index: number) => palette[index % palette.length];
  const withUnit = (value: unknown) => `${formatNumber(value)}${unit}`;
  const margin = { top: 4, right: 8, bottom: chart.xLabel ? 18 : 4, left: chart.yLabel ? 12 : 0 };

  const axes = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
      <XAxis
        dataKey={xKey}
        tick={{ fontSize: 11, fill: tickFill }}
        stroke={gridStroke}
        minTickGap={16}
        label={
          chart.xLabel
            ? { value: chart.xLabel, position: "insideBottom", offset: -12, fontSize: 11, fill: tickFill }
            : undefined
        }
      />
      <YAxis
        tick={{ fontSize: 11, fill: tickFill }}
        stroke={gridStroke}
        width={64}
        tickFormatter={withUnit}
        label={
          chart.yLabel
            ? {
                value: shorten(chart.yLabel),
                angle: -90,
                position: "insideLeft",
                offset: -4,
                fontSize: 11,
                fill: tickFill,
                style: { textAnchor: "middle" },
              }
            : undefined
        }
      />
      <Tooltip
        formatter={(value, name) => [withUnit(value), String(name)]}
        contentStyle={{
          background: tooltipBg,
          border: `1px solid ${tooltipBorder}`,
          borderRadius: 6,
          color: tooltipText,
          maxWidth: 360,
          whiteSpace: "normal",
        }}
        labelStyle={{ color: tooltipText }}
        cursor={{ fill: gridStroke, fillOpacity: 0.4 }}
      />
      {series.length > 1 && (
        <Legend
          verticalAlign="top"
          wrapperStyle={{ fontSize: 11, color: tickFill, paddingBottom: 6 }}
          formatter={(value) => shorten(String(value))}
        />
      )}
    </>
  );

  return (
    <Box>
      <Flex align="flex-start" justify="space-between" gap={2} mb={2}>
        <Box minW={0}>
          <Text fontWeight="medium" fontSize="sm" noOfLines={2} title={title}>
            {title}
          </Text>
          <Text fontSize="xs" color="fg.muted" noOfLines={2}>
            {chart.subtitle || `${data.length} points`}
          </Text>
        </Box>
        <ButtonGroup size="xs" isAttached variant="outline" flexShrink={0}>
          {chartTypes.map((item) => (
            <Button
              key={item}
              onClick={() => setType(item)}
              colorScheme={type === item ? "brand" : "gray"}
              variant={type === item ? "solid" : "outline"}
            >
              {item}
            </Button>
          ))}
        </ButtonGroup>
      </Flex>

      <Box h="280px">
        <ResponsiveContainer width="100%" height="100%">
          {type === "bar" ? (
            <BarChart data={data} margin={margin}>
              {axes}
              {series.map((item, index) => (
                <Bar
                  key={item.key}
                  dataKey={item.key}
                  name={item.label}
                  fill={colorFor(index)}
                  radius={[3, 3, 0, 0]}
                />
              ))}
            </BarChart>
          ) : type === "area" ? (
            <AreaChart data={data} margin={margin}>
              <defs>
                {series.map((item, index) => (
                  <linearGradient key={item.key} id={`${fillId}-${index}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={colorFor(index)} stopOpacity={0.35} />
                    <stop offset="100%" stopColor={colorFor(index)} stopOpacity={0.02} />
                  </linearGradient>
                ))}
              </defs>
              {axes}
              {series.map((item, index) => (
                <Area
                  key={item.key}
                  type="monotone"
                  dataKey={item.key}
                  name={item.label}
                  stroke={colorFor(index)}
                  strokeWidth={2}
                  fill={`url(#${fillId}-${index})`}
                />
              ))}
            </AreaChart>
          ) : (
            <LineChart data={data} margin={margin}>
              {axes}
              {series.map((item, index) => (
                <Line
                  key={item.key}
                  type="monotone"
                  dataKey={item.key}
                  name={item.label}
                  stroke={colorFor(index)}
                  strokeWidth={2}
                  dot={data.length <= 24 ? { r: 3 } : false}
                  activeDot={{ r: 5 }}
                  connectNulls
                />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      </Box>
    </Box>
  );
}
