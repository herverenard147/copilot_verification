import { useCallback, useEffect, useState } from "react";
import API from "./api.js";

// Compte utilisateur (chantier auth/RGPD) : optionnel, l'app reste
// utilisable en anonyme (cookie de session existant, session_store.py).
// Se connecter n'est nécessaire que pour : consentir à l'apprentissage par
// correction, exporter ses données, supprimer son compte.
export function useAuth() {
  const [userId, setUserId] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const d = await API.me();
      setUserId(d.user_id);
    } catch (e) {
      setUserId(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = useCallback(async (email, password) => {
    const d = await API.login(email, password);
    setUserId(d.user_id);
    return d;
  }, []);

  const register = useCallback(async (email, password) => {
    const d = await API.register(email, password);
    setUserId(d.user_id);
    return d;
  }, []);

  const logout = useCallback(async () => {
    try { await API.logout(); } catch (e) { /* on se déconnecte côté nav quoi qu'il arrive */ }
    setUserId(null);
  }, []);

  return { userId, loading, isAuthenticated: userId != null, login, register, logout, refresh };
}
