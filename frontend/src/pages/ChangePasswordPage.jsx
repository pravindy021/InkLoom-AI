import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound } from "lucide-react";
import { api } from "../services/api";
import { useAuth } from "../contexts/AuthContext";
import { ErrorMessage } from "../components/common/UI";

export default function ChangePasswordPage() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    if (newPassword !== confirmPassword) {
      setError("The new passwords do not match.");
      return;
    }
    setSaving(true);
    try {
      const result = await api.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setUser(result.user);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.message || "Password could not be updated.");
    } finally {
      setSaving(false);
    }
  };

  return <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-12">
    <section className="card w-full max-w-md p-6 sm:p-8">
      <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-ink-50 text-ink-700"><KeyRound size={21} /></div>
      <h1 className="text-xl font-bold text-ink-900">{user?.must_change_password ? "Set your password" : "Change password"}</h1>
      <p className="mt-1 text-sm leading-6 text-slate-500">{user?.must_change_password ? "Your invitation password can only be used to sign in and set a new password." : "Choose a new password for your workspace account."} Use at least 12 characters.</p>
      {error && <div className="mt-5"><ErrorMessage>{error}</ErrorMessage></div>}
      <form onSubmit={submit} className="mt-6 space-y-4">
        <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="current-password">Current password</label><input id="current-password" type="password" autoComplete="current-password" required maxLength={128} value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="field" /></div>
        <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="new-password">New password</label><input id="new-password" type="password" autoComplete="new-password" minLength={12} required maxLength={128} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="field" /></div>
        <div><label className="mb-1.5 block text-sm font-medium text-slate-700" htmlFor="confirm-password">Confirm new password</label><input id="confirm-password" type="password" autoComplete="new-password" minLength={12} required maxLength={128} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className="field" /></div>
        <button className="btn-primary w-full justify-center" type="submit" disabled={saving}>{saving ? "Saving…" : "Save password"}</button>
      </form>
    </section>
  </main>;
}
