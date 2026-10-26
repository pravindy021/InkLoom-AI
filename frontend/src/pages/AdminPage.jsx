import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import UserManagement from "../components/settings/UserManagement";
import { ErrorMessage, PageHeader } from "../components/common/UI";
import { api, errorMessage } from "../services/api";

export default function AdminPage() {
  const [mailError, setMailError] = useState("");
  const [mailConfigured, setMailConfigured] = useState(null);

  useEffect(() => {
    let active = true;
    api.health()
      .then((health) => {
        if (active) setMailConfigured(Boolean(health.password_recovery_enabled));
      })
      .catch((error) => {
        if (active) setMailError(errorMessage(error));
      });
    return () => { active = false; };
  }, []);

  return <>
    <PageHeader
      eyebrow="Workspace administration"
      title="Admin dashboard"
      description="Invite members and manage workspace access. New members set their own password through a secure, expiring invitation."
      action={<span className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600"><Users size={16} />Admin tools</span>}
    />
    {mailError && <div className="mb-5"><ErrorMessage>{mailError}</ErrorMessage></div>}
    {mailConfigured === false && <div className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm leading-6 text-amber-900" role="status">Email delivery is not configured. Add SMTP settings to the backend environment and restart the API before sending invitations. Existing member access remains unchanged.</div>}
    <UserManagement />
  </>;
}
