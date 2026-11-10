/** How requests are signed, and a nudge to rotate secrets made before Standard Webhooks support. */
export function SignatureHelp({ format }: { format?: "standard" | "legacy" }) {
  return (
    <>
      <p className="muted small">
        Every request is signed twice with this secret. Verify either one: the{" "}
        <a href="https://www.standardwebhooks.com" target="_blank" rel="noreferrer">Standard Webhooks</a>{" "}
        <code className="mono">webhook-signature</code> header, using any of their official libraries, or
        HookFlow&apos;s <code className="mono">HookFlow-Signature</code> header, an HMAC-SHA256 of{" "}
        <code className="mono">{"{timestamp}.{raw body}"}</code>.
      </p>
      {format === "legacy" && (
        <div className="alert alert-warning mb">
          This secret was created before Standard Webhooks support, so the official libraries may not accept it.
          HookFlow&apos;s own signature still works. Rotate the secret to get one that works with both.
        </div>
      )}
    </>
  );
}
