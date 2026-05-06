import { create } from 'zustand'
import { setToken, clearToken, getToken } from '@/lib/api'

interface AuthState {
  isAuthenticated: boolean
  login: (token: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: !!getToken(),
  login: (token: string) => {
    setToken(token)
    set({ isAuthenticated: true })
  },
  logout: () => {
    clearToken()
    set({ isAuthenticated: false })
  },
}))
