import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../../contexts/AuthContext";

export default function RequireAdmin() {
  const { user } = useAuth();
  return user?.role === "admin" ? <Outlet /> : <Navigate to="/" replace />;
}
