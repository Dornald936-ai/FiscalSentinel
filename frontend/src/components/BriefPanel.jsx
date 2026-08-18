import { useState } from "react";
import { api } from "../api";

// Minimal renderer for the small Markdown subset the brief actually uses:
// #/## headings, **bold**, *italic*, numbered lists, and a closing italic note.
function renderInline(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-[var(--text-primary)]">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

function MarkdownLite({ text }) {
  const lines = text.split("\n");
  const blocks = [];
  let list = [];

  const flushList = () => {
    if (list.length) {
      blocks.push(
        <ol key={`list-${blocks.length}`} className="list-decimal list-inside space-y-1 my-2">
          {list.map((item, i) => (
            <li key={i} className="text-sm text-[var(--text-secondary)]">
              {renderInline(item)}
            </li>
          ))}
        </ol>
      );
      list = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushList();
      continue;
    }
    if (line.startsWith("# ")) {
      flushList();
      blocks.push(
        <h2 key={blocks.length} className="text-base font-semibold text-[var(--text-primary)] mt-3 mb-1 first:mt-0">
          {renderInline(line.slice(2))}
        </h2>
      );
    } else if (line.startsWith("## ")) {
      flushList();
      blocks.push(
        <h3 key={blocks.length} className="text-sm font-semibold text-[var(--text-primary)] mt-3 mb-1">
          {renderInline(line.slice(3))}
        </h3>
      );
    } else if (line.startsWith("### ")) {
      flushList();
      blocks.push(
        <h4 key={blocks.length} className="text-sm font-semibold text-[var(--text-primary)] mt-2 mb-1">
          {renderInline(line.slice(4))}
        </h4>
      );
    } else if (/^\d+\.\s/.test(line)) {
      list.push(line.replace(/^\d+\.\s/, ""));
    } else if (line.startsWith("*") && line.endsWith("*") && !line.startsWith("**")) {
      flushList();
      blocks.push(
        <p key={blocks.length} className="text-xs italic text-[var(--text-muted)] mt-3">
          {line.slice(1, -1)}
        </p>
      );
    } else {
      flushList();
      blocks.push(
        <p key={blocks.length} className="text-sm text-[var(--text-secondary)] leading-relaxed my-1">
          {renderInline(line)}
        </p>
      );
    }
  }
  flushList();
  return <div>{blocks}</div>;
}

export default function BriefPanel() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.generateBrief(5);
      setResult(data);
    } catch (err) {
      setError(err.message || "Failed to generate brief");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-lg border border-[var(--border-hairline)] bg-[var(--surface-card)] p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            Executive Financial Brief
          </h2>
          <p className="text-xs text-[var(--text-muted)]">
            Plain-language summary of the findings above, ready for the finance committee
          </p>
        </div>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={loading}
          className="shrink-0 inline-flex items-center gap-2 rounded-md bg-[var(--series-actual)] text-white text-sm font-medium px-3.5 py-2 hover:opacity-90 disabled:opacity-60 disabled:cursor-not-allowed transition"
        >
          {loading ? "Generating..." : "Generate Financial Brief"}
        </button>
      </div>

      {error && (
        <div className="text-sm text-[var(--status-critical)] bg-[var(--status-critical)]/10 rounded-md px-3 py-2">
          {error}
        </div>
      )}

      {result && (
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs text-[var(--text-muted)]">
            <span className="rounded-full bg-black/[0.04] px-2 py-0.5">
              {result.source === "llm" ? `Model: ${result.model}` : "Deterministic template"}
            </span>
          </div>
          <div className="rounded-md bg-black/[0.015] border border-[var(--border-hairline)] px-4 py-3 max-h-[420px] overflow-y-auto">
            <MarkdownLite text={result.brief} />
          </div>
        </div>
      )}
    </div>
  );
}
