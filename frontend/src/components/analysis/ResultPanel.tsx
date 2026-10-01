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
import { useEffect, useRef } from "react";

import { BriefingPanel } from "./BriefingPanel";
import { ChartBlock } from "../plot/ChartBlock";
import { CorrelationTable } from "./CorrelationTable";
import { DatasetPanel } from "./DatasetPanel";
import { MetricCards } from "./MetricCards";
import { Panel } from "../common/Panel";
import { useAnalysisStore } from "../../store/analysisStore";
import { useChatStore } from "../../store/chatStore";
import type { AnalysisResult } from "../../types/analysis";

function ChatReply({ result }: { result: AnalysisResult }) {
  return (
    <Stack spacing={3}>
      <Box>
        <Text fontSize="xs" color="fg.muted" mb={1}>
          You
        </Text>
        <Text 
          fontSize="sm" 
          bg="bg.subtle" 
          p={3} 
          rounded="md"
          fontWeight="medium"
        >
          {result.query}
        </Text>
      </Box>
      <Box>
        <Text fontSize="xs" color="fg.muted" mb={1}>
          General agent
        </Text>
        <Text 
          whiteSpace="pre-wrap" 
          fontSize="sm" 
          lineHeight="tall"
          p={3}
          bg="bg.muted"
          rounded="md"
        >
          {result.report.briefing}
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
              <MenuItem onClick={() => exportResult("markdown")}>Briefing with citations (Markdown)</MenuItem>
              <MenuItem onClick={() => exportResult("json")}>Full report (JSON)</MenuItem>
              <MenuItem onClick={() => exportResult("csv")}>Dataset records (CSV)</MenuItem>
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
  const analysisResult = useAnalysisStore((state) => state.analysisResult);
  const resultTab = useAnalysisStore((state) => state.resultTab);
  const setResultTab = useAnalysisStore((state) => state.setResultTab);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [chatMessages]);

  return (
    <Panel title="Results">
      <Tabs
        colorScheme="brand"
        variant="line"
        index={resultTab === "chat" ? 0 : 1}
        onChange={(index) => setResultTab(index === 0 ? "chat" : "analysis")}
      >
        <TabList borderColor="border.subtle">
          <Tab>Chat</Tab>
          <Tab>Analysis</Tab>
        </TabList>
        <TabPanels>
          <TabPanel px={0}>
            <Box
              ref={scrollRef}
              maxH="600px"
              overflowY="auto"
              borderWidth="1px"
              borderColor="border.subtle"
              rounded="md"
              p={4}
            >
              {chatMessages.length > 0 ? (
                <Stack spacing={4}>
                  {chatMessages.map((msg, index) => (
                    <Box key={index} borderBottom={index < chatMessages.length - 1 ? "1px" : "none"} borderColor="border.subtle" pb={index < chatMessages.length - 1 ? 4 : 0}>
                      <ChatReply result={msg} />
                    </Box>
                  ))}
                </Stack>
              ) : (
                <Text fontSize="sm" color="fg.muted">
                  No conversation yet. Send a general message to chat.
                </Text>
              )}
            </Box>
          </TabPanel>
          <TabPanel px={0}>
            {analysisResult ? (
              <AnalysisView result={analysisResult} />
            ) : (
              <Text fontSize="sm" color="fg.muted">
                No analysis yet. Ask a statistics question to see metrics, charts and the briefing.
              </Text>
            )}
          </TabPanel>
        </TabPanels>
      </Tabs>
    </Panel>
  );
}
