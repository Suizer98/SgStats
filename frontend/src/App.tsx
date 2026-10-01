import { useEffect } from "react";
import { Box, Container, Flex, Stack } from "@chakra-ui/react";

import { AgentActivity } from "./components/AgentActivity";
import { Header } from "./components/Header";
import { QueryForm } from "./components/QueryForm";
import { ResultPanel } from "./components/ResultPanel";
import { useChatStore } from "./store/chatStore";

export default function App() {
  const loadHistory = useChatStore((state) => state.loadHistory);
  const checkHealth = useChatStore((state) => state.checkHealth);

  useEffect(() => {
    void loadHistory();
    void checkHealth();
    const timer = window.setInterval(() => void checkHealth(), 60000);
    return () => window.clearInterval(timer);
  }, [loadHistory, checkHealth]);

  return (
    <Box minH="100vh">
      <Header />
      <Container maxW="8xl" py={{ base: 5, md: 8 }}>
        <Stack spacing={{ base: 5, md: 6 }}>
          <QueryForm />
          <Flex gap={6} direction={{ base: "column", xl: "row" }} align="flex-start">
            <Box flex="2" w="100%" minW={0}>
              <ResultPanel />
            </Box>
            <Stack flex="1" w="100%" spacing={6}>
              <AgentActivity />
            </Stack>
          </Flex>
        </Stack>
      </Container>
    </Box>
  );
}
