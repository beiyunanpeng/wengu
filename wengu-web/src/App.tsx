import { Container, Stack, Title } from "@mantine/core";
import katex from "katex";
import { useMemo } from "react";

const SAMPLE_FORMULA = "a^2 + b^2 = c^2";

export default function App() {
  const formula = useMemo(
    () => katex.renderToString(SAMPLE_FORMULA, { throwOnError: false, output: "html" }),
    [],
  );

  return (
    <Container size="sm" py="xl">
      <Stack align="center" gap="lg">
        <Title order={1}>wengu · 温故</Title>
        <div aria-label="KaTeX render check" dangerouslySetInnerHTML={{ __html: formula }} />
      </Stack>
    </Container>
  );
}
