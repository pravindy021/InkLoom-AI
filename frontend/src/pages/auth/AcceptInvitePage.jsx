import { useState } from "react";
import { Link, useSearchParams, Navigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";

export default function AcceptInvitePage() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const { user, acceptInvitation } = useAuth();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      await acceptInvitation({ token, password });
    } catch (err) {
      setError(err.message || "Invitation could not be accepted.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 flex items-center justify-center px-5 py-12">
      <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-2xl">
        <p className="text-sm font-bold tracking-widest text-indigo-600">INKLOOM AI</p>
        <h1 className="mt-4 text-3xl font-bold text-slate-900">Accept invitation</h1>
        <p className="mt-2 text-sm text-slate-500">Create your password to join the workspace.</p>

        {!token ? (
          <p className="mt-6 rounded-lg bg-red-50 p-3 text-sm text-red-700">
            Invitation token is missing. Please open the complete invitation link.
          </p>
        ) : (
          <form onSubmit={handleSubmit} className="mt-6 space-y-5">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Create password</label>
              <input
                className="field"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={8}
                autoComplete="new-password"
                placeholder="At least 8 characters"
                required
              />
            </div>
            {error && <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
            <button className="btn-primary w-full justify-center" disabled={submitting}>
              {submitting ? "Accepting..." : "Accept invitation"}
            </button>
          </form>
        )}

        <p className="mt-6 text-center text-sm text-slate-500">
          <Link className="font-semibold text-indigo-600" to="/login">Back to login</Link>
        </p>
      </div>
    </main>
  );
}
