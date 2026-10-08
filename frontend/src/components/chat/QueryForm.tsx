import type { FormEvent, KeyboardEvent } from "react";
import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Flex,
  Progress,
  Stack,
  Tag,
  TagLabel,
  Text,
  Textarea,
  Wrap,
  WrapItem,
} from "@chakra-ui/react";

import { sampleQueries } from "../../constants";
import { useChatStore } from "../../store/chatStore";

export function QueryForm({ compact = false }: { compact?: boolean }) {
  const query = useChatStore((state) => state.query);
  const busy = useChatStore((state) => state.busy);
  const error = useChatStore((state) => state.error);
  const setQuery = useChatStore((state) => state.setQuery);
  const runAnalysis = useChatStore((state) => state.runAnalysis);
  const abortRun = useChatStore((state) => state.abortRun);

  function submit(event: FormEvent) {
    event.preventDefault();
    void runAnalysis();
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      if (busy) void abortRun();
      else void runAnalysis();
    }
  }

  return (
    <Box as="form" onSubmit={submit}>
      <Stack spacing={4}>
        <Textarea
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={compact ? "Ask a follow-up" : "Ask about any Singapore statistic, e.g. How has CPI inflation changed since 2019"}
          minH={compact ? "72px" : "96px"}
          bg="bg.subtle"
        />

        {!compact && (
          <Wrap spacing={2}>
            {sampleQueries.map((item) => (
              <WrapItem key={item}>
                <Tag
                  as="button"
                  type="button"
                  size="sm"
                  variant="outline"
                  colorScheme="gray"
                  cursor="pointer"
                  onClick={() => setQuery(item)}
                >
                  <TagLabel noOfLines={1}>{item}</TagLabel>
                </Tag>
              </WrapItem>
            ))}
          </Wrap>
        )}

        <Flex align="center" justify="space-between" gap={3} wrap="wrap">
          <Button
            type={busy ? "button" : "submit"}
            colorScheme={busy ? "red" : "brand"}
            onClick={busy ? () => void abortRun() : undefined}
          >
            {busy ? "Abort" : "Send"}
          </Button>
          <Text fontSize="xs" color="fg.muted">
            {busy ? "Ctrl/Cmd + Enter to stop" : "Ctrl/Cmd + Enter to send"}
          </Text>
        </Flex>

        {busy && <Progress size="xs" isIndeterminate colorScheme="brand" />}

        {error && (
          <Alert status="error" rounded="md" fontSize="sm">
            <AlertIcon />
            {error}
          </Alert>
        )}
      </Stack>
    </Box>
  );
}
