import {
  Badge,
  Box,
  Container,
  Drawer,
  DrawerBody,
  DrawerCloseButton,
  DrawerContent,
  DrawerHeader,
  DrawerOverlay,
  Flex,
  Heading,
  HStack,
  IconButton,
  Switch,
  Text,
  Tooltip,
  useColorMode,
  useDisclosure,
} from "@chakra-ui/react";

import { HistoryPanel } from "../chat/HistoryPanel";
import { MenuIcon, MoonIcon, SunIcon } from "../common/icons";
import { useChatStore } from "../../store/chatStore";
import type { AnalysisResult } from "../../types/analysis";

function llmLabel(result: AnalysisResult | null): string {
  const recorded = result?.report.llm_providers ?? [];
  const fallback = result?.report.llm_provider ? [result.report.llm_provider] : [];
  const names = new Set([...recorded, ...fallback]);
  const shown = ["gemini", "groq"].filter((name) => names.has(name));
  if (shown.length === 0) return "LLMs: None";
  return `LLMs: ${shown.join(", ")}`;
}

function StatusDot({ online }: { online: boolean | null }) {
  const color = online === null ? "gray.400" : online ? "green.400" : "red.400";
  return <Box w="8px" h="8px" rounded="full" bg={color} />;
}

function ColorModeRow() {
  const { colorMode, toggleColorMode } = useColorMode();
  const dark = colorMode === "dark";
  return (
    <Flex align="center" justify="space-between" mb={5}>
      <HStack spacing={2}>
        <Box fontSize="md">{dark ? <MoonIcon /> : <SunIcon />}</Box>
        <Text fontSize="sm">Dark mode</Text>
      </HStack>
      <Switch
        isChecked={dark}
        onChange={toggleColorMode}
        colorScheme="brand"
        aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      />
    </Flex>
  );
}

export function Header() {
  const apiOnline = useChatStore((state) => state.apiOnline);
  const result = useChatStore((state) => state.result);
  const models = llmLabel(result);
  const historyDrawer = useDisclosure();

  return (
    <Box bg="bg.surface" borderTop="4px solid" borderTopColor="civic.red" borderBottomWidth="1px" borderColor="border.subtle">
      <Container maxW="8xl" py={{ base: 4, md: 5 }}>
        <Flex align="center" justify="space-between" gap={4} wrap="wrap">
          <HStack spacing={3}>
            <Box w="6px" h="40px" bg="brand.600" />
            <Box>
              <Text
                fontSize="xs"
                color="brand.600"
                fontWeight="700"
                letterSpacing="0.09em"
                textTransform="uppercase"
              >
                Singapore public data workspace
              </Text>
              <HStack spacing={3} align="baseline">
                <Heading
                  as="button"
                  type="button"
                  size="md"
                  cursor="pointer"
                  onClick={() => window.location.reload()}
                >
                  SgStats
                </Heading>
                <Text display={{ base: "none", md: "block" }} fontSize="sm" color="fg.muted">
                  Agentic policy analytics
                </Text>
              </HStack>
            </Box>
          </HStack>
          <HStack spacing={3} wrap="wrap">
            <HStack
              spacing={2}
              borderWidth="1px"
              borderColor="border.subtle"
              rounded="sm"
              px={3}
              py={1}
            >
              <StatusDot online={apiOnline} />
              <Text fontSize="xs">
                API {apiOnline === null ? "checking" : apiOnline ? "online" : "offline"}
              </Text>
            </HStack>
            <Badge variant="outline" colorScheme="gray" px={3} py={1}>
              Bifrost: Gemini to Groq
            </Badge>
            <Badge variant="outline" colorScheme="brand" px={3} py={1}>
              gov-mcp tools
            </Badge>
            <Badge colorScheme={models === "LLMs: None" ? "gray" : "green"} px={3} py={1}>
              {models}
            </Badge>
            <Tooltip label="History">
              <IconButton
                aria-label="Open history"
                icon={<MenuIcon />}
                onClick={historyDrawer.onOpen}
                size="sm"
                variant="ghost"
                fontSize="md"
              />
            </Tooltip>
          </HStack>
        </Flex>
      </Container>
      <Drawer isOpen={historyDrawer.isOpen} placement="right" onClose={historyDrawer.onClose} size="md">
        <DrawerOverlay bg="blackAlpha.600" />
        <DrawerContent>
          <DrawerCloseButton />
          <DrawerHeader>History</DrawerHeader>
          <DrawerBody>
            <ColorModeRow />
            <HistoryPanel onOpenItem={historyDrawer.onClose} />
          </DrawerBody>
        </DrawerContent>
      </Drawer>
    </Box>
  );
}
