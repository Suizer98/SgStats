import { useState } from "react";
import {
  Badge,
  Box,
  Button,
  Flex,
  HStack,
  List,
  ListItem,
  Stack,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from "@chakra-ui/react";

import type { Dataset } from "../../types/analysis";
import { downloadFile, formatNumber, labelCase, toCsv } from "../../utils/format";

const previewRows = 6;

function DatasetCard({ dataset }: { dataset: Dataset }) {
  const [expanded, setExpanded] = useState(false);
  const records = dataset.records;
  const columns = Array.from(new Set(records.flatMap((row) => Object.keys(row))));
  const visible = expanded ? records : records.slice(0, previewRows);
  const nulls = Object.entries(dataset.quality.nulls || {}).filter(([, count]) => count > 0);
  const live = dataset.mode === "live";

  return (
    <Box borderWidth="1px" borderColor="border.subtle" rounded="md" p={4}>
      <Flex align="flex-start" justify="space-between" gap={3} wrap="wrap" mb={3}>
        <Box minW={0}>
          <Text fontWeight="medium">{dataset.title ?? dataset.source}</Text>
          <Text fontSize="xs" color="fg.muted">
            {dataset.citation}
          </Text>
          {dataset.note && (
            <Text fontSize="xs" color="orange.500" mt={1}>
              {dataset.note}
            </Text>
          )}
        </Box>
        <HStack spacing={2}>
          <Badge colorScheme={live ? "green" : "orange"}>
            {live ? "live fetch" : "snapshot fallback"}
          </Badge>
          {dataset.provider && <Badge variant="outline">{dataset.provider}</Badge>}
          {dataset.grain && <Badge variant="outline">{dataset.grain}</Badge>}
          <Badge colorScheme={dataset.quality.ok ? "green" : "red"} variant="subtle">
            quality {dataset.quality.ok ? "ok" : "check"}
          </Badge>
        </HStack>
      </Flex>

      <HStack spacing={5} mb={3} fontSize="xs" color="fg.faint" wrap="wrap">
        <Text>{dataset.quality.rows} rows after cleaning</Text>
        <Text>{columns.length} columns</Text>
        <Text>
          {nulls.length === 0
            ? "no null values"
            : `nulls: ${nulls.map(([key, count]) => `${key} (${count})`).join(", ")}`}
        </Text>
        {dataset.quality.missing_columns.length > 0 && (
          <Text color="red.500">
            missing: {dataset.quality.missing_columns.join(", ")}
          </Text>
        )}
        {dataset.format && <Text>source format {dataset.format.toUpperCase()}</Text>}
      </HStack>

      {(dataset.quality.checks ?? []).length > 0 && (
        <Box mb={3} fontSize="xs" color="fg.muted">
          <Text fontWeight="semibold" color="fg.default" mb={1}>
            Quality checks
          </Text>
          <List spacing={0.5}>
            {dataset.quality.checks?.map((check) => (
              <ListItem key={check}>• {check}</ListItem>
            ))}
          </List>
          {(dataset.quality.outliers ?? []).length > 0 && (
            <Text mt={1} color="orange.500">
              Flagged:{" "}
              {dataset.quality.outliers
                ?.map((item) => `${item.series} ${item.period} (${formatNumber(item.value)})`)
                .join(", ")}
            </Text>
          )}
        </Box>
      )}

      <TableContainer borderWidth="1px" borderColor="border.subtle" rounded="md">
        <Table size="sm" variant="simple">
          <Thead bg="bg.subtle">
            <Tr>
              {columns.map((column) => (
                <Th key={column}>{labelCase(column)}</Th>
              ))}
            </Tr>
          </Thead>
          <Tbody>
            {visible.map((row, index) => (
              <Tr key={index}>
                {columns.map((column) => (
                  <Td key={column} fontSize="xs">
                    {typeof row[column] === "number"
                      ? formatNumber(row[column])
                      : String(row[column] ?? "")}
                  </Td>
                ))}
              </Tr>
            ))}
          </Tbody>
        </Table>
      </TableContainer>

      <HStack spacing={3} mt={3}>
        {records.length > previewRows && (
          <Button size="xs" variant="ghost" onClick={() => setExpanded(!expanded)}>
            {expanded ? "Show less" : `Show all ${records.length} rows`}
          </Button>
        )}
        <Button
          size="xs"
          variant="ghost"
          onClick={() =>
            downloadFile(
              toCsv(records),
              `${(dataset.dataset_id ?? dataset.source).toLowerCase().replace(/[^a-z0-9]+/g, "-")}.csv`,
              "text/csv",
            )
          }
        >
          Download CSV
        </Button>
      </HStack>
    </Box>
  );
}

export function DatasetPanel({ datasets }: { datasets: Dataset[] }) {
  return (
    <Stack spacing={4}>
      {datasets.map((dataset) => (
        <DatasetCard key={`${dataset.dataset_id ?? dataset.source}-${dataset.citation}`} dataset={dataset} />
      ))}
    </Stack>
  );
}
