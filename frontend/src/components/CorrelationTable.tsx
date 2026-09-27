import { Badge, Box, Table, TableContainer, Tbody, Td, Text, Th, Thead, Tr } from "@chakra-ui/react";

import type { Correlation } from "../types/analysis";

const strengthScheme: Record<string, string> = {
  strong: "green",
  moderate: "blue",
  weak: "gray",
};

export function CorrelationTable({ correlations }: { correlations: Correlation[] }) {
  if (correlations.length === 0) return null;

  return (
    <Box>
      <Text fontWeight="semibold" fontSize="sm" mb={1}>
        Correlations
      </Text>
      <Text fontSize="xs" color="fg.muted" mb={2}>
        Pearson r across shared periods. Correlation does not imply causation.
      </Text>
      <TableContainer borderWidth="1px" borderColor="border.subtle" rounded="md">
        <Table size="sm">
          <Thead bg="bg.subtle">
            <Tr>
              <Th>Series</Th>
              <Th>Compared with</Th>
              <Th isNumeric>r</Th>
              <Th isNumeric>Periods</Th>
              <Th>Strength</Th>
            </Tr>
          </Thead>
          <Tbody>
            {correlations.map((item) => (
              <Tr key={`${item.a}-${item.b}`}>
                <Td fontSize="xs">{item.a}</Td>
                <Td fontSize="xs">{item.b}</Td>
                <Td isNumeric fontSize="xs">
                  {item.r.toFixed(2)}
                </Td>
                <Td isNumeric fontSize="xs">
                  {item.periods}
                </Td>
                <Td>
                  <Badge colorScheme={strengthScheme[item.strength.split(" ")[0]] ?? "gray"} variant="subtle">
                    {item.strength}
                  </Badge>
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </TableContainer>
    </Box>
  );
}
