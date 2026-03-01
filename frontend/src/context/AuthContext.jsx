import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import api from '../lib/api'

const AuthContext = createContext(undefined)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(localStorage.getItem('tw_access_token'))
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const bootstrapAuth = async () => {
      const existingToken = localStorage.getItem('tw_access_token')
      if (!existingToken) {
        setLoading(false)
        return
      }

      try {
        const res = await api.get('/auth/me')
        setToken(existingToken)
        setUser(res.data)
      } catch {
        localStorage.removeItem('tw_access_token')
        localStorage.removeItem('tw_refresh_token')
        setToken(null)
        setUser(null)
      } finally {
        setLoading(false)
      }
    }

    bootstrapAuth()
  }, [])

  const login = (nextToken, nextUser, nextRefreshToken = null) => {
    localStorage.setItem('tw_access_token', nextToken)
    if (nextRefreshToken) {
      localStorage.setItem('tw_refresh_token', nextRefreshToken)
    }
    setToken(nextToken)
    setUser(nextUser)
  }

  const logout = () => {
    localStorage.removeItem('tw_access_token')
    localStorage.removeItem('tw_refresh_token')
    setToken(null)
    setUser(null)
  }

  const value = useMemo(
    () => ({
      user,
      token,
      loading,
      login,
      logout,
    }),
    [user, token, loading],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}
