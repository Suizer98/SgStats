import { extendTheme, type ThemeConfig } from "@chakra-ui/react";

const config: ThemeConfig = {
  initialColorMode: "light",
  useSystemColorMode: false,
};

export const theme = extendTheme({
  config,
  fonts: {
    heading: "'Segoe UI', 'Open Sans', system-ui, sans-serif",
    body: "'Segoe UI', 'Open Sans', system-ui, sans-serif",
  },
  colors: {
    brand: {
      50: "#eef3fa",
      100: "#d8e2f1",
      200: "#b5c8e2",
      500: "#244b7c",
      600: "#193d6a",
      700: "#102f59",
      800: "#0b264b",
      900: "#071b38",
    },
    civic: {
      red: "#d92d20",
      navy: "#102f59",
    },
  },
  radii: {
    sm: "3px",
    md: "4px",
    lg: "6px",
  },
  semanticTokens: {
    colors: {
      "bg.canvas": { default: "#f5f7fa", _dark: "#101820" },
      "bg.surface": { default: "#ffffff", _dark: "#18232f" },
      "bg.subtle": { default: "#f7f8fa", _dark: "whiteAlpha.100" },
      "bg.active": { default: "#eef3fa", _dark: "#193d6a" },
      "border.subtle": { default: "#d9dee7", _dark: "whiteAlpha.300" },
      "border.accent": { default: "#244b7c", _dark: "#8aa8cf" },
      "fg.default": { default: "#1b2634", _dark: "#f1f4f7" },
      "fg.muted": { default: "#617083", _dark: "#aeb9c5" },
      "fg.faint": { default: "#46566a", _dark: "#c5ced7" },
    },
  },
  styles: {
    global: {
      body: {
        bg: "bg.canvas",
        color: "fg.default",
        fontSize: "16px",
        lineHeight: "1.5",
        letterSpacing: "0",
      },
      "::selection": {
        bg: "brand.100",
        color: "brand.900",
      },
    },
  },
  components: {
    Heading: {
      baseStyle: {
        color: "fg.default",
        fontWeight: "700",
        letterSpacing: "-0.015em",
      },
    },
    Button: {
      baseStyle: {
        borderRadius: "sm",
        fontWeight: "600",
      },
      defaultProps: {
        colorScheme: "brand",
      },
    },
    Badge: {
      baseStyle: {
        borderRadius: "sm",
        fontWeight: "600",
        letterSpacing: "0.015em",
        textTransform: "none",
      },
    },
    Textarea: {
      baseStyle: {
        borderRadius: "sm",
      },
      variants: {
        outline: {
          borderColor: "border.subtle",
          _hover: { borderColor: "brand.500" },
          _focusVisible: {
            borderColor: "brand.500",
            boxShadow: "0 0 0 1px #244b7c",
          },
        },
      },
    },
  },
});
