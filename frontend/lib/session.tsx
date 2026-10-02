"use client";

// Who is signed in, which plan applies and how much of the monthly quota is used.
// One provider in the root layout; every page reads it with useSession().

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getMe, setToken, signOut as apiSignOut, type FeatureKey, type Me } from "./api";

interface SessionState {
  me: Me | null; // null while loading or when the API is unreachable
  loading: boolean;
  refresh: () => Promise<void>;
  signIn: (token: string) => Promise<void>;
  signOut: () => Promise<void>;
  can: (feature: FeatureKey) => boolean;
}

const SessionContext = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setMe(await getMe());
    } catch {
      // An expired token is cleared by the API client; retry once as a guest.
      try {
        setMe(await getMe());
      } catch {
        setMe(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<SessionState>(
    () => ({
      me,
      loading,
      refresh,
      signIn: async (token) => {
        setToken(token);
        await refresh();
      },
      signOut: async () => {
        try {
          await apiSignOut();
        } catch {
          /* already expired */
        }
        setToken(null);
        await refresh();
      },
      can: (feature) => me?.plan.features.includes(feature) ?? false,
    }),
    [me, loading, refresh],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used inside <SessionProvider>");
  return ctx;
}
