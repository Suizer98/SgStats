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
import { relativeTime } from "../utils/format";

function statusColor(status: string): string {
  if (status === "done") return "green";
  if (status === "failed") return "red";
  return "blue";
}

export function HistoryPanel({ onOpenItem }: { onOpenItem?: () => void }) {
  const history = useAnalysisStore((state) => state.history);
  const filter = useAnalysisStore((state) => state.historyFilter);
  const activeId = useAnalysisStore((state) => state.activeId);
  const setHistoryFilter = useAnalysisStore((state) => state.setHistoryFilter);
  const openHistory = useAnalysisStore((state) => state.openHistory);
  const deleteHistory = useAnalysisStore((state) => state.deleteHistory);
  const clearHistory = useAnalysisStore((state) => state.clearHistory);
  const confirmClear = useDisclosure();
  const cancelRef = useRef<HTMLButtonElement>(null);

  const rows = history.filter((row) =>
    row.query.toLowerCase().includes(filter.trim().toLowerCase()),
  );

  return (
    <>
      <Stack spacing={3}>
        <Text fontSize="sm" color="fg.muted">
          {history.length} saved analyses
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
          {rows.map((row) => (
            <Box
              key={row.id}
              textAlign="left"
              borderWidth="1px"
              borderColor={row.id === activeId ? "border.accent" : "border.subtle"}
              bg={row.id === activeId ? "bg.active" : "bg.surface"}
              rounded="md"
              p={3}
              cursor="pointer"
              onClick={() => {
                void openHistory(row.id);
                onOpenItem?.();
              }}
              _hover={{ borderColor: "border.accent" }}
            >
              <Flex align="flex-start" justify="space-between" gap={2}>
                <Text fontSize="sm" fontWeight="medium" noOfLines={2}>
                  {row.query}
                </Text>
                <Button
                  size="xs"
                  variant="ghost"
                  flexShrink={0}
                  isDisabled={row.status === "running"}
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteHistory(row.id);
                  }}
                >
                  Delete
                </Button>
              </Flex>
              <Flex align="center" gap={2} mt={2}>
                <Badge colorScheme={statusColor(row.status)}>{row.status}</Badge>
                <Badge variant="outline" title={row.conversation_id}>
                  {row.conversation_id?.slice(0, 8)}
                </Badge>
                <Text fontSize="xs" color="fg.muted">
                  {relativeTime(row.created_at)}
                </Text>
              </Flex>
            </Box>
          ))}
          {rows.length === 0 && (
            <Text fontSize="sm" color="fg.muted">
              {history.length === 0 ? "No runs yet." : "No matching runs."}
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
