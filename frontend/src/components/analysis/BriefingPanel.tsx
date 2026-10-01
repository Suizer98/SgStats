import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Divider,
  Heading,
  HStack,
  List,
  ListItem,
  Stack,
  Text,
} from "@chakra-ui/react";

import type { AnalysisResult } from "../../types/analysis";

export function BriefingPanel({ result }: { result: AnalysisResult }) {
  const { report } = result;
  const usage = report.llm_usage;

  return (
    <Stack spacing={4}>
      <HStack spacing={2} wrap="wrap">
        <Badge colorScheme="purple">via {report.llm_provider}</Badge>
        <Badge colorScheme={report.grounding.passed ? "green" : "red"}>
          {report.grounding.passed ? "grounded in source numbers" : "ungrounded numbers found"}
        </Badge>
        <Badge variant="outline">{result.datasets.length} sources</Badge>
        {usage && usage.seconds > 0 && (
          <Badge variant="outline">
            {usage.input_tokens + usage.output_tokens} tokens · {usage.seconds}s
          </Badge>
        )}
      </HStack>

      {report.llm_error && (
        <Alert status="info" rounded="md" fontSize="sm">
          <AlertIcon />
          LLM unavailable ({report.llm_error}). This briefing was written from the computed facts only.
        </Alert>
      )}

      {!report.grounding.passed && (
        <Alert status="warning" rounded="md" fontSize="sm">
          <AlertIcon />
          Numbers not traced to the datasets: {report.grounding.unsupported_numbers.join(", ")}
        </Alert>
      )}

      <Box>
        <Heading size="sm" mb={2}>
          {report.title}
        </Heading>
        <List spacing={2}>
          {report.insights.map((insight) => (
            <ListItem key={insight} fontSize="sm">
              • {insight}
            </ListItem>
          ))}
        </List>
      </Box>

      <Text whiteSpace="pre-wrap" fontSize="sm" lineHeight="tall">
        {report.briefing}
      </Text>

      <Divider />

      <Box>
        <Text fontWeight="medium" fontSize="sm" mb={1}>
          Citations
        </Text>
        <Stack spacing={1}>
          {report.citations.map((citation) => (
            <Text key={citation} fontSize="xs" color="fg.faint">
              {citation}
            </Text>
          ))}
        </Stack>
      </Box>
    </Stack>
  );
}
