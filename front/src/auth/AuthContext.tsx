import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  clearToken,
  getToken,
  setToken,
  setUnauthorizedHandler,
} from "../api/client";
import type { LoginResponse, Role, User } from "../api/types";

const USER_KEY = "user";

type RegisterInput = {
  username: string;
  email: string;
  password: string;
  role: Role;
};

type AuthContextValue = {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function readCachedUser(): User | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(readCachedUser);
  const [ready, setReady] = useState(() => !getToken());

  useEffect(() => {
    setUnauthorizedHandler(() => {
      localStorage.removeItem(USER_KEY);
      setUser(null);
      navigate("/entrar", { state: { expired: true } });
    });

    return () => setUnauthorizedHandler(null);
  }, [navigate]);

  useEffect(() => {
    if (!getToken()) {
      return;
    }

    api
      .get<User>("/api/auth/me/")
      .then((me) => {
        localStorage.setItem(USER_KEY, JSON.stringify(me));
        setUser(me);
      })
      .catch(() => {
        localStorage.removeItem(USER_KEY);
        setUser(null);
      })
      .finally(() => setReady(true));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const data = await api.post<LoginResponse>(
      "/api/auth/login/",
      { email, password },
      false,
    );
    setToken(data.token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    setUser(data.user);
  }, []);

  const register = useCallback(
    async (input: RegisterInput) => {
      await api.post<User>("/api/auth/register/", input, false);
      await login(input.email, input.password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout/").catch(() => undefined);
    clearToken();
    localStorage.removeItem(USER_KEY);
    setUser(null);
    navigate("/entrar");
  }, [navigate]);

  const value = useMemo(
    () => ({ user, ready, login, register, logout }),
    [user, ready, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth precisa estar dentro de AuthProvider");
  }
  return context;
}
