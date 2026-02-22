import { ReactNode } from 'react'
import { useAuthStore } from '../../store/authStore'
import { LoginPage } from './LoginPage'

interface ProtectedRouteProps {
  children: ReactNode
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, isAuthEnabled } = useAuthStore()

  // Show loading state while checking auth
  if (isLoading) {
    return (
      <div className="auth-loading">
        <div className="auth-loading-spinner" />
        <p>Loading...</p>
      </div>
    )
  }

  // If auth is disabled, allow access
  if (!isAuthEnabled) {
    return <>{children}</>
  }

  // If not authenticated, show login page
  if (!isAuthenticated) {
    return <LoginPage />
  }

  // User is authenticated
  return <>{children}</>
}
