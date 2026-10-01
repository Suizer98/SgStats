import type { ReactNode } from "react";
import { Box, Flex, Heading, Text } from "@chakra-ui/react";

type PanelProps = {
  title?: string;
  caption?: string;
  action?: ReactNode;
  children: ReactNode;
};

export function Panel({ title, caption, action, children }: PanelProps) {
  return (
    <Box
      bg="bg.surface"
      borderWidth="1px"
      borderColor="border.subtle"
      borderTopWidth="3px"
      borderTopColor="brand.600"
      rounded="md"
      p={{ base: 4, md: 5 }}
    >
      {title && (
        <Flex align="flex-start" justify="space-between" gap={3} mb={4}>
          <Box>
            <Heading size="sm" lineHeight="1.3">
              {title}
            </Heading>
            {caption && (
              <Text fontSize="sm" color="fg.muted" mt={1} lineHeight="1.5">
                {caption}
              </Text>
            )}
          </Box>
          {action}
        </Flex>
      )}
      {children}
    </Box>
  );
}
