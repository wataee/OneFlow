import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import { apiClient } from '@/api/client';
import type { User } from '@/types';

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('access_token'));
  const user = ref<User | null>(null);
  const loading = ref(false);

  const isAuthenticated = computed(() => !!token.value);

  const setToken = (newToken: string | null) => {
    token.value = newToken;
    if (newToken) {
      localStorage.setItem('access_token', newToken);
    } else {
      localStorage.removeItem('access_token');
    }
  };

  const fetchCurrentUser = async () => {
    if (!token.value) return;
    try {
      loading.value = true;
      const resp = await apiClient.get<User>('/auth/me');
      user.value = resp.data;
    } catch {
      setToken(null);
      user.value = null;
    } finally {
      loading.value = false;
    }
  };

  const login = async (email: string, password: string) => {
    loading.value = true;
    try {
      const resp = await apiClient.post<{ access_token: string }>('/auth/login', { email, password });
      setToken(resp.data.access_token);
      await fetchCurrentUser();
    } finally {
      loading.value = false;
    }
  };

  const register = async (email: string, password: string, fullName: string, orgName: string) => {
    loading.value = true;
    try {
      const resp = await apiClient.post<{ access_token: string }>('/auth/register', {
        email,
        password,
        full_name: fullName,
        organization_name: orgName,
      });
      setToken(resp.data.access_token);
      await fetchCurrentUser();
    } finally {
      loading.value = false;
    }
  };

  const logout = async () => {
    try {
      await apiClient.post('/auth/logout');
    } catch {
      // ignore
    } finally {
      setToken(null);
      user.value = null;
      window.location.href = '/login';
    }
  };

  return {
    token,
    user,
    loading,
    isAuthenticated,
    login,
    register,
    fetchCurrentUser,
    logout,
  };
});
