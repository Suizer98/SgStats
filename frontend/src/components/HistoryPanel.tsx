import { useRef } from "react";
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Badge,
  Box,
  Button,
  Flex,
  Input,
  Stack,
  Text,
  useDisclosure,
} from "@chakra-ui/react";

import { useAnalysisStore } from "../store/analysisStore";
import type { Conversation } from "../types/analysis";
import { relativeTime } from "../utils/format";

function statusColor(status: string): string {
  if (status === "done") return "green";
  if (status === "failed") return "red";
  return "blue";
}

function threadStatus(thread: Conversation): string {
  if (thread.analyses.some((row) => row.status === "running")) return "running";
  const latest = thread.analyses[thread.analyses.length - 1];
  return latest?.status ?? "done";
}

export function HistoryPanel({ onOpenItem }: { onOpenItem?: () => void }) {
  const history = useAnalysisStore((state) => state.history);
  const filter = useAnalysisStore((state) => state.historyFilter);
  const conversationId = useAnalysisStore((state) => state.conversationId);
  const setHistoryFilter = useAnalysisStore((state) => state.setHistoryFilter);
  const openHistory = useAnalysisStore((state) => state.openHistory);
  const deleteHistory = useAnalysisStore((state) => state.deleteHistory);
  const clearHistory = useAnalysisStore((state) => state.clearHistory);
  const confirmClear = useDisclosure();
  const cancelRef = useRef<HTMLButtonElement>(null);

  const needle = filter.trim().toLowerCase();
  const threads = history.filter((thread) => {
    if (!needle) return true;
    if (thread.title.toLowerCase().includes(needle)) return true;
    return thread.analyses.some((row) => row.query.toLowerCase().includes(needle));
  });

  return (
    <>
      <Stack spacing={3}>
        <Text fontSize="sm" color="fg.muted">
          {history.length} saved {history.length === 1 ? "thread" : "threads"}
        </Text>
        <Flex gap={2}>
          <Input
            size="sm"
            placeholder="Filter by query"
            value={filter}
            onChange={(event) => setHistoryFilter(event.target.value)}
          />
          {history.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              flexShrink={0}
              onClick={confirmClear.onOpen}
            >
              Clear
            </Button>
          )}
        </Flex>

        <Stack spacing={2} maxH="calc(100vh - 220px)" overflowY="auto" pr={1}>
          {threads.map((thread) => {
            const latest = thread.analyses[thread.analyses.length - 1];
            const status = threadStatus(thread);
            const open = thread.id === conversationId;
            return (
              <Box
                key={thread.id}
                textAlign="left"
                borderWidth="1px"
                borderColor={open ? "border.accent" : "border.subtle"}
                bg={open ? "bg.active" : "bg.surface"}
                rounded="md"
                p={3}
                cursor="pointer"
                onClick={() => {
                  void openHistory(thread.id);
                  onOpenItem?.();
                }}
                _hover={{ borderColor: "border.accent" }}
              >
                <Flex align="flex-start" justify="space-between" gap={2}>
                  <Text fontSize="sm" fontWeight="medium" noOfLines={2}>
                    {thread.title}
                  </Text>
                  <Button
                    size="xs"
                    variant="ghost"
                    flexShrink={0}
                    isDisabled={status === "running"}
                    onClick={(event) => {
                      event.stopPropagation();
                      void deleteHistory(thread.id);
                    }}
                  >
                    Delete
                  </Button>
                </Flex>
                {thread.analyses.length > 1 && latest && latest.query !== thread.title && (
                  <Text fontSize="xs" color="fg.muted" noOfLines={1} mt={1}>
                    Latest: {latest.query}
                  </Text>
                )}
                <Flex align="center" gap={2} mt={2}>
                  <Badge colorScheme={statusColor(status)}>{status}</Badge>
                  {thread.analyses.length > 1 && (
                    <Badge variant="subtle">{thread.analyses.length} messages</Badge>
                  )}
                  <Badge variant="outline" title={thread.id}>
                    {thread.id.slice(0, 8)}
                  </Badge>
                  <Text fontSize="xs" color="fg.muted">
                    {relativeTime(thread.updated_at)}
                  </Text>
                </Flex>
              </Box>
            );
          })}
          {threads.length === 0 && (
            <Text fontSize="sm" color="fg.muted">
              {history.length === 0 ? "No threads yet." : "No matching threads."}
            </Text>
          )}
        </Stack>
      </Stack>

      <AlertDialog
        isOpen={confirmClear.isOpen}
        leastDestructiveRef={cancelRef}
        onClose={confirmClear.onClose}
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader fontSize="lg">Clear history</AlertDialogHeader>
            <AlertDialogBody>
              Delete saved history? A run that is still going will stay.
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button ref={cancelRef} onClick={confirmClear.onClose}>
                Cancel
              </Button>
              <Button
                colorScheme="red"
                ml={3}
                onClick={() => {
                  confirmClear.onClose();
                  void clearHistory();
                }}
              >
                Clear
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </>
  );
}
