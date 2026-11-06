import { createContext, useContext, useEffect, useState } from "react";
import { authApi } from "../services/api";

const AuthContext = createContext(null);
const TOKEN_KEY = "inkloom_access_token";
const USER_KEY = "inkloom_user";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY));
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);

  const saveSession = (data) => {
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    setUser(data.user);
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setUser(null);
  };

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);

    if (!token) {
      setLoading(false);
      return;
    }

    authApi.me()
      .then((data) => {
        setUser(data.user || data);
        localStorage.setItem(USER_KEY, JSON.stringify(data.user || data));
      })
      .catch(() => logout())
      .finally(() => setLoading(false));
  }, []);

  const login = async (credentials) => {
    const data = await authApi.login(credentials);
    saveSession(data);
    return data;
  };

  const acceptInvitation = async (payload) => {
    const data = await authApi.acceptInvite(payload);
    if (data.access_token && data.user) saveSession(data);
    return data;
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, acceptInvitation }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
