"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, errorMessage } from "@/lib/api";

const TOPICS = [
  { value: "question", label: "General question" },
  { value: "support", label: "Help with my account" },
  { value: "sales", label: "Pricing or sales" },
  { value: "bug", label: "Bug report" },
  { value: "other", label: "Other" },
];
const MAX = 5000;

export function ContactForm() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [topic, setTopic] = useState("question");
  const [message, setMessage] = useState("");
  const [website, setWebsite] = useState(""); // hidden; only bots fill it in
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  // Logged in? Fill in the email (and pick "Help with my account") to save typing.
  useEffect(() => {
    fetch("/api/v1/auth/me", { credentials: "same-origin", cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((me) => {
        if (me?.user?.email) {
          setEmail((e) => e || me.user.email);
          setTopic((t) => (t === "question" ? "support" : t));
        }
      })
      .catch(() => {});
  }, []);

  const tooShort = message.trim().length > 0 && message.trim().length < 10;
  const ready = name.trim() && /\S+@\S+\.\S+/.test(email) && message.trim().length >= 10;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.contact({ name: name.trim(), email: email.trim(), topic, message: message.trim(), website });
      setSent(res.message);
      setMessage("");
    } catch (err) {
      setError(err instanceof ApiError && err.code === "rate_limited"
        ? "You've sent several messages in the last hour. Please wait a bit, or email us directly."
        : errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="contact-sent" role="status">
        <span className="contact-sent-icon" aria-hidden>✓</span>
        <h2>Message sent</h2>
        <p className="muted">{sent}</p>
        <button type="button" className="btn" onClick={() => setSent(null)}>Send another message</button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="stack" noValidate>
      <div className="contact-row">
        <label className="field">
          <span className="field-label">Name</span>
          <input className="input" autoComplete="name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} required />
        </label>
        <label className="field">
          <span className="field-label">Email</span>
          <input className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
      </div>
      <fieldset className="field contact-topics">
        <legend className="field-label">What&apos;s it about?</legend>
        <div className="contact-chips">
          {TOPICS.map((t) => (
            <label key={t.value} className={`contact-chip${topic === t.value ? " active" : ""}`}>
              <input type="radio" name="topic" value={t.value} checked={topic === t.value} onChange={() => setTopic(t.value)} />
              {t.label}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="field">
        <span className="field-label">Message</span>
        <textarea
          className="input textarea contact-message"
          rows={7}
          maxLength={MAX}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={topic === "bug" ? "What happened, what you expected, and an event or delivery ID if you have one." : "How can we help?"}
          required
        />
        <span className={`field-hint contact-count${tooShort ? " field-hint-error" : ""}`}>
          {tooShort ? "A little more detail, please (at least 10 characters)." : `${message.length} / ${MAX}`}
        </span>
      </label>
      <label className="contact-hp" aria-hidden>
        Website
        <input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
      </label>
      {error && (
        <div className="alert alert-error" role="alert"><strong>{error}</strong></div>
      )}
      <div className="contact-submit">
        <button type="submit" className="btn btn-signal btn-lg" disabled={busy || !ready}>
          {busy ? "Sending…" : "Send message"}
        </button>
        <span className="muted small">We&apos;ll only use your email to reply.</span>
      </div>
    </form>
  );
}
