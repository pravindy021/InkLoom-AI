import { useEffect, useState } from "react";
import { MailPlus, RefreshCw, Users } from "lucide-react";
import { api, errorMessage } from "../../services/api";
import { EmptyState, ErrorMessage, SuccessMessage } from "../common/UI";

const ROLE_LABELS = {
  admin: "Admin",
  reviewer: "Reviewer",
  contributor: "Contributor",
};

export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState({ email: "", display_name: "", role: "contributor" });
  const [saving, setSaving] = useState(false);
  const [resending, setResending] = useState(null);

  const load = async () => {
    setError("");
    setLoading(true);
    try {
      setUsers(await api.users());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const invite = async (event) => {
    event.preventDefault();
    setError("");
    setNotice("");
    setSaving(true);
    try {
      await api.createUser(form);
      setNotice(`Invitation sent to ${form.email.trim()}. The member will create their password using the email link.`);
      setForm({ email: "", display_name: "", role: "contributor" });
      await load();
    } catch (err) {
      await load();
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const resend = async (user) => {
    setError("");
    setNotice("");
    setResending(user.id);
    try {
      await api.resendInvitation(user.id);
      setNotice(`A new invitation was sent to ${user.email}. Any previous invitation link has been invalidated.`);
      await load();
    } catch (err) {
      await load();
      setError(errorMessage(err));
    } finally {
      setResending(null);
    }
  };

  const update = async (user, changes) => {
    setError("");
    setNotice("");
    try {
      const updated = await api.updateUser(user.id, {
        role: changes.role ?? user.role,
        is_active: changes.is_active ?? user.is_active,
      });
      setUsers((current) => current.map((entry) => entry.id === updated.id ? updated : entry));
      setNotice(`${updated.display_name}'s account was updated.`);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return <section className="card p-5 sm:p-6">
    <div className="flex items-start gap-3">
      <div className="rounded-lg bg-ink-50 p-2.5 text-ink-700"><Users size={19} /></div>
      <div><h2 className="font-semibold text-ink-900">Workspace members</h2><p className="mt-1 text-sm text-slate-500">New members receive an expiring, single-use email invitation and choose their own password. API role checks enforce these assignments.</p></div>
    </div>
    {error && <div className="mt-4"><ErrorMessage>{error}</ErrorMessage></div>}
    {notice && <div className="mt-4"><SuccessMessage>{notice}</SuccessMessage></div>}
    <form onSubmit={invite} className="mt-5 grid gap-3 rounded-lg border border-slate-200 p-4 sm:grid-cols-2">
      <label className="text-xs font-medium text-slate-600">Name<input required maxLength={120} className="field mt-1.5" autoComplete="name" value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} /></label>
      <label className="text-xs font-medium text-slate-600">Email<input required type="email" maxLength={254} className="field mt-1.5" autoComplete="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
      <label className="text-xs font-medium text-slate-600">Assigned role<select className="field mt-1.5" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value })}>{Object.entries(ROLE_LABELS).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <button type="submit" className="btn-primary self-end" disabled={saving}><MailPlus size={16} />{saving ? "Sending invitation…" : "Invite user"}</button>
    </form>
    <div className="mt-5 overflow-x-auto">
      {loading ? <p role="status" className="py-5 text-sm text-slate-500">Loading workspace members…</p> : users.length === 0 ? <EmptyState title="No workspace members" description="Invite your first teammate to get started." icon={Users} /> : <table className="w-full min-w-[650px] text-left text-sm">
        <thead><tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400"><th className="py-2 pr-3 font-medium">Member</th><th className="py-2 pr-3 font-medium">Role</th><th className="py-2 pr-3 font-medium">Status</th><th className="py-2 font-medium">Account access</th></tr></thead>
        <tbody className="divide-y divide-slate-100">{users.map((user) => <tr key={user.id}>
          <td className="py-3 pr-3"><p className="font-medium text-slate-700">{user.display_name}</p><p className="text-xs text-slate-400">{user.email}</p></td>
          <td className="py-3 pr-3"><select aria-label={`Role for ${user.display_name}`} className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs disabled:bg-slate-50" value={user.role} disabled={user.must_change_password} onChange={(event) => update(user, { role: event.target.value })}><option value="admin">Admin</option><option value="reviewer">Reviewer</option><option value="contributor">Contributor</option></select></td>
          <td className="py-3 pr-3"><span className={`rounded-full px-2 py-1 text-xs font-medium ${user.invitation_expired ? "bg-rose-50 text-rose-700" : user.invitation_pending ? "bg-amber-50 text-amber-700" : user.is_active ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{user.invitation_expired ? "Invitation expired" : user.invitation_pending ? "Invitation pending" : user.is_active ? "Active" : "Deactivated"}</span></td>
          <td className="py-3">{user.invitation_pending ? <button type="button" className="inline-flex items-center gap-1 text-xs font-medium text-ink-700 underline disabled:text-slate-400" disabled={resending === user.id} onClick={() => resend(user)}><RefreshCw size={13} className={resending === user.id ? "animate-spin" : ""} />{resending === user.id ? "Sending…" : "Resend invite"}</button> : <button type="button" className="text-xs font-medium text-ink-700 underline disabled:text-slate-400" disabled={user.role === "admin" && user.is_active && users.filter((entry) => entry.role === "admin" && entry.is_active).length === 1} onClick={() => update(user, { is_active: !user.is_active })}>{user.is_active ? "Deactivate" : "Reactivate"}</button>}</td>
        </tr>)}</tbody>
      </table>}
    </div>
  </section>;
}
