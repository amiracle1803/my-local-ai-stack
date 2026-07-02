/** Renders a job result as clean readable text, not raw JSON. */
export function extractText(raw: unknown): string {
  if (!raw) return "";
  if (typeof raw === "string") return raw.trim();
  if (typeof raw === "object" && raw !== null) {
    const o = raw as Record<string, unknown>;
    // Common response envelope shapes
    const text =
      o.response ?? o.result ?? o.output ?? o.content ?? o.message ?? o.answer ?? o.summary;
    if (typeof text === "string") return text.trim();
    if (typeof text === "object") return extractText(text);
    // Last resort: pretty JSON
    return JSON.stringify(raw, null, 2);
  }
  return String(raw);
}

export default function ResultView({ result }: { result: unknown }) {
  const text = extractText(result);
  if (!text) return null;

  // Detect if the text is actually JSON (shouldn't be after extraction, but guard)
  const isCode = text.startsWith("{") || text.startsWith("[");

  if (isCode) {
    return <pre className="codeblock">{text}</pre>;
  }

  // Render as readable paragraphs — split on double newlines and markdown headers
  const lines = text.split("\n");
  return (
    <div style={{ fontSize: 13, lineHeight: 1.75, color: "var(--text)", maxWidth: 720 }}>
      {lines.map((line, i) => {
        const trimmed = line.trim();

        if (!trimmed) return <div key={i} style={{ height: 8 }} />;

        // ### Header
        if (trimmed.startsWith("### ")) {
          return <h4 key={i} style={{ fontSize: 13, fontWeight: 700, color: "var(--text2)", margin: "14px 0 4px", textTransform: "uppercase", letterSpacing: ".05em" }}>{trimmed.slice(4)}</h4>;
        }
        if (trimmed.startsWith("## ")) {
          return <h3 key={i} style={{ fontSize: 15, fontWeight: 700, margin: "18px 0 5px" }}>{trimmed.slice(3)}</h3>;
        }
        if (trimmed.startsWith("# ")) {
          return <h2 key={i} style={{ fontSize: 17, fontWeight: 800, margin: "20px 0 6px" }}>{trimmed.slice(2)}</h2>;
        }

        // Bullet
        if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
          return (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4 }}>
              <span style={{ color: "var(--accent2)", flexShrink: 0, marginTop: 1 }}>•</span>
              <span>{inlineFmt(trimmed.slice(2))}</span>
            </div>
          );
        }

        // Numbered list
        const numMatch = trimmed.match(/^(\d+)\.\s(.+)/);
        if (numMatch) {
          return (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4 }}>
              <span style={{ color: "var(--text3)", flexShrink: 0, minWidth: 18, fontFamily: "var(--mono)", fontSize: 12 }}>{numMatch[1]}.</span>
              <span>{inlineFmt(numMatch[2])}</span>
            </div>
          );
        }

        // Bold section heading (e.g. "**Title:**")
        if (trimmed.startsWith("**") && trimmed.endsWith("**")) {
          return <div key={i} style={{ fontWeight: 700, margin: "10px 0 3px" }}>{trimmed.replace(/\*\*/g, "")}</div>;
        }

        // Separator
        if (trimmed === "---" || trimmed === "***") {
          return <hr key={i} className="divider" />;
        }

        return <p key={i} style={{ margin: "0 0 6px" }}>{inlineFmt(trimmed)}</p>;
      })}
    </div>
  );
}

/** Bold and inline-code within a line */
function inlineFmt(text: string): React.ReactNode {
  // Split on **bold** and `code`
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={i} style={{ fontFamily: "var(--mono)", fontSize: 12, background: "var(--s3)", padding: "1px 5px", borderRadius: 3 }}>{part.slice(1, -1)}</code>;
    }
    return part;
  });
}
