"use client";

import { Avatar } from "@/components/Avatar";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, MEMBER_ROLES, type Invite, type Member, type MemberRole, type Role } from "@/lib/api";
import { accountLabel, ROLE_LABEL, useMe } from "@/components/MeContext";
import { ConfirmButton, Empty, ErrorBox, Loading, PageHeader, SecretBox, Time } from "@/components/ui";

/** What each role can do, for the explainer table. Order matches the columns. */
const ROLE_COLUMNS: Role[] = ["viewer", "developer", "admin", "owner"];
const CAPABILITIES: { label: string; roles: Role[] }[] = [
  { label: "View events, deliveries, endpoints and the audit log", roles: ["viewer", "developer", "admin", "owner"] },
  { label: "Send events and replay deliveries", roles: ["developer", "admin", "owner"] },
  { label: "Create and edit endpoints, manage API keys", roles: ["developer", "admin", "owner"] },
  { label: "Invite people, change roles of developers and viewers", roles: ["admin", "owner"] },
  { label: "Invite admins, change or remove admins", roles: ["owner"] },
];

/** Roles the current user may give to others (in invites and role changes). */
function assignableRoles(myRole: Role): MemberRole[] {
  if (myRole === "owner") return MEMBER_ROLES;
  if (myRole === "admin") return MEMBER_ROLES.filter((r) => r !== "admin");
  return [];
}

/** Whether the current user may change or remove this member (mirrors the backend rules). */
function canManageMember(myRole: Role, myId: string, m: Member): boolean {
  if (m.role === "owner" || m.user_id === myId) return false;
  if (myRole === "owner") return true;
  return myRole === "admin" && m.role !== "admin";
}

function RoleBadge({ role }: { role: Role }) {
  return <span className={`badge role-badge role-${role}`}>{ROLE_LABEL[role]}</span>;
}

export default function TeamPage() {
  const { me, can, refresh } = useMe();
  const manage = can("team:manage");

  const [members, setMembers] = useState<Member[] | null>(null);
  const [membersErr, setMembersErr] = useState<unknown>(null);
  const [invites, setInvites] = useState<Invite[] | null>(null);
  const [invitesErr, setInvitesErr] = useState<unknown>(null);
  const [actionErr, setActionErr] = useState<unknown>(null);
  const [savingRole, setSavingRole] = useState<string | null>(null);

  const [email, setEmail] = useState("");
  const [role, setRole] = useState<MemberRole>("developer");
  const [inviting, setInviting] = useState(false);
  const [inviteErr, setInviteErr] = useState<unknown>(null);
  const [created, setCreated] = useState<{ email: string; role: MemberRole; link: string } | null>(null);

  const [leaveErr, setLeaveErr] = useState<unknown>(null);

  const loadMembers = useCallback(async () => {
    setMembersErr(null);
    try {
      setMembers((await api.listMembers()).data);
    } catch (e) {
      setMembersErr(e);
    }
  }, []);

  const loadInvites = useCallback(async () => {
    setInvitesErr(null);
    try {
      setInvites((await api.listInvites()).data);
    } catch (e) {
      setInvitesErr(e);
    }
  }, []);

  useEffect(() => {
    void loadMembers();
  }, [loadMembers]);

  useEffect(() => {
    if (manage) void loadInvites();
  }, [manage, loadInvites]);

  /** A 403 usually means our role changed under us: re-read who we are and what's there. */
  async function onActionError(err: unknown) {
    setActionErr(err);
    if (err instanceof ApiError && (err.status === 403 || err.status === 404)) {
      await Promise.all([refresh(), loadMembers()]);
    }
  }

  async function changeRole(m: Member, next: MemberRole) {
    if (next === m.role) return;
    setActionErr(null);
    setSavingRole(m.user_id);
    try {
      const updated = await api.updateMember(m.user_id, next);
      setMembers((prev) => (prev ?? []).map((x) => (x.user_id === m.user_id ? updated : x)));
    } catch (err) {
      await onActionError(err);
    } finally {
      setSavingRole(null);
    }
  }

  async function remove(m: Member) {
    setActionErr(null);
    try {
      await api.removeMember(m.user_id);
      setMembers((prev) => (prev ?? []).filter((x) => x.user_id !== m.user_id));
    } catch (err) {
      await onActionError(err);
    }
  }

  async function leave() {
    if (!me) return;
    setLeaveErr(null);
    try {
      await api.removeMember(me.user.id);
      // This session is back in the personal account; reload so nothing from the team stays on screen.
      window.location.assign("/overview");
    } catch (err) {
      setLeaveErr(err);
    }
  }

  async function invite(e: FormEvent) {
    e.preventDefault();
    const addr = email.trim();
    if (!addr) return;
    setInviting(true);
    setInviteErr(null);
    try {
      const res = await api.createInvite(addr, role);
      setCreated({ email: res.invite.email, role: res.invite.role, link: window.location.origin + res.accept_path });
      setEmail("");
      // A new invite to the same email replaces the old one, so re-read the list rather than prepend.
      void loadInvites();
    } catch (err) {
      setInviteErr(err);
      if (err instanceof ApiError && err.status === 403) void refresh();
    } finally {
      setInviting(false);
    }
  }

  async function revoke(inv: Invite) {
    setActionErr(null);
    try {
      await api.revokeInvite(inv.id);
      setInvites((prev) => (prev ?? []).filter((x) => x.id !== inv.id));
      if (created && created.email === inv.email) setCreated(null);
    } catch (err) {
      await onActionError(err);
    }
  }

  if (!me) {
    return (
      <div className="page">
        <PageHeader title="Team" />
        <Loading />
      </div>
    );
  }

  const myRole = me.account.role;
  const roles = assignableRoles(myRole);
  const inviteRole = roles.includes(role) ? role : (roles[0] ?? "developer");

  return (
    <div className="page">
      <PageHeader
        title="Team"
        sub={
          <>
            People with access to{" "}
            {me.account.personal ? (
              "your personal account"
            ) : (
              <strong className="team-account">{accountLabel(me.account)}</strong>
            )}
            . You&apos;re{" "}
            {myRole === "owner" ? "the owner" : `a${myRole === "admin" ? "n" : ""} ${ROLE_LABEL[myRole].toLowerCase()}`}
            {manage ? "." : " — only owners and admins can invite people or change roles."}
          </>
        }
        actions={
          myRole !== "owner" ? (
            <ConfirmButton
              label="Leave team"
              prompt="You'll lose access to this account until someone invites you again."
              confirmLabel="Leave"
              onConfirm={leave}
            />
          ) : undefined
        }
      />
      <ErrorBox error={leaveErr} />

      {manage && (
        <section className="card">
          <div className="card-head">
            <h2>Invite someone</h2>
            <span className="muted small">No email is sent — you share the link yourself.</span>
          </div>
          <form onSubmit={invite} className="inline-form">
            <label className="field grow">
              <span className="field-label">Email</span>
              <input
                type="email"
                className="input"
                placeholder="teammate@example.com"
                autoComplete="off"
                value={email}
                maxLength={320}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field-label">Role</span>
              <select
                className="input select team-role-select"
                value={inviteRole}
                onChange={(e) => setRole(e.target.value as MemberRole)}
              >
                {roles.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABEL[r]}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="btn btn-primary" disabled={inviting || !email.trim()}>
              {inviting ? "Creating link…" : "Create invite link"}
            </button>
          </form>
          {myRole === "admin" && (
            <p className="field-hint team-hint">Only the account owner can invite admins.</p>
          )}
          <ErrorBox error={inviteErr} />

          {created && (
            <div className="stack mt">
              <SecretBox
                title={`Invite link for ${created.email} (${ROLE_LABEL[created.role]})`}
                value={created.link}
                warning={
                  <>
                    Copy this link now and send it to {created.email} — it won&apos;t be shown again. It works for 7
                    days, once, and only for someone logged in as that email. Creating another invite for the same
                    email cancels this link.
                  </>
                }
              />
              <div>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => setCreated(null)}>
                  I&apos;ve shared it — dismiss
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      <section className="card">
        <div className="card-head">
          <h2>Members</h2>
          {members && <span className="muted small">{members.length} {members.length === 1 ? "person" : "people"}</span>}
        </div>
        <ErrorBox error={membersErr} onRetry={loadMembers} />
        <ErrorBox error={actionErr} />
        {!members && !membersErr && <Loading />}
        {members && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Joined</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {members.map((m) => {
                  const editable = canManageMember(myRole, me.user.id, m);
                  // An admin's own row can't be edited; the dropdown also never offers roles they can't grant.
                  const options = editable ? roles : [];
                  return (
                    <tr key={m.user_id}>
                      <td>
                        <span className="person">
                          <Avatar email={m.email} self={m.user_id === me.user.id} />
                          <span className="team-email">{m.email}</span>
                        </span>
                        {m.user_id === me.user.id && <span className="badge badge-grey team-you">You</span>}
                      </td>
                      <td>
                        {editable && options.length > 0 ? (
                          <select
                            className="input select team-role-select"
                            aria-label={`Role for ${m.email}`}
                            value={m.role}
                            disabled={savingRole === m.user_id}
                            onChange={(e) => void changeRole(m, e.target.value as MemberRole)}
                          >
                            {options.map((r) => (
                              <option key={r} value={r}>
                                {ROLE_LABEL[r]}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <RoleBadge role={m.role} />
                        )}
                      </td>
                      <td>
                        <Time iso={m.joined_at} />
                      </td>
                      <td className="right actions-cell">
                        {editable && (
                          <ConfirmButton
                            small
                            label="Remove"
                            prompt={`${m.email} loses access right away.`}
                            confirmLabel="Remove"
                            onConfirm={() => remove(m)}
                          />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {members && members.length === 1 && manage && (
          <p className="muted small team-hint">Just you so far. Invite someone above to give them access.</p>
        )}
      </section>

      {manage && (
        <section className="card">
          <div className="card-head">
            <h2>Open invites</h2>
          </div>
          <ErrorBox error={invitesErr} onRetry={loadInvites} />
          {!invites && !invitesErr && <Loading />}
          {invites && invites.length === 0 && (
            <Empty title="No open invites">Links that haven&apos;t been used yet show up here until they expire.</Empty>
          )}
          {invites && invites.length > 0 && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Created</th>
                    <th>Expires</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {invites.map((inv) => (
                    <tr key={inv.id}>
                      <td className="team-email">{inv.email}</td>
                      <td>
                        <RoleBadge role={inv.role} />
                      </td>
                      <td>
                        <Time iso={inv.created_at} />
                      </td>
                      <td>
                        <Time iso={inv.expires_at} />
                      </td>
                      <td className="right actions-cell">
                        {inv.role !== "admin" || myRole === "owner" ? (
                          <ConfirmButton
                            small
                            label="Revoke"
                            prompt="The link stops working."
                            confirmLabel="Revoke"
                            onConfirm={() => revoke(inv)}
                          />
                        ) : (
                          <span className="muted small">Owner only</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      <section className="card">
        <div className="card-head">
          <h2>Roles</h2>
          <span className="muted small">Each account has one owner. Roles apply only within this account.</span>
        </div>
        <div className="table-wrap">
          <table className="table role-matrix">
            <thead>
              <tr>
                <th>Can</th>
                {ROLE_COLUMNS.map((r) => (
                  <th key={r} className={`center${r === myRole ? " role-mine" : ""}`}>
                    {ROLE_LABEL[r]}
                    {r === myRole && <span className="sr-only"> (your role)</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CAPABILITIES.map((c) => (
                <tr key={c.label}>
                  <td>{c.label}</td>
                  {ROLE_COLUMNS.map((r) => (
                    <td key={r} className={`center${r === myRole ? " role-mine" : ""}`}>
                      {c.roles.includes(r) ? (
                        <span className="role-yes" aria-label="Yes">✓</span>
                      ) : (
                        <span className="role-no" aria-label="No">—</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
