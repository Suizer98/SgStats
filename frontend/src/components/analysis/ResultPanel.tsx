import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Code,
  HStack,
  Menu,
  MenuButton,
  MenuItem,
  MenuList,
  SimpleGrid,
  Stack,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
} from "@chakra-ui/react";
import { useEffect, useRef, useState } from "react";

import { QueryForm } from "../chat/QueryForm";
import { BriefingPanel } from "./BriefingPanel";
import { ChartBlock } from "../plot/ChartBlock";
import { CorrelationTable } from "./CorrelationTable";
import { DatasetPanel } from "./DatasetPanel";
import { MetricCards } from "./MetricCards";
import { NewChatIcon } from "../common/icons";
import { Panel } from "../common/Panel";
import { useAnalysisStore } from "../../store/analysisStore";
import { useChatStore } from "../../store/chatStore";
import type { AnalysisResult } from "../../types/analysis";

function replyText(result: AnalysisResult): string {
  if (result.kind === "chat") return result.report.briefing;
  return result.report.chat_message || result.report.briefing;
}

function Turn({ result }: { result: AnalysisResult }) {
  return (
    <Stack spacing={4}>
      <Box>
        <Text fontSize="xs" color="fg.muted" mb={1}>
          You
        </Text>
        <Text fontSize="sm" bg="bg.subtle" p={3} rounded="md" fontWeight="medium">
          {result.query}
        </Text>
      </Box>
      <Box>
        <Text fontSize="xs" color="fg.muted" mb={1}>
          SgStats
        </Text>
        <Text whiteSpace="pre-wrap" fontSize="sm" lineHeight="tall" p={3} bg="bg.muted" rounded="md">
          {replyText(result)}
        </Text>
      </Box>
    </Stack>
  );
}

function AnalysisView({ result }: { result: AnalysisResult }) {
  const exportResult = useAnalysisStore((state) => state.exportResult);
  const { charts, metrics } = result.summary;
  const { scope } = result;
  const liveCount = result.datasets.filter((item) => item.mode === "live").length;

  return (
    <Stack spacing={4}>
      <HStack justify="space-between" wrap="wrap">
        <Text fontSize="sm" color="fg.muted">
          {scope.sector ? `${scope.sector} · ` : ""}
          {scope.year_from}-{scope.year_to}
        </Text>
        <HStack spacing={2}>
          <Badge colorScheme="green">{liveCount} live</Badge>
          <Badge colorScheme="orange">{result.datasets.length - liveCount} snapshot</Badge>
          <Menu>
            <MenuButton as={Button} size="sm" variant="outline">
              Export
            </MenuButton>
            <MenuList>
            <MenuItem onClick={() => exportResult("markdown", result)}>Briefing with citations (Markdown)</MenuItem>
            <MenuItem onClick={() => exportResult("json", result)}>Full report (JSON)</MenuItem>
            <MenuItem onClick={() => exportResult("csv", result)}>Dataset records (CSV)</MenuItem>
            </MenuList>
          </Menu>
        </HStack>
      </HStack>
      <Tabs colorScheme="brand" variant="line" isLazy>
        <TabList borderColor="border.subtle">
          <Tab>Overview</Tab>
          <Tab>Datasets ({result.datasets.length})</Tab>
          <Tab>Briefing</Tab>
          <Tab>Raw JSON</Tab>
        </TabList>

        <TabPanels>
          <TabPanel px={0}>
            <Stack spacing={5}>
              {(scope.notes ?? []).map((note) => (
                <Alert key={note} status="info" rounded="md" fontSize="sm">
                  <AlertIcon />
                  {note}
                </Alert>
              ))}
              <MetricCards metrics={metrics} />
              <SimpleGrid columns={{ base: 1, xl: 2 }} spacing={5}>
                {charts.map((chart) => (
                  <Box
                    key={chart.id}
                    borderWidth="1px"
                    borderColor="border.subtle"
                    rounded="md"
                    p={4}
                  >
                    <ChartBlock chart={chart} />
                  </Box>
                ))}
              </SimpleGrid>
              {charts.length === 0 && (
                <Text fontSize="sm" color="fg.muted">
                  No numeric series to chart for this query.
                </Text>
              )}
              <CorrelationTable correlations={result.summary.correlations ?? []} />
            </Stack>
          </TabPanel>

          <TabPanel px={0}>
            <DatasetPanel datasets={result.datasets} />
          </TabPanel>

          <TabPanel px={0}>
            <BriefingPanel result={result} />
          </TabPanel>

          <TabPanel px={0}>
            <Code
              display="block"
              whiteSpace="pre"
              overflowX="auto"
              maxH="520px"
              overflowY="auto"
              p={3}
              fontSize="xs"
              rounded="md"
              bg="bg.subtle"
              color="fg.default"
            >
              {JSON.stringify(result, null, 2)}
            </Code>
          </TabPanel>
        </TabPanels>
      </Tabs>
    </Stack>
  );
}

export function ResultPanel() {
  const chatMessages = useChatStore((state) => state.chatMessages);
  const pendingQuery = useChatStore((state) => state.pendingQuery);
  const busy = useChatStore((state) => state.busy);
  const conversationId = useChatStore((state) => state.conversationId);
  const startConversation = useChatStore((state) => state.startConversation);
  const scrollRef = useRef<HTMLDivElement>(null);
  const hasThread = chatMessages.length > 0 || Boolean(pendingQuery);
  const pinned = [...chatMessages].reverse().find((turn) => turn.result.kind !== "chat" && turn.result.datasets.length > 0);
  const [tab, setTab] = useState(0);
  const latestId = chatMessages[chatMessages.length - 1]?.id;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatMessages, pendingQuery]);

  useEffect(() => {
    const latest = chatMessages[chatMessages.length - 1]?.result;
    if (!latest) return;
    setTab(latest.kind !== "chat" && latest.datasets.length > 0 ? 1 : 0);
  }, [latestId, chatMessages]);

  return (
    <Panel
      title={hasThread ? "Conversation" : "Ask a policy question"}
      caption={
        hasThread
          ? "A follow-up stays in this thread. Start a new conversation to fetch different data."
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
            isDisabled={busy || !hasThread}
          >
            New conversation
          </Button>
        </HStack>
      }
    >
      <Stack spacing={4}>
        {hasThread ? (
          <Tabs colorScheme="brand" variant="line" index={tab} onChange={setTab}>
            <TabList borderColor="border.subtle">
              <Tab>Chat</Tab>
              <Tab>Analysis</Tab>
            </TabList>
            <TabPanels>
              <TabPanel px={0}>
                <Box ref={scrollRef} maxH="calc(100vh - 320px)" overflowY="auto">
                  <Stack spacing={6}>
                    {chatMessages.map((turn) => (
                      <Box key={turn.id} borderBottomWidth="1px" borderColor="border.subtle" pb={6}>
                        <Turn result={turn.result} />
                      </Box>
                    ))}
                    {pendingQuery && (
                      <Box>
                        <Text fontSize="xs" color="fg.muted" mb={1}>
                          You
                        </Text>
                        <Text fontSize="sm" bg="bg.subtle" p={3} rounded="md" fontWeight="medium">
                          {pendingQuery}
                        </Text>
                        <Text fontSize="sm" color="fg.muted" mt={3}>
                          Working on this now.
                        </Text>
                      </Box>
                    )}
                  </Stack>
                </Box>
                <Box mt={4}>
                  <QueryForm compact />
                </Box>
              </TabPanel>
              <TabPanel px={0}>
                {pinned ? (
                  <AnalysisView result={pinned.result} />
                ) : (
                  <Text fontSize="sm" color="fg.muted">
                    No analysis yet. Ask a statistics question to see the chart.
                  </Text>
                )}
              </TabPanel>
            </TabPanels>
          </Tabs>
        ) : (
          <QueryForm />
        )}
      </Stack>
    </Panel>
  );
}
