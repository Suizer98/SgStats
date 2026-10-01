import type { FormEvent, KeyboardEvent } from "react";
import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Flex,
  HStack,
  Progress,
  Stack,
  Tag,
  TagLabel,
  Text,
  Textarea,
  Wrap,
  WrapItem,
} from "@chakra-ui/react";

import { sampleQueries } from "../constants";
import { NewChatIcon } from "./icons";
import { Panel } from "./Panel";
import { useAnalysisStore } from "../store/analysisStore";
import { useChatStore } from "../store/chatStore";

export function QueryForm() {
  const query = useChatStore((state) => state.query);
  const busy = useChatStore((state) => state.busy);
  const error = useChatStore((state) => state.error);
  const conversationId = useChatStore((state) => state.conversationId);
  const analysisResult = useAnalysisStore((state) => state.analysisResult);
  const setQuery = useChatStore((state) => state.setQuery);
  const startConversation = useChatStore((state) => state.startConversation);
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
    <Panel
      title="Ask a policy question"
      caption={
        analysisResult
          ? "A follow-up updates this analysis from the same datasets. Start a new conversation to fetch different data."
          : "Statistics questions use the data agents. General chat stays a normal conversation."
      }
      action={
        <HStack spacing={2}>
          {conversationId && (
            <Badge colorScheme="brand" title={conversationId}>
              thread {conversationId.slice(0, 8)}
            </Badge>
          )}
          <Button
            size="xs"
            variant="ghost"
            colorScheme="brand"
            leftIcon={<NewChatIcon />}
            onClick={startConversation}
            isDisabled={busy}
          >
            New conversation
          </Button>
        </HStack>
      }
    >
      <Box as="form" onSubmit={submit}>
        <Stack spacing={4}>
          <Textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask about any Singapore statistic, e.g. How has CPI inflation changed since 2019"
            minH="96px"
            bg="bg.subtle"
          />

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
    </Panel>
  );
}
