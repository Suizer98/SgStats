import { useEffect, useRef, useState } from "react";
import {
  Badge,
  Box,
  Circle,
  Flex,
  HStack,
  Spinner,
  Stack,
  Text,
} from "@chakra-ui/react";

import { agentBlurb, agentOrder } from "../constants";
import { Panel } from "./Panel";
import { useChatStore } from "../store/chatStore";
import { clockTime, labelCase } from "../utils/format";

function stepColor(step: string): string {
  if (step === "thought") return "purple";
  if (step === "action") return "orange";
  return "green";
}

function useElapsed(startedAt: number | null, busy: boolean): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [busy]);
  if (!startedAt) return 0;
  return Math.max(0, Math.round(((busy ? now : startedAt) - startedAt) / 1000));
}

function AgentSteps({ order, seen, busy }: { order: string[]; seen: string[]; busy: boolean }) {
  const current = seen[seen.length - 1];
  return (
    <Stack spacing={2} mb={4}>
      {order.map((agent) => {
        const done = seen.includes(agent) && (!busy || agent !== current);
        const active = busy && agent === current;
        const color = active ? "blue.500" : done ? "green.500" : "gray.300";
        return (
          <HStack key={agent} align="flex-start" spacing={3}>
            <Circle size="8px" bg={color} mt="6px" />
            <Box>
              <HStack spacing={2}>
                <Text fontSize="sm" fontWeight="medium">
                  {labelCase(agent)}
                </Text>
                {active && <Spinner size="xs" color="blue.500" />}
              </HStack>
              <Text fontSize="xs" color="fg.muted">
                {agentBlurb[agent]}
              </Text>
            </Box>
          </HStack>
        );
      })}
    </Stack>
  );
}

export function AgentActivity() {
  const events = useChatStore((state) => state.events);
  const busy = useChatStore((state) => state.busy);
  const startedAt = useChatStore((state) => state.startedAt);
  const elapsed = useElapsed(startedAt, busy);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = scroller.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [events.length]);

  const chat = events.some((item) => item.agent === "general");
  const order = chat ? ["coordinator", "general"] : agentOrder;
  const seen = order.filter((agent) => events.some((item) => item.agent === agent));

  return (
    <Panel
      title="Agent activity"
      caption="Reasoning, action and observation steps streamed over WebSocket"
      action={
        busy ? (
          <Badge colorScheme="brand" px={2}>
            running {elapsed}s
          </Badge>
        ) : events.length > 0 ? (
          <Badge colorScheme="green" px={2}>
            {events.length} steps
          </Badge>
        ) : undefined
      }
    >
      <AgentSteps order={order} seen={seen} busy={busy} />

      {events.length === 0 ? (
        <Text fontSize="sm" color="fg.muted">
          Run a query to watch the agents plan, fetch and analyse.
        </Text>
      ) : (
        <Box ref={scroller} maxH="420px" overflowY="auto" pr={2}>
          <Stack spacing={3}>
            {events.map((item, index) => (
              <Box
                key={`${item.created_at}-${index}`}
                borderLeftWidth="2px"
                borderColor={`${stepColor(item.step)}.300`}
                pl={3}
              >
                <Flex align="center" justify="space-between" gap={2}>
                  <HStack spacing={2}>
                    <Badge>{item.agent}</Badge>
                    <Badge colorScheme={stepColor(item.step)}>{item.step}</Badge>
                  </HStack>
                  <Text fontSize="xs" color="fg.muted">
                    {clockTime(item.created_at)}
                  </Text>
                </Flex>
                <Text fontSize="sm" mt={1}>
                  {item.content}
                </Text>
              </Box>
            ))}
          </Stack>
        </Box>
      )}
    </Panel>
  );
}
