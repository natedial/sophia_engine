import { useState, FormEvent } from 'react'
import { useAuthStore } from '../../store/authStore'
import './Auth.css'

type AuthMode = 'login' | 'register' | 'confirm'

export function LoginPage() {
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [confirmationCode, setConfirmationCode] = useState('')
  const [pendingEmail, setPendingEmail] = useState('')

  const { login, register, confirmRegistration, isLoading, error, clearError } =
    useAuthStore()

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault()
    clearError()

    try {
      await login(email, password)
    } catch {
      // Error is handled in store
    }
  }

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault()
    clearError()

    if (password !== confirmPassword) {
      return
    }

    try {
      const result = await register(email, password)
      if (result.requiresConfirmation) {
        setPendingEmail(email)
        setMode('confirm')
      }
    } catch {
      // Error is handled in store
    }
  }

  const handleConfirm = async (e: FormEvent) => {
    e.preventDefault()
    clearError()

    try {
      await confirmRegistration(pendingEmail, confirmationCode)
      // After confirmation, switch to login
      setMode('login')
      setEmail(pendingEmail)
      setPassword('')
    } catch {
      // Error is handled in store
    }
  }

  const switchMode = (newMode: AuthMode) => {
    clearError()
    setMode(newMode)
  }

  return (
    <div className="auth-page">
      <div className="auth-container">
        <div className="auth-header">
          <h1 className="auth-title">Sophia Canvas</h1>
          <p className="auth-subtitle">Economic Analysis Dashboard</p>
        </div>

        {mode === 'login' && (
          <form className="auth-form" onSubmit={handleLogin}>
            <h2>Sign In</h2>

            {error && <div className="auth-error">{error}</div>}

            <div className="form-group">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email"
                required
                disabled={isLoading}
              />
            </div>

            <div className="form-group">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                required
                disabled={isLoading}
              />
            </div>

            <button
              type="submit"
              className="auth-button"
              disabled={isLoading}
            >
              {isLoading ? 'Signing in...' : 'Sign In'}
            </button>

            <p className="auth-switch">
              Don't have an account?{' '}
              <button
                type="button"
                className="auth-link"
                onClick={() => switchMode('register')}
              >
                Register
              </button>
            </p>
          </form>
        )}

        {mode === 'register' && (
          <form className="auth-form" onSubmit={handleRegister}>
            <h2>Create Account</h2>

            {error && <div className="auth-error">{error}</div>}

            <div className="form-group">
              <label htmlFor="reg-email">Email</label>
              <input
                id="reg-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Enter your email"
                required
                disabled={isLoading}
              />
            </div>

            <div className="form-group">
              <label htmlFor="reg-password">Password</label>
              <input
                id="reg-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Create a password"
                required
                minLength={8}
                disabled={isLoading}
              />
            </div>

            <div className="form-group">
              <label htmlFor="reg-confirm">Confirm Password</label>
              <input
                id="reg-confirm"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Confirm your password"
                required
                disabled={isLoading}
              />
              {password !== confirmPassword && confirmPassword && (
                <span className="field-error">Passwords do not match</span>
              )}
            </div>

            <button
              type="submit"
              className="auth-button"
              disabled={isLoading || password !== confirmPassword}
            >
              {isLoading ? 'Creating account...' : 'Create Account'}
            </button>

            <p className="auth-switch">
              Already have an account?{' '}
              <button
                type="button"
                className="auth-link"
                onClick={() => switchMode('login')}
              >
                Sign In
              </button>
            </p>
          </form>
        )}

        {mode === 'confirm' && (
          <form className="auth-form" onSubmit={handleConfirm}>
            <h2>Verify Email</h2>
            <p className="auth-message">
              We sent a verification code to <strong>{pendingEmail}</strong>
            </p>

            {error && <div className="auth-error">{error}</div>}

            <div className="form-group">
              <label htmlFor="code">Verification Code</label>
              <input
                id="code"
                type="text"
                value={confirmationCode}
                onChange={(e) => setConfirmationCode(e.target.value)}
                placeholder="Enter 6-digit code"
                required
                disabled={isLoading}
              />
            </div>

            <button
              type="submit"
              className="auth-button"
              disabled={isLoading}
            >
              {isLoading ? 'Verifying...' : 'Verify'}
            </button>

            <p className="auth-switch">
              <button
                type="button"
                className="auth-link"
                onClick={() => switchMode('login')}
              >
                Back to Sign In
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
