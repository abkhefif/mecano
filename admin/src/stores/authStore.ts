import { create } from "zustand";
import api from "../api/client";

interface AuthState {
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem("admin_token"),
  login: async (email, password) => {
    const res = await api.post("/auth/login", { email, password });
    const token = res.data.access_token;
    localStorage.setItem("admin_token", token);
    set({ token });
  },
  logout: () => {
    localStorage.removeItem("admin_token");
    set({ token: null });
  },
}));
