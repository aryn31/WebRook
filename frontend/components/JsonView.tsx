import { Fragment } from "react";

/** Pretty-printed JSON with keys, strings, numbers and literals in different colours. */
export function JsonView({ text }: { text: string }) {
  const parts: React.ReactNode[] = [];
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(<Fragment key={k++}>{text.slice(last, m.index)}</Fragment>);
    if (m[1]) {
      parts.push(<span key={k++} className={m[2] ? "j-key" : "j-str"}>{m[1]}</span>);
      if (m[2]) parts.push(<Fragment key={k++}>{m[2]}</Fragment>);
    } else if (m[3]) parts.push(<span key={k++} className="j-lit">{m[3]}</span>);
    else parts.push(<span key={k++} className="j-num">{m[4]}</span>);
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(<Fragment key={k++}>{text.slice(last)}</Fragment>);
  return <pre className="mono payload json-view">{parts}</pre>;
}
