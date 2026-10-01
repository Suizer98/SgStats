import {
  Box,
  SimpleGrid,
  Stat,
  StatArrow,
  StatHelpText,
  StatLabel,
  StatNumber,
} from "@chakra-ui/react";

import type { Metric } from "../../types/analysis";
import { formatNumber, labelCase } from "../../utils/format";

// Metrics saved before `change` existed used `value` as the change itself.
function changeOf(metric: Metric): number | null {
  return metric.change === undefined ? metric.value : metric.change;
}

export function MetricCards({ metrics }: { metrics: Metric[] }) {
  return (
    <SimpleGrid columns={{ base: 1, sm: 2, xl: 3 }} spacing={4}>
      {metrics.map((metric, index) => (
        <Box
          key={`${metric.label}-${index}`}
          borderWidth="1px"
          borderColor="border.subtle"
          borderLeftWidth="4px"
          borderLeftColor="brand.500"
          rounded="md"
          p={4}
          bg="bg.surface"
        >
          <Stat>
            <StatLabel fontSize="xs" color="fg.muted" noOfLines={2} title={metric.label}>
              {labelCase(metric.label)}
            </StatLabel>
            <StatNumber fontSize="2xl">
              {formatNumber(metric.value)}
              {metric.unit}
            </StatNumber>
            <StatHelpText mb={0} fontSize="xs">
              {changeOf(metric) !== null && (
                <StatArrow type={(changeOf(metric) ?? 0) >= 0 ? "increase" : "decrease"} />
              )}
              {metric.detail}
            </StatHelpText>
          </Stat>
        </Box>
      ))}
    </SimpleGrid>
  );
}
