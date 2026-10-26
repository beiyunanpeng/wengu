import katex from "katex";
import { Fragment, useMemo, type CSSProperties } from "react";

type Segment =
  | { kind: "text"; value: string }
  | { kind: "inline"; value: string }
  | { kind: "block"; value: string };

const TOKEN_PATTERN =
  /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+?\$)/g;

function classify(token: string): Segment {
  if (token.startsWith("$$") && token.endsWith("$$")) {
    return { kind: "block", value: token.slice(2, -2) };
  }
  if (token.startsWith("\\[") && token.endsWith("\\]")) {
    return { kind: "block", value: token.slice(2, -2) };
  }
  if (token.startsWith("\\(") && token.endsWith("\\)")) {
    return { kind: "inline", value: token.slice(2, -2) };
  }
  return { kind: "inline", value: token.slice(1, -1) };
}

function parse(text: string): Segment[] {
  if (!text) {
    return [];
  }
  const segments: Segment[] = [];
  let cursor = 0;
  for (const match of text.matchAll(TOKEN_PATTERN)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      segments.push({ kind: "text", value: text.slice(cursor, index) });
    }
    segments.push(classify(match[0]));
    cursor = index + match[0].length;
  }
  if (cursor < text.length) {
    segments.push({ kind: "text", value: text.slice(cursor) });
  }
  return segments;
}

function MathSegment({ segment }: { segment: Segment }) {
  const html = useMemo(
    () =>
      katex.renderToString(segment.value, {
        throwOnError: false,
        displayMode: segment.kind === "block",
        output: "html",
        trust: false,
      }),
    [segment],
  );
  if (segment.kind === "block") {
    return (
      <span
        style={{ display: "block", overflowX: "auto", margin: "0.4em 0" }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

export default function MathText({
  text,
  style,
}: {
  text: string | null | undefined;
  style?: CSSProperties;
}) {
  const segments = useMemo(() => parse(text ?? ""), [text]);
  if (!text) {
    return null;
  }
  return (
    <span style={{ whiteSpace: "pre-wrap", ...style }}>
      {segments.map((segment, index) =>
        segment.kind === "text" ? (
          <Fragment key={index}>{segment.value}</Fragment>
        ) : (
          <MathSegment key={index} segment={segment} />
        ),
      )}
    </span>
  );
}
